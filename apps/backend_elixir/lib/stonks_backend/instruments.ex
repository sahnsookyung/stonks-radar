defmodule StonksBackend.Instruments do
  @moduledoc "Instrument search/resolve compatibility."

  alias StonksBackend.{InstrumentCache, Settings, Sql, TrackedTickers}

  @index_schema_version 1
  @index_last_updated_at "2026-05-25T00:00:00Z"
  @contexts ["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"]
  @reference_regex ~r/^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/
  @provider_cache_table :stonks_backend_instrument_provider_cache
  @index_cache_ttl_ms 5 * 60 * 1_000
  @provider_source "provider_symbol_lookup"
  @public_symbol_directory_source "nasdaq_trader_symbol_directory"
  @nasdaq_listed_url "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
  @nasdaq_other_listed_url "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
  @country_by_exchange %{
    "AMEX" => "US",
    "ARCA" => "US",
    "CBOE" => "US",
    "NASDAQ" => "US",
    "Nasdaq" => "US",
    "NYSE" => "US",
    "NYSEAMERICAN" => "US",
    "NYSE AMERICAN" => "US",
    "OTC" => "US",
    "KRX" => "Korea",
    "KOSPI" => "Korea",
    "KOSDAQ" => "Korea",
    "TSE" => "Japan",
    "TYO" => "Japan",
    "JPX" => "Japan",
    "LSE" => "United Kingdom",
    "TSX" => "Canada",
    "TSXV" => "Canada",
    "ASX" => "Australia",
    "XETRA" => "Germany",
    "FWB" => "Germany",
    "EPA" => "France",
    "HKEX" => "Hong Kong",
    "SSE" => "China",
    "SZSE" => "China"
  }
  @payload_atom_keys %{
    "context" => :context,
    "context_screen" => :context_screen,
    "currency" => :currency,
    "exchange" => :exchange,
    "isin" => :isin,
    "name" => :name,
    "optional_notes" => :optional_notes,
    "query" => :query,
    "symbol" => :symbol
  }

  def search(query, opts \\ []) do
    filters = search_filters(opts)
    query = query |> to_string() |> String.trim()
    normalized = normalize_search_query(query)

    cond do
      normalized == "" ->
        response(query, [], [])

      String.length(to_string(query)) > 64 ->
        response(query, [], ["query exceeds maximum length of 64"])

      minimum_warning = search_validation_warning(query, normalized) ->
        response(query, [], [minimum_warning])

      true ->
        local_entries = instrument_index()
        local_results = search_entries(local_entries, normalized, filters)

        provider_needed = provider_lookup_needed?(local_results, normalized, filters)

        provider_entries =
          if provider_needed, do: provider_lookup_entries(query, normalized), else: []

        results =
          if provider_needed do
            (local_entries ++ provider_entries)
            |> search_entries(normalized, filters)
          else
            local_results
          end

        warnings =
          if provider_needed and provider_entries == [],
            do: ["Live instrument lookup is unavailable; showing the local index."],
            else: []

        response(query, results, warnings, cache: "shared")
    end
  end

  def resolve(payload) do
    symbol = value_for(payload, "symbol")
    name = value_for(payload, "name")
    exchange = value_for(payload, "exchange")
    currency = value_for(payload, "currency")
    isin = value_for(payload, "isin")
    context = value_for(payload, "context") || "CSV_IMPORT"
    query = isin || symbol || name || ""

    results =
      search(query,
        limit: 10,
        include_advanced: true,
        include_inactive: false,
        exchange: exchange,
        context: context
      ).results

    results =
      if present?(currency) do
        matches =
          Enum.filter(
            results,
            &(String.upcase(to_string(&1["currency"])) == String.upcase(to_string(currency)))
          )

        if matches == [], do: results, else: matches
      else
        results
      end

    if results == [] do
      %{status: "NO_MATCH", confidence: "LOW", matches: []}
    else
      exact =
        Enum.filter(results, fn row ->
          normalize_symbol(row["displaySymbol"]) == normalize_symbol(symbol) ||
            "IDENTIFIER_EXACT" in Map.get(row, "matchedOn", []) ||
            (present?(isin) && normalize_symbol(row["displaySymbol"]) == normalize_symbol(isin))
        end)

      matches = if exact == [], do: results, else: exact

      %{
        status: if(length(matches) == 1, do: "MATCHED", else: "MULTIPLE_MATCHES"),
        confidence: if(exact != [] or length(matches) == 1, do: "HIGH", else: "MEDIUM"),
        matches: matches
      }
    end
  end

  def detail(id, listing_id \\ nil) do
    id = trim_value(id)
    listing_id = trim_optional_value(listing_id)
    normalized = normalize_symbol(id)
    normalized_listing = normalize_symbol(listing_id)

    cond do
      not valid_reference?(id) ->
        nil

      present?(listing_id) and not valid_reference?(listing_id) ->
        nil

      true ->
        case Enum.find(instrument_index(), &entry_matches_reference?(&1, normalized)) do
          nil -> db_detail(id, normalized_listing)
          entry -> detail_payload(entry, normalized_listing)
        end
    end
  end

  def create_review_request(payload, ip_hash) do
    with {:ok, request} <- normalize_review_request(payload) do
      existing =
        Sql.one(
          """
          select id, status
          from instrument_review_request
          where request_ip_hash = $1
            and lower(query) = lower($2)
            and context_screen = $3
            and status in ('queued', 'in_review')
            and created_at >= now() - interval '1 day'
          order by created_at desc
          limit 1
          """,
          [ip_hash, request.query, request.context_screen]
        )

      if existing do
        {:ok, %{id: to_string(existing["id"]), status: existing["status"], deduped: true}}
      else
        id =
          Sql.scalar(
            """
            insert into instrument_review_request(query, context_screen, optional_notes, request_ip_hash)
            values ($1, $2, $3, $4)
            returning id
            """,
            [request.query, request.context_screen, request.optional_notes, ip_hash]
          )

        if id do
          {:ok, %{id: to_string(id), status: "queued"}}
        else
          {:error, 503, %{detail: "Instrument review request storage unavailable"}}
        end
      end
    else
      {:error, detail} -> {:error, 422, %{detail: detail}}
    end
  end

  def refresh_index(payload) do
    InstrumentCache.invalidate_index()
    local_index = instrument_index()

    warm_queries =
      payload
      |> Map.get("symbols", default_provider_warm_symbols())
      |> normalize_symbol_list()
      |> Enum.take(provider_search_limit())

    provider_hits =
      warm_queries
      |> Enum.flat_map(fn symbol ->
        provider_lookup_entries(symbol, normalize_search_query(symbol))
      end)
      |> Enum.uniq_by(&normalize_symbol(&1.instrument_id <> ":" <> &1.listing_id))

    {:ok,
     %{
       status: "refreshed",
       source: payload["source"],
       mode: payload["mode"],
       local_index_count: length(local_index),
       provider_index_count: length(provider_hits),
       provider_lookup_enabled: provider_lookup_enabled?()
     }}
  end

  def normalize_review_request(payload) do
    query = value_for(payload, "query") |> to_string() |> String.trim()
    context = value_for(payload, "context_screen") || "HOLDING_ENTRY"
    optional_notes = value_for(payload, "optional_notes")
    optional_notes = if optional_notes, do: String.trim(to_string(optional_notes)), else: nil

    cond do
      String.length(query) < 1 ->
        {:error, "query must be at least 1 character"}

      String.length(query) > 64 ->
        {:error, "query must be at most 64 characters"}

      context not in @contexts ->
        {:error, "context_screen must be one of #{Enum.join(@contexts, ", ")}"}

      optional_notes && String.length(optional_notes) > 500 ->
        {:error, "optional_notes must be at most 500 characters"}

      true ->
        {:ok, %{query: query, context_screen: context, optional_notes: optional_notes}}
    end
  end

  def client_identity_hash(peer) do
    :crypto.hash(:sha256, to_string(peer))
    |> Base.encode16(case: :lower)
  end

  defdelegate normalize_search_query(value),
    to: StonksBackend.Instruments.Normalization,
    as: :search_query

  defdelegate normalize_symbol(value), to: StonksBackend.Instruments.Normalization, as: :symbol

  defp db_detail(id, normalized_listing) do
    row =
      Sql.one(
        """
        select co.object_key, co.display_name_en, co.display_name_ko, co.active,
               i.ticker, i.exchange, i.currency_code, i.market_data_policy
        from canonical_object co
        left join instrument i on i.canonical_object_id = co.id
        where co.object_key = $1
        limit 1
        """,
        [id]
      )

    if row, do: detail_payload(db_entry(row), normalized_listing)
  end

  defp search_filters(opts) do
    %{
      limit: opts |> Keyword.get(:limit, 10) |> parse_int(10) |> min(25) |> max(1),
      include_advanced: truthy?(Keyword.get(opts, :include_advanced, false)),
      include_inactive: truthy?(Keyword.get(opts, :include_inactive, false)),
      country: trim_optional_value(Keyword.get(opts, :country)),
      exchange: trim_optional_value(Keyword.get(opts, :exchange)),
      asset_class: trim_optional_value(Keyword.get(opts, :asset_class)),
      instrument_type: trim_optional_value(Keyword.get(opts, :instrument_type)),
      context: trim_optional_value(Keyword.get(opts, :context)) || "HOLDING_ENTRY"
    }
  end

  defp search_entries(entries, normalized, filters) do
    entries
    |> Enum.map(&search_result_for_entry(&1, normalized, filters))
    |> Enum.reject(&is_nil/1)
    |> keep_best_results()
    |> Enum.sort_by(fn row ->
      {-row["score"], row["displaySymbol"], row["listingId"], row["instrumentId"]}
    end)
    |> Enum.take(filters.limit)
  end

  defp instrument_index do
    InstrumentCache.fetch_index(@index_cache_ttl_ms, &build_instrument_index/0)
    |> elem(0)
  end

  defp build_instrument_index do
    (static_entries() ++ watchlist_entries() ++ db_entries())
    |> Enum.uniq_by(&normalize_symbol(&1.instrument_id <> ":" <> &1.listing_id))
  end

  defp db_entries do
    """
    select co.object_key, co.display_name_en, co.display_name_ko, co.active,
           i.ticker, i.exchange, i.currency_code, i.market_data_policy
    from canonical_object co
    left join instrument i on i.canonical_object_id = co.id
    where co.object_type = 'instrument'
    order by co.display_name_en
    limit 250
    """
    |> Sql.all()
    |> Enum.map(&db_entry/1)
  end

  defp db_entry(row) do
    symbol = row["ticker"] || row["object_key"]
    exchange = row["exchange"] || "UNKNOWN"
    currency = row["currency_code"] || "USD"

    entry(%{
      instrument_id: row["object_key"],
      symbol: symbol,
      name: row["display_name_en"] || row["object_key"],
      listing_id: "#{exchange}:#{symbol}",
      exchange: exchange,
      country: "US",
      currency: currency,
      asset_class: "Equity",
      instrument_type: "stock",
      sector: "Unclassified",
      quality_level: "PARTIAL",
      quality_message: "Source-backed listing metadata; classification may be incomplete.",
      is_active: truthy?(row["active"]),
      aliases: [row["display_name_ko"]],
      identifiers: []
    })
  end

  defp watchlist_entries do
    case TrackedTickers.payload() do
      {:ok, %{"entities" => entities}} when is_list(entities) ->
        entities
        |> Enum.flat_map(&watchlist_entry/1)

      _ ->
        []
    end
  end

  defp watchlist_entry(%{"route_kind" => "ticker"} = entity) do
    symbol = entity |> Map.get("symbol") |> trim_value() |> String.upcase()
    exchange = entity |> Map.get("exchange") |> trim_value()

    if symbol == "" or exchange == "" do
      []
    else
      [
        entry(%{
          instrument_id: Map.get(entity, "entity_id") || symbol,
          symbol: symbol,
          name: Map.get(entity, "legal_name") || Map.get(entity, "name_en") || symbol,
          listing_id: "#{exchange}:#{symbol}",
          exchange: exchange,
          country: Map.get(entity, "country") || country_for_exchange(exchange),
          currency: Map.get(entity, "currency") || "USD",
          asset_class: asset_class_from_watchlist(entity["asset_type"]),
          instrument_type: instrument_type_from_watchlist(entity["asset_type"]),
          sector: Map.get(entity, "sector") || "Unclassified",
          quality_level: "SOURCE_BACKED",
          quality_message:
            "Tracked ticker metadata from the shared watchlist with TradingView and configured news/source identifiers.",
          aliases:
            [
              Map.get(entity, "name_en"),
              Map.get(entity, "name_ko"),
              Map.get(entity, "legal_name")
            ] ++
              List.wrap(Map.get(entity, "aliases")),
          identifiers: watchlist_identifiers(entity),
          source_providers: ["ticker_watchlist"]
        })
      ]
    end
  end

  defp watchlist_entry(_entity), do: []

  defp watchlist_identifiers(entity) do
    [
      if(present?(entity["sec_cik"]),
        do: %{"type" => "OTHER", "value" => "CIK#{entity["sec_cik"]}"}
      ),
      if(present?(entity["tradingview_symbol"]),
        do: %{"type" => "OTHER", "value" => entity["tradingview_symbol"]}
      )
    ]
    |> Enum.reject(&is_nil/1)
  end

  defp asset_class_from_watchlist(value) do
    case value |> to_string() |> String.downcase() do
      "etf" -> "Equity"
      "fund" -> "Equity"
      "crypto" -> "Crypto / Digital Assets"
      "fixed income" -> "Fixed Income"
      _ -> "Equity"
    end
  end

  defp instrument_type_from_watchlist(value) do
    case value |> to_string() |> String.downcase() do
      "etf" -> "etf"
      "fund" -> "etf"
      "crypto" -> "crypto"
      _ -> "stock"
    end
  end

  defp static_entries do
    [
      entry(%{
        instrument_id: "AAPL",
        symbol: "AAPL",
        name: "Apple Inc.",
        listing_id: "NASDAQ:AAPL",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "stock",
        sector: "Information Technology",
        aliases: ["Apple", "Apple Computer"],
        identifiers: [
          %{"type" => "ISIN", "value" => "US0378331005"},
          %{"type" => "FIGI", "value" => "BBG000B9XRY4"}
        ]
      }),
      entry(%{
        instrument_id: "MSFT",
        symbol: "MSFT",
        name: "Microsoft Corp.",
        listing_id: "NASDAQ:MSFT",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "stock",
        sector: "Information Technology",
        aliases: ["Microsoft"],
        identifiers: [%{"type" => "ISIN", "value" => "US5949181045"}]
      }),
      entry(%{
        instrument_id: "NVDA",
        symbol: "NVDA",
        name: "NVIDIA Corporation",
        listing_id: "NASDAQ:NVDA",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "stock",
        sector: "Information Technology",
        aliases: ["Nvidia", "NVIDIA Corp"],
        identifiers: [%{"type" => "ISIN", "value" => "US67066G1040"}]
      }),
      entry(%{
        instrument_id: "TSLA",
        symbol: "TSLA",
        name: "Tesla, Inc.",
        listing_id: "NASDAQ:TSLA",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "stock",
        sector: "Consumer Discretionary",
        aliases: ["Tesla"],
        identifiers: [%{"type" => "ISIN", "value" => "US88160R1014"}]
      }),
      entry(%{
        instrument_id: "005930.KS",
        symbol: "005930.KS",
        name: "Samsung Electronics Co., Ltd.",
        listing_id: "KRX:005930",
        exchange: "KRX",
        country: "Korea",
        currency: "KRW",
        asset_class: "Equity",
        instrument_type: "stock",
        sector: "Information Technology",
        quality_level: "PARTIAL",
        quality_message:
          "Partial data: sector classification confirmed; holdings look-through not applicable.",
        aliases: ["Samsung Electronics", "삼성전자"],
        identifiers: [
          %{"type" => "ISIN", "value" => "KR7005930003"},
          %{"type" => "LOCAL_CODE", "value" => "005930"}
        ]
      }),
      entry(%{
        instrument_id: "VXUS",
        symbol: "VXUS",
        name: "Vanguard Total International Stock ETF",
        listing_id: "NASDAQ:VXUS",
        exchange: "NASDAQ",
        country: "Global ex-US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "etf",
        sector: "Multi-sector",
        quality_level: "PARTIAL",
        quality_message: "Partial data: latest fund holdings may be delayed.",
        aliases: ["Vanguard VXUS", "Total International Stock ETF"]
      }),
      entry(%{
        instrument_id: "TLT",
        symbol: "TLT",
        name: "iShares 20+ Year Treasury Bond ETF",
        listing_id: "NASDAQ:TLT",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Fixed Income",
        instrument_type: "etf",
        sector: "Government bonds",
        aliases: ["20 Year Treasury Bond ETF"]
      }),
      entry(%{
        instrument_id: "SGOV",
        symbol: "SGOV",
        name: "iShares 0-3 Month Treasury Bond ETF",
        listing_id: "NYSE:SGOV",
        exchange: "NYSE",
        country: "US",
        currency: "USD",
        asset_class: "Cash & Cash Equivalents",
        instrument_type: "etf",
        sector: "Government bonds",
        aliases: ["T-Bill ETF", "Short Treasury ETF"]
      }),
      entry(%{
        instrument_id: "QQQ",
        symbol: "QQQ",
        name: "Invesco QQQ Trust",
        listing_id: "NASDAQ:QQQ",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Equity",
        instrument_type: "etf",
        sector: "Information Technology",
        aliases: ["Nasdaq 100 ETF"]
      }),
      entry(%{
        instrument_id: "BTC",
        symbol: "BTC",
        name: "Bitcoin",
        listing_id: "Crypto:BTC",
        exchange: "Crypto",
        country: "Global",
        currency: "USD",
        asset_class: "Crypto / Digital Assets",
        instrument_type: "crypto",
        sector: "Crypto",
        quality_level: "PROXY",
        quality_message: "Proxy used: crypto reference price classification is approximate.",
        aliases: ["Bitcoin BTC"]
      }),
      entry(%{
        instrument_id: "TQQQ",
        symbol: "TQQQ",
        name: "ProShares UltraPro QQQ",
        listing_id: "NASDAQ:TQQQ",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Derivatives / Leveraged Products",
        instrument_type: "leveraged",
        sector: "Leveraged ETF",
        leverage_flag: true,
        quality_level: "PARTIAL",
        quality_message:
          "Partial data. This is a leveraged or inverse product. It may behave very differently from the underlying asset, especially over longer periods.",
        aliases: ["3x QQQ ETF"]
      }),
      entry(%{
        instrument_id: "AAPL.WS",
        symbol: "AAPL.WS",
        name: "Apple warrant",
        listing_id: "NASDAQ:AAPL.WS",
        exchange: "NASDAQ",
        country: "US",
        currency: "USD",
        asset_class: "Derivatives / Leveraged Products",
        instrument_type: "manual",
        sector: "Warrant",
        quality_level: "UNAVAILABLE",
        quality_message: "Data unavailable: advanced instrument requires manual verification.",
        aliases: ["Apple warrant"]
      })
    ]
  end

  defp entry(attrs) do
    %{
      instrument_id: attrs.instrument_id,
      symbol: attrs.symbol,
      name: attrs.name,
      listing_id: attrs.listing_id,
      exchange: attrs.exchange,
      country: attrs.country,
      currency: attrs.currency,
      asset_class: attrs.asset_class,
      instrument_type: attrs.instrument_type,
      sector: attrs.sector,
      quality_level: Map.get(attrs, :quality_level, "COMPLETE"),
      quality_message: Map.get(attrs, :quality_message, "Complete data"),
      is_active: Map.get(attrs, :is_active, true),
      leverage_flag: Map.get(attrs, :leverage_flag, false),
      inverse_flag: Map.get(attrs, :inverse_flag, false),
      aliases: Map.get(attrs, :aliases, []) |> Enum.reject(&blank?/1),
      identifiers: Map.get(attrs, :identifiers, []),
      source_providers: Map.get(attrs, :source_providers, ["local_static_seed"]),
      current_price: decimal_or_nil(Map.get(attrs, :current_price)),
      previous_close: decimal_or_nil(Map.get(attrs, :previous_close)),
      price_as_of: Map.get(attrs, :price_as_of),
      price_coverage: Map.get(attrs, :price_coverage, "unavailable"),
      calculation_eligible: Map.get(attrs, :calculation_eligible, false),
      requires_user_price: Map.get(attrs, :requires_user_price, true),
      source_observed_at: Map.get(attrs, :source_observed_at, @index_last_updated_at),
      stale_after: Map.get(attrs, :stale_after),
      hard_expires_at: Map.get(attrs, :hard_expires_at),
      staleness_state: Map.get(attrs, :staleness_state)
    }
  end

  defp search_result_for_entry(entry, normalized, filters) do
    if entry_matches_filters?(entry, filters) do
      exact_symbol = entry_exact_symbol?(entry, normalized)
      exact_name = normalize_search_query(entry.name) == normalized

      if advanced?(entry) and not filters.include_advanced and not exact_symbol and not exact_name do
        nil
      else
        {score, matched_on} = score_entry(entry, normalized, filters.context, exact_symbol)

        if score > 0 do
          result_for(entry, score, matched_on)
        end
      end
    end
  end

  defp entry_matches_filters?(entry, filters) do
    matches_filter?(filters.country, entry.country) and
      matches_filter?(filters.exchange, entry.exchange) and
      matches_filter?(filters.asset_class, entry.asset_class) and
      matches_filter?(filters.instrument_type, entry.instrument_type) and
      (entry.is_active or filters.include_inactive)
  end

  defp matches_filter?(nil, _actual), do: true
  defp matches_filter?("", _actual), do: true

  defp matches_filter?(expected, actual),
    do: String.upcase(to_string(expected)) == String.upcase(to_string(actual))

  defp entry_exact_symbol?(entry, normalized) do
    query_symbol = normalize_symbol(normalized)

    query_symbol in [
      normalize_symbol(entry.symbol),
      normalize_symbol(entry.instrument_id),
      normalize_symbol(entry.listing_id)
    ]
  end

  defp score_entry(entry, normalized, context, exact_symbol) do
    tokens = tokens_for(entry)

    {token_score, matches} =
      Enum.reduce(tokens, {0, []}, fn {kind, value}, {score, matches} ->
        {token_score, match_label} = score_token(kind, value, normalized)
        labels = if match_label, do: [match_label | matches], else: matches
        {score + token_score, labels}
      end)

    if token_score <= 0 do
      {0, []}
    else
      rank_bonus =
        0
        |> maybe_add(entry.is_active, 150)
        |> maybe_add(true, 100)
        |> maybe_add(entry.currency == "USD", 20)
        |> maybe_add(context == "BUILDER" and entry.instrument_type in ["etf", "stock"], 60)
        |> maybe_add(context == "TAX_LOT" and exact_symbol, 60)
        |> Kernel.+(quality_rank_adjustment(entry.quality_level))

      {token_score + rank_bonus, matches |> Enum.uniq() |> Enum.sort()}
    end
  end

  defp score_token(kind, value, normalized) do
    token = normalize_search_query(value)

    cond do
      token == "" ->
        {0, nil}

      token == normalized ->
        {if(kind in ["symbol", "identifier"], do: 500, else: 300), match_label(kind, "EXACT")}

      String.starts_with?(token, normalized) ->
        {if(kind in ["symbol", "identifier"], do: 250, else: 150), match_label(kind, "PREFIX")}

      String.contains?(token, normalized) ->
        {if(kind in ["symbol", "identifier"], do: 120, else: 75), match_label(kind, "CONTAINS")}

      normalize_symbol(token) == normalize_symbol(normalized) and normalize_symbol(token) != "" ->
        {500, match_label(kind, "EXACT")}

      true ->
        {0, nil}
    end
  end

  defp tokens_for(entry) do
    identifier_tokens =
      Enum.map(entry.identifiers, fn identifier ->
        {"identifier", identifier["value"] || identifier[:value]}
      end)

    [
      {"symbol", entry.symbol},
      {"symbol", entry.instrument_id},
      {"symbol", entry.listing_id},
      {"name", entry.name},
      {"exchange", entry.exchange}
      | Enum.map(entry.aliases, &{"alias", &1})
    ] ++ identifier_tokens
  end

  defp match_label("identifier", suffix), do: "IDENTIFIER_#{suffix}"
  defp match_label(kind, suffix), do: "#{String.upcase(kind)}_#{suffix}"

  defp result_for(entry, score, matched_on) do
    quality = entry.quality_level
    has_price = is_number(entry.current_price) and entry.current_price > 0

    tooltip_keys = [
      "ticker",
      "exchange",
      "asset_class",
      "instrument_type",
      "currency",
      "country",
      "data_quality",
      "sector"
    ]

    tooltip_keys =
      if advanced?(entry), do: tooltip_keys ++ ["advanced_instrument"], else: tooltip_keys

    tooltip_keys =
      if quality == "PARTIAL", do: tooltip_keys ++ ["partial_data"], else: tooltip_keys

    %{
      "instrumentId" => entry.instrument_id,
      "listingId" => entry.listing_id,
      "displaySymbol" => String.upcase(entry.symbol),
      "name" => entry.name,
      "exchange" => entry.exchange,
      "country" => entry.country,
      "currency" => entry.currency,
      "assetClass" => entry.asset_class,
      "instrumentType" => entry.instrument_type,
      "sector" => entry.sector,
      "isPrimaryListing" => true,
      "isAdvancedInstrument" => advanced?(entry),
      "isActive" => entry.is_active,
      "isStale" => quality == "STALE",
      "qualityLevel" => quality,
      "qualityMessage" => entry.quality_message,
      "metadataCoverage" => metadata_coverage_for_quality(quality),
      "priceCoverage" => entry.price_coverage,
      "calculationEligible" => entry.calculation_eligible,
      "requiresUserPrice" => entry.requires_user_price,
      "currentPrice" => entry.current_price,
      "previousClose" => entry.previous_close || entry.current_price,
      "priceAsOf" => entry.price_as_of,
      "sourceProviders" => entry.source_providers,
      "sourceObservedAt" => entry.source_observed_at,
      "staleAfter" => entry.stale_after,
      "hardExpiresAt" => entry.hard_expires_at,
      "stalenessState" => entry.staleness_state || if(has_price, do: "fresh"),
      "score" => score,
      "matchedOn" => matched_on,
      "tooltipKeys" => tooltip_keys
    }
  end

  defp provider_lookup_needed?(local_results, normalized, filters) do
    provider_lookup_enabled?() and provider_query_eligible?(normalized, filters) and
      (not Enum.any?(local_results, &exact_result_match?(&1, normalized)) or
         (quote_provider_enabled?() and exact_results_need_price?(local_results, normalized)))
  end

  defp exact_result_match?(row, normalized) do
    normalize_symbol(normalized) in [
      normalize_symbol(row["instrumentId"]),
      normalize_symbol(row["displaySymbol"]),
      normalize_symbol(row["listingId"])
    ]
  end

  defp exact_results_need_price?(local_results, normalized) do
    Enum.any?(local_results, fn row ->
      exact_result_match?(row, normalized) and
        (row["priceCoverage"] != "available" or row["requiresUserPrice"] == true)
    end)
  end

  defp provider_query_eligible?(normalized, filters) do
    String.length(normalized) >= 2 and
      filters.context in @contexts and
      (likely_symbol_query?(normalized) or String.length(normalized) >= 3)
  end

  defp provider_lookup_enabled? do
    Settings.truthy?(Settings.get(:instrument_provider_search_enabled, "true")) and
      (public_symbol_lookup_enabled?() or
         not is_nil(provider_api_key(:fmp_api_key)) or
         not is_nil(provider_api_key(:finnhub_api_key)))
  end

  defp provider_lookup_entries(query, normalized) do
    if provider_lookup_enabled?() and provider_query_eligible?(normalized, %{context: "BUILDER"}) do
      cached_provider_entries(normalized, fn ->
        fetch_provider_entries(query, normalized)
      end)
    else
      []
    end
  end

  defp cached_provider_entries(normalized, fetch_fun) do
    cache_key = {:provider_symbol_lookup, normalize_search_query(normalized)}
    now = System.monotonic_time(:millisecond)

    with {:ok, table} <- ensure_provider_cache(),
         [{^cache_key, expires_at, entries}] when expires_at > now <-
           :ets.lookup(table, cache_key) do
      entries
    else
      _ ->
        entries = fetch_fun.()
        cache_provider_entries(cache_key, entries, now)
        entries
    end
  end

  defp ensure_provider_cache do
    case :ets.whereis(@provider_cache_table) do
      :undefined ->
        {:ok, :ets.new(@provider_cache_table, [:named_table, :public, read_concurrency: true])}

      table ->
        {:ok, table}
    end
  rescue
    ArgumentError ->
      case :ets.whereis(@provider_cache_table) do
        :undefined -> {:error, :cache_unavailable}
        table -> {:ok, table}
      end
  end

  defp cache_provider_entries(cache_key, entries, now) do
    InstrumentCache.put_provider(cache_key, now + provider_cache_ttl_ms(), entries)
  end

  defp fetch_provider_entries(query, normalized) do
    keyed_entries =
      []
      |> Kernel.++(fmp_symbol_entries(query, normalized))
      |> Kernel.++(finnhub_symbol_entries(query))
      |> unique_provider_entries()

    directory_entries =
      if keyed_provider_result_complete?(keyed_entries, normalized) do
        []
      else
        public_symbol_directory_entries(query, normalized)
      end

    entries =
      keyed_entries
      |> Kernel.++(directory_entries)
      |> unique_provider_entries()
      |> Enum.take(provider_search_limit())

    if likely_symbol_query?(normalized) do
      enrich_provider_quotes(entries, normalize_symbol(query))
    else
      entries
    end
  end

  defp fmp_symbol_entries(query, normalized) do
    case provider_api_key(:fmp_api_key) do
      nil ->
        []

      api_key ->
        rows = fmp_search_request(:symbol, query, api_key)

        rows =
          if rows == [] and String.length(normalized) >= 3,
            do: fmp_search_request(:name, query, api_key),
            else: rows

        rows
        |> Enum.flat_map(&fmp_search_row_to_entry/1)
    end
  end

  defp fmp_search_request(kind, query, api_key) do
    url =
      case kind do
        :name ->
          Settings.get(
            :instrument_fmp_name_search_url,
            "https://financialmodelingprep.com/stable/search-name"
          )

        _ ->
          Settings.get(
            :instrument_fmp_symbol_search_url,
            "https://financialmodelingprep.com/stable/search-symbol"
          )
      end

    request_json(url,
      params: %{"query" => query, "apikey" => api_key},
      receive_timeout: provider_timeout_ms()
    )
    |> case do
      {:ok, rows} when is_list(rows) -> rows
      {:ok, %{"data" => rows}} when is_list(rows) -> rows
      _ -> []
    end
  end

  defp fmp_search_row_to_entry(row) when is_map(row) do
    symbol = string_value(row["symbol"])
    name = string_value(row["name"])
    exchange = first_present([row["exchangeShortName"], row["exchange"], row["stockExchange"]])
    currency = string_value(row["currency"], "USD")

    cond do
      symbol == "" or name == "" ->
        []

      exchange == "" ->
        []

      true ->
        [
          entry(%{
            instrument_id: symbol,
            symbol: symbol,
            name: name,
            listing_id: "#{exchange}:#{symbol}",
            exchange: exchange,
            country: country_for_exchange(exchange),
            currency: currency,
            asset_class: "Equity",
            instrument_type: instrument_type_from_provider(row),
            sector: "Unclassified",
            quality_level: "PARTIAL",
            quality_message:
              "Provider-backed symbol metadata. Classification may be incomplete until scheduled index refresh confirms it.",
            aliases: [row["companyName"], row["stockExchange"]],
            identifiers: [],
            source_providers: ["fmp", @provider_source],
            source_observed_at: DateTime.utc_now() |> DateTime.to_iso8601()
          })
        ]
    end
  end

  defp fmp_search_row_to_entry(_row), do: []

  defp finnhub_symbol_entries(query) do
    case provider_api_key(:finnhub_api_key) do
      nil ->
        []

      api_key ->
        Settings.get(:instrument_finnhub_symbol_lookup_url, "https://finnhub.io/api/v1/search")
        |> request_json(
          params: %{"q" => query, "token" => api_key},
          receive_timeout: provider_timeout_ms()
        )
        |> case do
          {:ok, %{"result" => rows}} when is_list(rows) -> rows
          {:ok, rows} when is_list(rows) -> rows
          _ -> []
        end
        |> Enum.flat_map(&finnhub_row_to_entry/1)
    end
  end

  defp finnhub_row_to_entry(row) when is_map(row) do
    symbol = first_present([row["symbol"], row["displaySymbol"]])
    display_symbol = first_present([row["displaySymbol"], row["symbol"]])
    name = first_present([row["description"], row["name"]])

    if symbol == "" or name == "" do
      []
    else
      exchange = exchange_from_provider_symbol(symbol)

      [
        entry(%{
          instrument_id: display_symbol,
          symbol: display_symbol,
          name: name,
          listing_id: "#{exchange}:#{display_symbol}",
          exchange: exchange,
          country: country_for_exchange(exchange),
          currency: "USD",
          asset_class: "Equity",
          instrument_type: instrument_type_from_provider(row),
          sector: "Unclassified",
          quality_level: "PARTIAL",
          quality_message:
            "Finnhub symbol lookup metadata. Classification may be incomplete until scheduled index refresh confirms it.",
          aliases: [symbol],
          identifiers: [],
          source_providers: ["finnhub", @provider_source],
          source_observed_at: DateTime.utc_now() |> DateTime.to_iso8601()
        })
      ]
    end
  end

  defp finnhub_row_to_entry(_row), do: []

  defp unique_provider_entries(entries) do
    Enum.uniq_by(entries, &normalize_symbol(&1.instrument_id <> ":" <> &1.listing_id))
  end

  defp keyed_provider_result_complete?([], _normalized), do: false

  defp keyed_provider_result_complete?(entries, normalized) do
    Enum.any?(entries, &entry_exact_symbol?(&1, normalized)) or
      length(entries) >= provider_search_limit()
  end

  defp public_symbol_directory_entries(query, normalized) do
    if public_symbol_lookup_enabled?() and
         provider_query_eligible?(normalized, %{context: "BUILDER"}) do
      symbol_query = normalize_symbol(query)
      text_query = normalize_search_query(query)

      public_symbol_directory()
      |> Enum.filter(&public_symbol_directory_match?(&1, symbol_query, text_query))
      |> Enum.take(provider_search_limit())
    else
      []
    end
  end

  defp public_symbol_directory do
    now = System.monotonic_time(:millisecond)
    cache_key = :public_symbol_directory

    with {:ok, table} <- ensure_provider_cache(),
         [{^cache_key, expires_at, entries}] when expires_at > now <-
           :ets.lookup(table, cache_key) do
      entries
    else
      _ ->
        entries = fetch_public_symbol_directory()

        InstrumentCache.put_provider(
          cache_key,
          now + public_symbol_directory_cache_ttl_ms(),
          entries
        )

        entries
    end
  end

  defp fetch_public_symbol_directory do
    [
      {Settings.get(:instrument_nasdaq_listed_url, @nasdaq_listed_url), :nasdaq_listed},
      {Settings.get(:instrument_nasdaq_other_listed_url, @nasdaq_other_listed_url), :other_listed}
    ]
    |> Enum.flat_map(fn {url, kind} ->
      case request_text(url, receive_timeout: provider_timeout_ms()) do
        {:ok, body} -> parse_public_symbol_directory(body, kind)
        _ -> []
      end
    end)
    |> unique_provider_entries()
  end

  defp parse_public_symbol_directory(body, kind) do
    body
    |> to_string()
    |> String.split(~r/\r?\n/, trim: true)
    |> Enum.drop(1)
    |> Enum.flat_map(&public_symbol_row_to_entry(&1, kind))
  end

  defp public_symbol_row_to_entry("File Creation Time:" <> _rest, _kind), do: []

  defp public_symbol_row_to_entry(row, :nasdaq_listed) do
    case String.split(row, "|") do
      [symbol, name, market_category, test_issue, _financial_status, _round_lot_size, etf | _rest] ->
        if public_symbol_row_valid?(symbol, name, test_issue) do
          exchange = nasdaq_market_category_exchange(market_category)
          [public_symbol_entry(symbol, name, exchange, etf)]
        else
          []
        end

      _ ->
        []
    end
  end

  defp public_symbol_row_to_entry(row, :other_listed) do
    case String.split(row, "|") do
      [symbol, name, exchange_code, _cqs_symbol, etf, _round_lot_size, test_issue | _rest] ->
        if public_symbol_row_valid?(symbol, name, test_issue) do
          [public_symbol_entry(symbol, name, listed_exchange_name(exchange_code), etf)]
        else
          []
        end

      _ ->
        []
    end
  end

  defp public_symbol_row_valid?(symbol, name, test_issue) do
    symbol = String.trim(to_string(symbol))
    name = String.trim(to_string(name))
    String.upcase(String.trim(to_string(test_issue))) != "Y" and symbol != "" and name != ""
  end

  defp public_symbol_entry(symbol, name, exchange, etf) do
    symbol = String.trim(symbol)
    name = clean_public_symbol_name(name)
    exchange = if exchange == "", do: "US", else: exchange

    instrument_type =
      if String.upcase(String.trim(to_string(etf))) == "Y", do: "etf", else: "stock"

    entry(%{
      instrument_id: symbol,
      symbol: symbol,
      name: name,
      listing_id: "#{exchange}:#{symbol}",
      exchange: exchange,
      country: country_for_exchange(exchange),
      currency: "USD",
      asset_class: if(instrument_type == "etf", do: "Fund", else: "Equity"),
      instrument_type: instrument_type,
      sector: "Unclassified",
      quality_level: "PARTIAL",
      quality_message:
        "Public listing-directory metadata. Add a manual price or wait for configured market-data providers to supply quote coverage.",
      aliases: [],
      identifiers: [],
      source_providers: [@public_symbol_directory_source, @provider_source],
      source_observed_at: DateTime.utc_now() |> DateTime.to_iso8601()
    })
  end

  defp public_symbol_directory_match?(entry, symbol_query, text_query) do
    symbol = normalize_symbol(entry.symbol)
    name = normalize_search_query(entry.name)

    cond do
      symbol_query == "" ->
        false

      symbol == symbol_query ->
        true

      String.length(symbol_query) >= 2 and String.starts_with?(symbol, symbol_query) ->
        true

      String.length(text_query) >= 3 and String.contains?(name, text_query) ->
        true

      true ->
        false
    end
  end

  defp nasdaq_market_category_exchange(category) do
    case String.upcase(String.trim(to_string(category))) do
      "Q" -> "NASDAQ"
      "G" -> "NASDAQ"
      "S" -> "NASDAQ"
      _ -> "NASDAQ"
    end
  end

  defp listed_exchange_name(code) do
    case String.upcase(String.trim(to_string(code))) do
      "A" -> "NYSEAMERICAN"
      "N" -> "NYSE"
      "P" -> "ARCA"
      "Z" -> "CBOE"
      "V" -> "IEX"
      _ -> "US"
    end
  end

  defp clean_public_symbol_name(name) do
    name
    |> to_string()
    |> String.trim()
    |> String.replace(~r/\s+/, " ")
  end

  defp enrich_provider_quotes(entries, normalized_symbol) do
    case provider_api_key(:fmp_api_key) do
      nil ->
        entries

      api_key ->
        quote = fmp_quote(normalized_symbol, api_key)

        Enum.map(entries, fn entry ->
          if normalize_symbol(entry.symbol) == normalized_symbol and is_number(quote.price) do
            %{entry | current_price: quote.price, previous_close: quote.price}
            |> Map.put(:price_as_of, quote.observed_at)
            |> Map.put(:price_coverage, "available")
            |> Map.put(:calculation_eligible, true)
            |> Map.put(:requires_user_price, false)
            |> Map.put(:quality_level, "PARTIAL")
            |> Map.put(
              :quality_message,
              "Provider-backed symbol metadata with latest quote snapshot."
            )
            |> Map.put(:source_observed_at, quote.observed_at)
            |> Map.put(:staleness_state, "fresh")
            |> Map.update!(:source_providers, &Enum.uniq(["fmp_quote_short" | &1]))
          else
            entry
          end
        end)
    end
  end

  defp fmp_quote(symbol, api_key) do
    Settings.get(
      :instrument_fmp_quote_short_url,
      "https://financialmodelingprep.com/stable/quote-short"
    )
    |> request_json(
      params: %{"symbol" => symbol, "apikey" => api_key},
      receive_timeout: provider_timeout_ms()
    )
    |> case do
      {:ok, [row | _]} when is_map(row) ->
        %{
          price: decimal_or_nil(row["price"]),
          observed_at: DateTime.utc_now() |> DateTime.to_iso8601()
        }

      {:ok, %{"price" => price}} ->
        %{price: decimal_or_nil(price), observed_at: DateTime.utc_now() |> DateTime.to_iso8601()}

      _ ->
        %{price: nil, observed_at: nil}
    end
  end

  defp request_json(url, opts) do
    request_fun = Settings.get(:instrument_provider_request_fun, &Req.get/2)

    case request_fun.(url, opts) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_list(body) ->
        {:ok, body}

      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, body}

      {:ok, %{status: status, body: body}} when status in 200..299 ->
        Jason.decode(to_string(body))

      _ ->
        {:error, :request_failed}
    end
  rescue
    _ -> {:error, :request_failed}
  end

  defp request_text(url, opts) do
    request_fun = Settings.get(:instrument_provider_request_fun, &Req.get/2)

    case request_fun.(url, opts) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_binary(body) ->
        {:ok, body}

      {:ok, %{status: status, body: body}} when status in 200..299 ->
        {:ok, to_string(body)}

      _ ->
        {:error, :request_failed}
    end
  rescue
    _ -> {:error, :request_failed}
  end

  defp keep_best_results(results) do
    results
    |> Enum.reduce(%{}, fn row, acc ->
      key = row["listingId"]
      current = Map.get(acc, key)

      if current == nil or better_search_result?(row, current) do
        Map.put(acc, key, row)
      else
        acc
      end
    end)
    |> Map.values()
  end

  defp better_search_result?(candidate, current) do
    candidate_quality_rank = result_quality_rank(candidate)
    current_quality_rank = result_quality_rank(current)

    candidate_quality_rank > current_quality_rank or
      (candidate_quality_rank == current_quality_rank and candidate["score"] > current["score"])
  end

  defp result_quality_rank(row) do
    0
    |> maybe_add(row["calculationEligible"] == true, 1_000)
    |> maybe_add(row["priceCoverage"] == "available", 500)
    |> maybe_add(row["requiresUserPrice"] == false, 250)
    |> Kernel.+(metadata_quality_rank(row["qualityLevel"]))
  end

  defp metadata_quality_rank("COMPLETE"), do: 30
  defp metadata_quality_rank("PARTIAL"), do: 20
  defp metadata_quality_rank("STALE"), do: 10
  defp metadata_quality_rank(_quality), do: 0

  defp detail_payload(entry, normalized_listing) do
    listings =
      [
        %{
          "listingId" => entry.listing_id,
          "instrumentId" => entry.instrument_id,
          "displaySymbol" => entry.symbol,
          "exchangeCode" => entry.exchange,
          "exchangeName" => entry.exchange,
          "country" => entry.country,
          "tradingCurrency" => entry.currency,
          "listingType" => "PRIMARY",
          "isPrimaryListing" => true,
          "isActive" => entry.is_active,
          "localCode" => local_code(entry)
        }
      ]
      |> filter_detail_listings(normalized_listing)

    if listings == [] do
      nil
    else
      %{
        "instrumentId" => entry.instrument_id,
        "symbol" => entry.symbol,
        "name" => entry.name,
        "assetClass" => entry.asset_class,
        "instrumentType" => entry.instrument_type,
        "country" => entry.country,
        "currency" => entry.currency,
        "sector" => entry.sector,
        "themeTags" => [],
        "isActive" => entry.is_active,
        "isAdvancedInstrument" => advanced?(entry),
        "dataQualityLevel" => entry.quality_level,
        "dataQualityMessage" => entry.quality_message,
        "aliases" => entry.aliases,
        "identifiers" => entry.identifiers,
        "listings" => listings,
        "dataQualityIssues" => data_quality_issues(entry)
      }
    end
  end

  defp filter_detail_listings(listings, ""), do: listings

  defp filter_detail_listings(listings, normalized_listing) do
    Enum.filter(listings, &(normalize_symbol(&1["listingId"]) == normalized_listing))
  end

  defp entry_matches_reference?(_entry, ""), do: false

  defp entry_matches_reference?(entry, normalized) do
    references =
      [
        normalize_symbol(entry.instrument_id),
        normalize_symbol(entry.symbol),
        normalize_symbol(entry.listing_id),
        normalize_symbol(local_code(entry))
      ]
      |> Enum.reject(&blank?/1)

    normalized in references
  end

  defp local_code(entry) do
    entry.identifiers
    |> Enum.find_value(fn identifier ->
      type = identifier["type"] || identifier[:type]
      value = identifier["value"] || identifier[:value]
      if type == "LOCAL_CODE", do: value
    end)
  end

  defp data_quality_issues(%{quality_level: "COMPLETE"}), do: []

  defp data_quality_issues(entry) do
    [
      %{
        "entityType" => "INSTRUMENT",
        "entityId" => entry.instrument_id,
        "severity" =>
          if(entry.quality_level in ["PARTIAL", "STALE"], do: "WARNING", else: "INFO"),
        "issueType" => entry.quality_level,
        "message" => entry.quality_message,
        "detectedAt" => @index_last_updated_at,
        "status" => "OPEN"
      }
    ]
  end

  defp response(query, results, warnings, opts \\ []) do
    watchlist_count = length(watchlist_entries())

    %{
      query: query,
      results: results,
      items: results,
      warnings: warnings,
      cache: Keyword.get(opts, :cache, "none"),
      dataFreshness: %{
        instrumentIndexLastUpdatedAt: @index_last_updated_at,
        observedAt: @index_last_updated_at,
        status: "ACTIVE",
        stalenessState: "active",
        ageSeconds: 0,
        staleAfter: nil,
        hardExpiresAt: nil,
        source: "local_scheduled_index",
        schemaVersion: @index_schema_version,
        providerStatuses: [
          %{
            source: "local_static_seed",
            status: "loaded",
            generated_at: @index_last_updated_at,
            instrument_count: length(static_entries())
          },
          %{
            source: "ticker_watchlist",
            status: if(watchlist_count > 0, do: "loaded", else: "missing"),
            generated_at: @index_last_updated_at,
            instrument_count: watchlist_count
          },
          %{
            source: @provider_source,
            status: if(provider_lookup_enabled?(), do: "configured", else: "disabled"),
            generated_at: @index_last_updated_at,
            instrument_count: nil
          },
          %{
            source: @public_symbol_directory_source,
            status: if(public_symbol_lookup_enabled?(), do: "configured", else: "disabled"),
            generated_at: @index_last_updated_at,
            instrument_count: nil
          }
        ]
      }
    }
  end

  defp search_validation_warning(_query, normalized) do
    min_length = if likely_symbol_query?(normalized), do: 1, else: 2

    if String.length(normalized) < min_length do
      "#{min_length}-character minimum for this query type"
    end
  end

  defp likely_symbol_query?(normalized), do: Regex.match?(~r/^[a-z0-9.\-\/]+$/, normalized)

  defp advanced?(entry) do
    source =
      "#{entry.instrument_type} #{entry.asset_class} #{entry.sector} #{entry.name}"
      |> String.downcase()

    entry.leverage_flag || entry.inverse_flag ||
      Enum.any?(
        ["warrant", "preferred", "right", "unit", "option", "future", "leveraged"],
        &String.contains?(source, &1)
      )
  end

  defp metadata_coverage_for_quality("COMPLETE"), do: "full"

  defp metadata_coverage_for_quality(quality)
       when quality in ["PARTIAL", "STALE", "PROXY", "ESTIMATED"], do: "partial"

  defp metadata_coverage_for_quality(_quality), do: "unavailable"

  defp quality_rank_adjustment("STALE"), do: -100
  defp quality_rank_adjustment("UNAVAILABLE"), do: -200
  defp quality_rank_adjustment(_quality), do: 0

  defp maybe_add(score, true, value), do: score + value
  defp maybe_add(score, _condition, _value), do: score

  defp default_provider_warm_symbols do
    watchlist_entries()
    |> Enum.map(& &1.symbol)
    |> Enum.reject(&blank?/1)
    |> Enum.uniq()
  end

  defp normalize_symbol_list(value),
    do: StonksBackend.Instruments.Normalization.provider_symbol_list(value)

  defp provider_api_key(:fmp_api_key) do
    Settings.get(:fmp_api_key)
    |> present_api_key()
    |> case do
      nil -> Settings.get(:market_data_api_key) |> present_api_key()
      api_key -> api_key
    end
  end

  defp provider_api_key(:finnhub_api_key) do
    Settings.get(:finnhub_api_key)
    |> present_api_key()
  end

  defp public_symbol_lookup_enabled? do
    Settings.truthy?(Settings.get(:instrument_public_symbol_lookup_enabled, "true"))
  end

  defp quote_provider_enabled? do
    not is_nil(provider_api_key(:fmp_api_key))
  end

  defp present_api_key(nil), do: nil

  defp present_api_key(value) do
    value = value |> to_string() |> String.trim()
    if value == "", do: nil, else: value
  end

  defp provider_search_limit do
    Settings.get(:instrument_provider_search_limit, "8")
    |> parse_int(8)
    |> max(1)
    |> min(10)
  end

  defp provider_cache_ttl_ms do
    Settings.get(:instrument_provider_search_cache_seconds, "900")
    |> parse_int(900)
    |> max(60)
    |> min(86_400)
    |> Kernel.*(1000)
  end

  defp public_symbol_directory_cache_ttl_ms do
    Settings.get(:instrument_public_symbol_directory_cache_seconds, "86400")
    |> parse_int(86_400)
    |> max(300)
    |> min(604_800)
    |> Kernel.*(1000)
  end

  defp provider_timeout_ms do
    Settings.get(
      :instrument_provider_search_timeout_seconds,
      Settings.get(:market_data_fetch_timeout_seconds, "8")
    )
    |> parse_int(8)
    |> max(1)
    |> min(20)
    |> Kernel.*(1000)
  end

  defp first_present(values, default \\ "") do
    values
    |> Enum.find_value(fn value ->
      text = string_value(value)
      if text == "", do: nil, else: text
    end)
    |> case do
      nil -> default
      text -> text
    end
  end

  defp string_value(value, default \\ "")
  defp string_value(nil, default), do: default

  defp string_value(value, default) do
    value = value |> to_string() |> String.trim()
    if value == "", do: default, else: value
  end

  defp country_for_exchange(exchange) do
    normalized =
      exchange
      |> to_string()
      |> String.trim()
      |> String.upcase()

    Map.get(@country_by_exchange, normalized, if(normalized == "", do: "Unknown", else: "US"))
  end

  defp exchange_from_provider_symbol(symbol) do
    symbol = to_string(symbol)

    cond do
      String.ends_with?(symbol, ".KS") -> "KRX"
      String.ends_with?(symbol, ".KQ") -> "KRX"
      String.ends_with?(symbol, ".T") -> "TSE"
      String.ends_with?(symbol, ".TO") -> "TSX"
      true -> "US"
    end
  end

  defp instrument_type_from_provider(row) do
    text =
      [row["type"], row["instrumentType"], row["exchange"], row["name"], row["description"]]
      |> Enum.map(&to_string/1)
      |> Enum.join(" ")
      |> String.downcase()

    cond do
      String.contains?(text, "etf") -> "etf"
      String.contains?(text, "fund") -> "etf"
      String.contains?(text, "crypto") -> "crypto"
      true -> "stock"
    end
  end

  defp decimal_or_nil(nil), do: nil
  defp decimal_or_nil(%Decimal{} = decimal), do: Decimal.to_float(decimal)
  defp decimal_or_nil(value) when is_integer(value), do: value / 1
  defp decimal_or_nil(value) when is_float(value), do: value

  defp decimal_or_nil(value) do
    case Float.parse(to_string(value)) do
      {number, _rest} when number > 0 -> number
      _ -> nil
    end
  end

  defp value_for(map, key) when is_map(map) do
    Map.get(map, key) || Map.get(map, Map.get(@payload_atom_keys, key))
  end

  defp value_for(_map, _key), do: nil

  defp valid_reference?(value), do: present?(value) and Regex.match?(@reference_regex, value)

  defp trim_optional_value(nil), do: nil

  defp trim_optional_value(value) do
    case trim_value(value) do
      "" -> nil
      trimmed -> trimmed
    end
  end

  defp trim_value(nil), do: ""
  defp trim_value(value), do: value |> to_string() |> String.trim()

  defp present?(value), do: not blank?(value)
  defp blank?(nil), do: true
  defp blank?(value) when is_binary(value), do: String.trim(value) == ""
  defp blank?(_value), do: false

  defp truthy?(value) when value in [true, "true", "t", "1", 1], do: true
  defp truthy?(_value), do: false

  defp parse_int(value, _default) when is_integer(value), do: value

  defp parse_int(value, default) do
    case Integer.parse(to_string(value || default)) do
      {parsed, ""} -> parsed
      _ -> default
    end
  end
end
