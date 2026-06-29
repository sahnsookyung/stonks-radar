defmodule StonksBackend.Instruments do
  @moduledoc "Instrument search/resolve compatibility."

  alias StonksBackend.Sql

  @index_schema_version 1
  @index_last_updated_at "2026-05-25T00:00:00Z"
  @contexts ["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"]
  @reference_regex ~r/^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/
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
        results =
          instrument_index()
          |> Enum.map(&search_result_for_entry(&1, normalized, filters))
          |> Enum.reject(&is_nil/1)
          |> keep_best_results()
          |> Enum.sort_by(fn row ->
            {-row["score"], row["displaySymbol"], row["listingId"], row["instrumentId"]}
          end)
          |> Enum.take(filters.limit)

        response(query, results, [], cache: "miss")
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
            (present?(isin) && "IDENTIFIER_EXACT" in Map.get(row, "matchedOn", []))
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

  def refresh_index(payload),
    do: {:ok, %{status: "refreshed", source: payload["source"], mode: payload["mode"]}}

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

  def normalize_search_query(value) do
    value
    |> to_string()
    |> String.trim()
    |> String.downcase()
  end

  def normalize_symbol(nil), do: ""

  def normalize_symbol(value) do
    value
    |> to_string()
    |> String.upcase()
    |> String.replace(~r/[^A-Z0-9]/, "")
  end

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

  defp instrument_index do
    (static_entries() ++ db_entries())
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
      source_providers: Map.get(attrs, :source_providers, ["local_static_seed"])
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
      "priceCoverage" => "unavailable",
      "calculationEligible" => false,
      "requiresUserPrice" => true,
      "sourceProviders" => entry.source_providers,
      "sourceObservedAt" => @index_last_updated_at,
      "score" => score,
      "matchedOn" => matched_on,
      "tooltipKeys" => tooltip_keys
    }
  end

  defp keep_best_results(results) do
    results
    |> Enum.reduce(%{}, fn row, acc ->
      key = row["listingId"]
      current = Map.get(acc, key)

      if current == nil or row["score"] > current["score"] do
        Map.put(acc, key, row)
      else
        acc
      end
    end)
    |> Map.values()
  end

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
