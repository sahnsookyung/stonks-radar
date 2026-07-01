defmodule StonksBackend.MarketData do
  @moduledoc "Public market history read path."

  alias StonksBackend.{Settings, Sql}

  @symbol_regex ~r/^[A-Z0-9][A-Z0-9.\-:]{0,19}$/
  @max_symbols 8
  @max_symbol_query_length 256
  @max_history_days 1_095
  @us_market_timezone "America/New_York"
  @license_limited_reason "No source-policy-approved stored daily bars are available for public display. Public routes do not spend provider quota or fetch live licensed market data on demand; use the TradingView widget for public visual market display until scheduled stored data is approved."
  @provider_order ["twelve_data", "alpha_vantage", "fmp"]

  def history(symbols, start_date, end_date) do
    with {:ok, start_date} <- Date.from_iso8601(start_date),
         {:ok, end_date} <- Date.from_iso8601(end_date),
         {:ok, symbol_list} <- validate_symbols(symbols),
         :ok <- validate_window(start_date, end_date) do
      {:ok, stored_history_payload(symbol_list, start_date, end_date)}
    else
      {:error, reason} when is_binary(reason) -> {:error, :input, reason}
      {:error, reason} -> {:error, :input, to_string(reason)}
    end
  end

  def refresh_history(payload) do
    with {:ok, symbol} <- refresh_symbol(payload),
         {:ok, {start_date, end_date}} <- refresh_window(payload) do
      provider_order = market_provider_order()

      provider_order
      |> Enum.reduce_while([], fn provider_key, attempts ->
        case fetch_provider_history(provider_key, symbol, start_date, end_date) do
          {:ok, points} when points != [] ->
            stored = store_refreshed_points(provider_key, symbol, start_date, end_date, points)

            {:halt,
             {:ok,
              %{
                status: "ready",
                provider_key: provider_key,
                symbol: symbol,
                start: Date.to_iso8601(start_date),
                end: Date.to_iso8601(end_date),
                points: length(points),
                stored: stored,
                elixir_component: "market_history_refresh"
              }}}

          {:ok, []} ->
            {:cont, [%{provider_key: provider_key, status: "empty"} | attempts]}

          {:error, :missing_api_key} ->
            {:cont, [%{provider_key: provider_key, status: "missing_api_key"} | attempts]}

          {:error, reason} ->
            {:cont,
             [%{provider_key: provider_key, status: "failed", reason: inspect(reason)} | attempts]}
        end
      end)
      |> case do
        {:ok, result} ->
          {:ok, result}

        attempts ->
          {:error,
           %{
             status: "provider_unavailable",
             symbol: symbol,
             start: Date.to_iso8601(start_date),
             end: Date.to_iso8601(end_date),
             attempts: Enum.reverse(attempts),
             elixir_component: "market_history_refresh"
           }}
      end
    end
  end

  def configured_provider_api_key(provider_key), do: provider_api_key(to_string(provider_key))

  defp refresh_symbol(payload) do
    symbol =
      payload
      |> Map.get("symbol")
      |> to_string()
      |> String.trim()
      |> String.upcase()

    if Regex.match?(@symbol_regex, symbol), do: {:ok, symbol}, else: {:error, :invalid_symbol}
  end

  defp refresh_window(payload) do
    cond do
      is_binary(payload["start"]) and is_binary(payload["end"]) ->
        with {:ok, start_date} <- Date.from_iso8601(String.slice(payload["start"], 0, 10)),
             {:ok, end_date} <- Date.from_iso8601(String.slice(payload["end"], 0, 10)),
             :ok <- validate_window(start_date, end_date) do
          {:ok, {start_date, end_date}}
        end

      true ->
        end_date =
          case payload["market_session_date"] do
            value when is_binary(value) ->
              case Date.from_iso8601(String.slice(value, 0, 10)) do
                {:ok, date} -> date
                _ -> Date.utc_today()
              end

            _ ->
              Date.utc_today()
          end

        days =
          payload
          |> Map.get(
            "window_days",
            Map.get(payload, "days", Settings.get(:market_data_snapshot_window_days, 1_095))
          )
          |> normalize_int(1_095)
          |> max(1)
          |> min(@max_history_days)

        start_date = Date.add(end_date, -days)
        {:ok, {start_date, end_date}}
    end
  end

  defp market_provider_order do
    Settings.get(:market_data_provider_order, "twelve_data,alpha_vantage,fmp")
    |> to_string()
    |> String.split(",", trim: true)
    |> Enum.map(&(&1 |> String.trim() |> String.downcase()))
    |> Enum.filter(&(&1 in @provider_order))
    |> case do
      [] -> @provider_order
      providers -> providers
    end
  end

  defp fetch_provider_history(provider_key, symbol, start_date, end_date) do
    with {:ok, api_key} <- provider_api_key(provider_key),
         {:ok, payload} <- provider_request(provider_key, api_key, symbol, start_date, end_date) do
      {:ok, parse_provider_points(provider_key, payload, start_date, end_date)}
    end
  end

  defp provider_api_key("twelve_data") do
    provider_api_key_with_fallback(:twelve_data_api_key)
  end

  defp provider_api_key("alpha_vantage") do
    provider_api_key_with_fallback(:alpha_vantage_api_key)
  end

  defp provider_api_key("fmp") do
    provider_api_key_with_fallback(:fmp_api_key)
  end

  defp provider_api_key(_), do: {:error, :missing_api_key}

  defp provider_api_key_with_fallback(provider_key) do
    case Settings.get(provider_key) |> present_api_key() do
      {:ok, api_key} -> {:ok, api_key}
      {:error, :missing_api_key} -> Settings.get(:market_data_api_key) |> present_api_key()
    end
  end

  defp present_api_key(nil), do: {:error, :missing_api_key}

  defp present_api_key(value) do
    value = value |> to_string() |> String.trim()
    if value == "", do: {:error, :missing_api_key}, else: {:ok, value}
  end

  defp provider_request("twelve_data", api_key, symbol, start_date, end_date) do
    Req.get("https://api.twelvedata.com/time_series",
      params: %{
        "symbol" => symbol,
        "interval" => "1day",
        "start_date" => Date.to_iso8601(start_date),
        "end_date" => Date.to_iso8601(end_date),
        "order" => "ASC",
        "outputsize" => "5000",
        "apikey" => api_key
      },
      receive_timeout: market_timeout_ms()
    )
    |> json_response()
    |> reject_twelve_data_errors()
  end

  defp provider_request("alpha_vantage", api_key, symbol, _start_date, _end_date) do
    Req.get("https://www.alphavantage.co/query",
      params: %{
        "function" => "TIME_SERIES_DAILY",
        "symbol" => symbol,
        "outputsize" => "compact",
        "apikey" => api_key
      },
      receive_timeout: market_timeout_ms()
    )
    |> json_response()
    |> reject_alpha_vantage_errors()
  end

  defp provider_request("fmp", api_key, symbol, start_date, end_date) do
    Req.get("https://financialmodelingprep.com/stable/historical-price-eod/full",
      params: %{
        "symbol" => symbol,
        "from" => Date.to_iso8601(start_date),
        "to" => Date.to_iso8601(end_date),
        "apikey" => api_key
      },
      receive_timeout: market_timeout_ms()
    )
    |> json_response()
  end

  defp provider_request(_, _, _, _, _), do: {:error, :unsupported_provider}

  defp json_response({:ok, %{status: status, body: body}})
       when status in 200..299 and is_map(body),
       do: {:ok, body}

  defp json_response({:ok, %{status: status, body: body}})
       when status in 200..299 and is_list(body),
       do: {:ok, body}

  defp json_response({:ok, %{status: status, body: body}}) when status in 200..299 do
    case Jason.decode(to_string(body)) do
      {:ok, payload} -> {:ok, payload}
      _ -> {:error, :invalid_json}
    end
  end

  defp json_response({:ok, %{status: status}}), do: {:error, {:http_status, status}}
  defp json_response({:error, reason}), do: {:error, reason}

  defp reject_twelve_data_errors({:ok, %{"status" => "error", "message" => message}}),
    do: {:error, {:provider_error, message}}

  defp reject_twelve_data_errors(result), do: result

  defp reject_alpha_vantage_errors({:ok, payload}) when is_map(payload) do
    message = payload["Note"] || payload["Information"] || payload["Error Message"]
    if is_binary(message), do: {:error, {:provider_error, message}}, else: {:ok, payload}
  end

  defp reject_alpha_vantage_errors(result), do: result

  defp parse_provider_points("twelve_data", %{"values" => values}, start_date, end_date)
       when is_list(values) do
    values
    |> Enum.map(&point_from_map(&1, "datetime", close_fields: ["close"]))
    |> filter_valid_points(start_date, end_date)
  end

  defp parse_provider_points(
         "alpha_vantage",
         %{"Time Series (Daily)" => rows},
         start_date,
         end_date
       )
       when is_map(rows) do
    rows
    |> Enum.map(fn {date, row} ->
      %{
        "date" => date,
        "open" => row["1. open"],
        "high" => row["2. high"],
        "low" => row["3. low"],
        "close" => row["4. close"],
        "volume" => row["5. volume"]
      }
    end)
    |> Enum.map(&point_from_map(&1, "date", close_fields: ["close"]))
    |> filter_valid_points(start_date, end_date)
  end

  defp parse_provider_points("fmp", payload, start_date, end_date) do
    rows = if is_map(payload), do: payload["historical"], else: payload

    if is_list(rows) do
      rows
      |> Enum.map(
        &point_from_map(&1, "date",
          close_fields: ["adjClose", "close"],
          adjusted_field: "adjClose"
        )
      )
      |> filter_valid_points(start_date, end_date)
    else
      []
    end
  end

  defp parse_provider_points(_, _, _, _), do: []

  defp point_from_map(row, date_field, opts) when is_map(row) do
    date = row[date_field] |> to_string() |> String.slice(0, 10)
    close = first_decimal(row, Keyword.get(opts, :close_fields, ["close"]))
    adjusted_field = Keyword.get(opts, :adjusted_field)

    %{
      date: date,
      open: decimal_or_nil(row["open"]),
      high: decimal_or_nil(row["high"]),
      low: decimal_or_nil(row["low"]),
      close: close,
      adjusted_close: if(adjusted_field, do: decimal_or_nil(row[adjusted_field]), else: nil),
      volume: decimal_or_nil(row["volume"])
    }
  end

  defp point_from_map(_, _date_field, _opts), do: nil

  defp filter_valid_points(points, start_date, end_date) do
    points
    |> Enum.reject(&is_nil/1)
    |> Enum.filter(fn point ->
      with {:ok, date} <- Date.from_iso8601(point.date),
           true <- Date.compare(date, start_date) != :lt,
           true <- Date.compare(date, end_date) != :gt,
           true <- valid_ohlc?(point) do
        true
      else
        _ -> false
      end
    end)
    |> Enum.uniq_by(& &1.date)
    |> Enum.sort_by(& &1.date)
  end

  defp valid_ohlc?(%{close: close} = point) do
    is_number(close) and close > 0 and
      Enum.all?([point.open, point.high, point.low], fn
        nil -> true
        value -> value > 0
      end) and
      (is_nil(point.high) or is_nil(point.low) or point.high >= point.low)
  end

  defp store_refreshed_points(provider_key, symbol, start_date, end_date, points) do
    policy = source_policy(provider_key)
    policy_json = Jason.encode!(policy)

    stored =
      points
      |> Enum.map(&upsert_market_price_bar(provider_key, symbol, &1, policy_json))
      |> Enum.count(& &1)

    %{
      rows: stored,
      requested_start: Date.to_iso8601(start_date),
      requested_end: Date.to_iso8601(end_date),
      source_policy: policy
    }
  end

  defp upsert_market_price_bar(provider_key, symbol, point, policy_json) do
    source_hash =
      "sha256:" <>
        (:crypto.hash(
           :sha256,
           Jason.encode!(%{provider: provider_key, symbol: symbol, point: point})
         )
         |> Base.encode16(case: :lower))

    Sql.execute(
      """
      insert into market_price_bar (
        symbol, interval, price_date, provider_key, open, high, low, close,
        adjusted_close, volume, currency_code, exchange, timezone,
        provider_price_timestamp, source_hash, source_revision, is_adjusted,
        is_suspect, quality_state, quality_json, source_policy_json, updated_at
      )
      values (
        $1, '1day', cast($2 as date), $3, $4, $5, $6, $7,
        $8, $9, 'USD', null, $10,
        cast($11 as timestamptz), $12, $13, $14,
        false, 'valid', $15::jsonb, $16::jsonb, now()
      )
      on conflict (symbol, interval, price_date, provider_key) do update set
        open = excluded.open,
        high = excluded.high,
        low = excluded.low,
        close = excluded.close,
        adjusted_close = excluded.adjusted_close,
        volume = excluded.volume,
        provider_price_timestamp = excluded.provider_price_timestamp,
        source_hash = excluded.source_hash,
        source_revision = excluded.source_revision,
        is_adjusted = excluded.is_adjusted,
        is_suspect = false,
        quality_state = 'valid',
        quality_json = excluded.quality_json,
        source_policy_json = excluded.source_policy_json,
        ingested_at = now(),
        updated_at = now()
      """,
      [
        symbol,
        point.date,
        provider_key,
        point.open,
        point.high,
        point.low,
        point.close,
        point.adjusted_close,
        point.volume,
        @us_market_timezone,
        "#{point.date}T00:00:00Z",
        source_hash,
        String.slice(source_hash, 7, 16),
        not is_nil(point.adjusted_close),
        Jason.encode!(%{elixir_component: "market_history_refresh"}),
        policy_json
      ]
    )

    true
  rescue
    _ -> false
  end

  defp source_policy(provider_key) do
    public_allowed =
      Settings.get(:market_data_public_display_allowlist, "")
      |> to_string()
      |> String.split(",", trim: true)
      |> Enum.map(&String.trim/1)
      |> Enum.member?(provider_key)

    %{
      "provider_key" => provider_key,
      "endpoint_key" => "daily_prices",
      "normalized_storage_allowed" => true,
      "raw_public_allowed" => public_allowed,
      "raw_retention_days" => 0,
      "copyright_mode" => "provider_structured_daily_bars",
      "elixir_component" => "market_history_refresh"
    }
  end

  defp first_decimal(row, fields) do
    fields
    |> Enum.find_value(&decimal_or_nil(row[&1]))
  end

  defp decimal_or_nil(nil), do: nil
  defp decimal_or_nil(%Decimal{} = decimal), do: Decimal.to_float(decimal)
  defp decimal_or_nil(value) when is_integer(value), do: value / 1
  defp decimal_or_nil(value) when is_float(value), do: value

  defp decimal_or_nil(value) do
    case Float.parse(to_string(value)) do
      {number, _} -> number
      _ -> nil
    end
  end

  defp market_timeout_ms do
    Settings.get(
      :market_data_fetch_timeout_seconds,
      Settings.get(:source_fetch_timeout_seconds, 20)
    )
    |> normalize_int(20)
    |> max(1)
    |> Kernel.*(1000)
  end

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) do
    case Integer.parse(to_string(value || default)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  def cache_headers(%{status: "ok"} = payload) do
    digest =
      payload
      |> Map.take([
        :status,
        :symbols,
        :start,
        :end,
        :market_data_version,
        :market_data_snapshot_id,
        :provider
      ])
      |> Jason.encode!()
      |> then(&:crypto.hash(:sha256, &1))
      |> Base.encode16(case: :lower)
      |> String.slice(0, 24)

    [
      {"cache-control", "public, max-age=300, s-maxage=900, stale-while-revalidate=300"},
      {"etag", ~s("market-history-#{digest}")},
      {"vary", "Accept-Encoding"},
      {"x-market-data-source", "stored-snapshot"}
    ]
  end

  def cache_headers(%{status: "license_limited"}) do
    [{"cache-control", "no-store"}, {"x-market-data-source", "license-limited"}]
  end

  def cache_headers(_), do: [{"cache-control", "no-store"}]

  def license_limited_payload(symbols, start_date, end_date, reason \\ @license_limited_reason) do
    fetched_at = DateTime.utc_now() |> DateTime.to_iso8601()

    %{
      status: "license_limited",
      provider: "tradingview_widget_only",
      source_note: reason,
      cache: "miss",
      display_mode: "public",
      display_status: "license_limited",
      data_freshness: %{
        provider: "tradingview_widget_only",
        provider_timestamp: nil,
        fetched_at: fetched_at,
        source_observed_at: nil,
        market_session_date: nil,
        complete_through: nil,
        hard_expires_at: nil,
        staleness_state: "license_limited",
        calculation_eligible: false,
        delayed_by_seconds: nil,
        exchange_timezone: @us_market_timezone,
        delay_label: "license-limited",
        is_same_day_valid: false,
        is_public_display_allowed: false,
        staleness_reason: reason,
        license_mode: "public_display_not_allowed",
        source_url: "https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/"
      },
      provider_budget_status: [],
      symbols: symbols,
      start: Date.to_iso8601(start_date),
      end: Date.to_iso8601(end_date),
      series: Enum.map(symbols, &%{symbol: &1, points: []}),
      warnings: [reason]
    }
  end

  def stored_history_payload(symbols, start_date, end_date, rows \\ nil) do
    rows = rows || stored_history_rows(symbols, start_date, end_date)

    if rows == [] do
      license_limited_payload(symbols, start_date, end_date)
    else
      stored_payload_from_rows(symbols, start_date, end_date, rows)
    end
  end

  def stored_payload_from_rows(symbols, start_date, end_date, rows) do
    chosen_rows = choose_rows(rows)
    series = Enum.map(symbols, &series_for_symbol(&1, chosen_rows))

    if Enum.any?(series, &(Map.get(&1, :points) == [])) do
      license_limited_payload(symbols, start_date, end_date)
    else
      snapshot_ids =
        chosen_rows
        |> Enum.map(&Map.get(&1, "market_data_snapshot_id"))
        |> Enum.reject(&blank?/1)
        |> Enum.map(&to_string/1)
        |> Enum.uniq()
        |> Enum.sort()

      complete_through =
        series
        |> Enum.map(&latest_point_date/1)
        |> Enum.reject(&is_nil/1)
        |> Enum.min(fn -> nil end)

      source_observed_at =
        series
        |> Enum.map(&latest_point_date/1)
        |> Enum.reject(&is_nil/1)
        |> Enum.max(fn -> nil end)

      provider = "stored_normalized_daily_bars"
      market_data_version = history_version(series, snapshot_ids)
      coherence_status = coherence_status(snapshot_ids)
      warnings = stored_history_warnings(coherence_status)

      %{
        status: "ok",
        provider: provider,
        source_note:
          "Stored normalized daily bars. Public requests read cached database rows only; they do not fetch provider data or spend provider quota.",
        cache: "miss",
        display_mode: "public",
        display_status: "stored_public_allowed",
        data_freshness:
          data_freshness(
            provider,
            series,
            source_observed_at,
            complete_through,
            end_date
          ),
        provider_budget_status: [],
        symbols: symbols,
        start: Date.to_iso8601(start_date),
        end: Date.to_iso8601(end_date),
        series: series,
        coverage: Enum.map(series, &coverage_for_series/1),
        source_policy_digest: source_policy_digest(chosen_rows),
        market_data_version: market_data_version,
        market_data_snapshot_id: single_or_nil(snapshot_ids),
        market_data_snapshot_ids: snapshot_ids,
        calculation_manifest: calculation_manifest(chosen_rows),
        coherence_status: coherence_status,
        quality_state: quality_state(chosen_rows),
        calculation_readiness:
          calculation_readiness(
            symbols,
            start_date,
            end_date,
            series,
            snapshot_ids,
            coherence_status
          ),
        warnings: warnings
      }
    end
  end

  defp stored_history_rows(symbols, start_date, end_date) do
    Sql.all(
      """
      select symbol, price_date, provider_key, close, adjusted_close, volume, currency_code,
             exchange, timezone, provider_price_timestamp, ingested_at, source_hash,
             source_revision, quality_state, market_data_snapshot_id, source_policy_json,
             quality_json
      from market_price_bar
      where symbol = any($1)
        and interval = '1day'
        and price_date between $2 and $3
        and quality_state = 'valid'
        and coalesce((source_policy_json->>'raw_public_allowed')::boolean, false) = true
      order by symbol, price_date, ingested_at desc
      """,
      [symbols, start_date, end_date]
    )
  end

  defp choose_rows(rows) do
    rows
    |> Enum.group_by(&{&1["symbol"], &1["price_date"]})
    |> Enum.map(fn {_key, duplicate_rows} ->
      Enum.sort(duplicate_rows, &history_row_precedes?/2)
      |> List.first()
    end)
    |> Enum.sort_by(&{&1["symbol"], &1["price_date"]})
  end

  defp provider_rank(provider_key),
    do: Enum.find_index(@provider_order, &(&1 == provider_key)) || 99

  defp history_row_precedes?(left, right) do
    left_rank = provider_rank(left["provider_key"])
    right_rank = provider_rank(right["provider_key"])
    left_ingested = to_string(left["ingested_at"] || "")
    right_ingested = to_string(right["ingested_at"] || "")
    left_hash = to_string(left["source_hash"] || "")
    right_hash = to_string(right["source_hash"] || "")
    left_revision = to_string(left["source_revision"] || "")
    right_revision = to_string(right["source_revision"] || "")

    cond do
      left_rank != right_rank -> left_rank < right_rank
      left_ingested != right_ingested -> left_ingested > right_ingested
      left_hash != right_hash -> left_hash < right_hash
      true -> left_revision < right_revision
    end
  end

  defp series_for_symbol(symbol, rows) do
    symbol_rows =
      rows
      |> Enum.filter(&(String.upcase(to_string(&1["symbol"])) == symbol))
      |> Enum.sort_by(& &1["price_date"])

    %{
      symbol: symbol,
      points: Enum.map(symbol_rows, &point_for_row/1),
      source: "stored_normalized_daily_bars",
      providers: symbol_rows |> Enum.map(& &1["provider_key"]) |> Enum.uniq() |> Enum.sort(),
      snapshot_ids:
        symbol_rows
        |> Enum.map(& &1["market_data_snapshot_id"])
        |> Enum.reject(&blank?/1)
        |> Enum.map(&to_string/1)
        |> Enum.uniq()
        |> Enum.sort()
    }
  end

  defp point_for_row(row) do
    %{
      date: to_string(row["price_date"]),
      close: to_float(row["close"]),
      adjusted_close: to_float(row["adjusted_close"]),
      volume: to_float(row["volume"]),
      currency: row["currency_code"] || "USD",
      exchange: row["exchange"],
      timezone: row["timezone"] || @us_market_timezone,
      provider_timestamp: row["provider_price_timestamp"],
      source_revision: row["source_revision"]
    }
    |> Enum.reject(fn {_key, value} -> is_nil(value) end)
    |> Map.new()
  end

  defp coverage_for_series(series) do
    points = Map.fetch!(series, :points)

    %{
      symbol: Map.fetch!(series, :symbol),
      point_count: length(points),
      first_date: points |> List.first(%{}) |> Map.get(:date),
      latest_date: points |> List.last(%{}) |> Map.get(:date),
      providers: Map.get(series, :providers, []),
      snapshot_ids: Map.get(series, :snapshot_ids, []),
      status: "stored",
      quality_state: "valid"
    }
  end

  defp data_freshness(provider, series, source_observed_at, complete_through, requested_end) do
    fetched_at = DateTime.utc_now() |> DateTime.to_iso8601()
    staleness_state = history_staleness_state(complete_through, requested_end)

    %{
      provider: provider,
      provider_timestamp: latest_market_session_date(series),
      fetched_at: fetched_at,
      source_observed_at: source_observed_at,
      market_session_date: latest_market_session_date(series),
      complete_through: complete_through,
      hard_expires_at: history_hard_expires_at(complete_through),
      staleness_state: staleness_state,
      calculation_eligible:
        staleness_state in ["active", "delayed"] and not is_nil(complete_through),
      delayed_by_seconds: history_delayed_by_seconds(complete_through, requested_end),
      exchange_timezone: @us_market_timezone,
      delay_label: if(complete_through, do: "daily close", else: "unavailable"),
      is_same_day_valid: false,
      is_public_display_allowed: true,
      staleness_reason:
        if(complete_through,
          do: "Daily candle history only; not same-day intraday data and not a realtime quote.",
          else: "Provider returned no market session date."
        ),
      license_mode: "public_display_allowed",
      source_url: nil
    }
  end

  defp calculation_readiness(
         symbols,
         start_date,
         end_date,
         series,
         snapshot_ids,
         coherence_status
       ) do
    missing_symbols =
      series
      |> Enum.filter(&(Map.get(&1, :points) == []))
      |> Enum.map(&Map.fetch!(&1, :symbol))

    reason =
      cond do
        coherence_status not in ["single_snapshot", "current_snapshots"] ->
          "market_history_#{coherence_status}"

        missing_symbols != [] ->
          "missing_market_history_symbols"

        true ->
          nil
      end

    %{
      ready: is_nil(reason),
      reason: reason,
      snapshot_id: single_or_nil(snapshot_ids),
      coherence_status: coherence_status,
      snapshot_ids: snapshot_ids,
      missing_symbols: missing_symbols,
      missing_sessions: %{},
      required_fx_pairs: [],
      fx_coverage_status: "not_required",
      symbols: symbols,
      start: Date.to_iso8601(start_date),
      end: Date.to_iso8601(end_date),
      base_currency: "USD"
    }
  end

  defp calculation_manifest(rows) do
    Enum.map(rows, fn row ->
      %{
        symbol: row["symbol"],
        date: to_string(row["price_date"]),
        provider: row["provider_key"],
        snapshot_id: row["market_data_snapshot_id"],
        candidate_id: nil,
        content_hash: row["source_hash"] || ""
      }
    end)
  end

  defp latest_market_session_date(series) do
    series
    |> Enum.map(&latest_point_date/1)
    |> Enum.reject(&is_nil/1)
    |> Enum.max(fn -> nil end)
  end

  defp latest_point_date(series) do
    series
    |> Map.get(:points, [])
    |> Enum.map(&Map.get(&1, :date))
    |> Enum.reject(&blank?/1)
    |> Enum.max(fn -> nil end)
  end

  defp history_hard_expires_at(nil), do: nil

  defp history_hard_expires_at(complete_through) do
    with {:ok, date} <- Date.from_iso8601(complete_through),
         {:ok, dt} <- DateTime.new(Date.add(date, 3), ~T[23:59:59], "Etc/UTC") do
      DateTime.to_iso8601(dt)
    else
      _ -> nil
    end
  end

  defp history_staleness_state(nil, _requested_end), do: "unavailable"

  defp history_staleness_state(complete_through, requested_end) do
    case Date.from_iso8601(complete_through) do
      {:ok, date} ->
        lag_days = max(0, Date.diff(requested_end, date))

        cond do
          lag_days == 0 -> "active"
          lag_days <= 3 -> "delayed"
          true -> "stale_fallback"
        end

      _ ->
        "unavailable"
    end
  end

  defp history_delayed_by_seconds(nil, _requested_end), do: nil

  defp history_delayed_by_seconds(complete_through, requested_end) do
    case Date.from_iso8601(complete_through) do
      {:ok, date} -> max(0, Date.diff(requested_end, date)) * 86_400
      _ -> nil
    end
  end

  defp source_policy_digest(rows) do
    rows
    |> Enum.map(&Jason.encode!(Map.get(&1, "source_policy_json") || %{}))
    |> Enum.sort()
    |> Enum.join("|")
    |> sha256()
  end

  defp history_version(series, snapshot_ids) do
    %{series: series, snapshot_ids: snapshot_ids}
    |> Jason.encode!()
    |> sha256()
    |> String.slice(0, 16)
  end

  defp sha256(value) do
    :crypto.hash(:sha256, value)
    |> Base.encode16(case: :lower)
  end

  defp coherence_status([]), do: "unversioned"
  defp coherence_status([_single]), do: "single_snapshot"
  defp coherence_status(_snapshot_ids), do: "mixed_snapshots"

  defp stored_history_warnings("mixed_snapshots"),
    do: [
      "Stored history spans multiple market data snapshots; downstream calculations should pin a single snapshot."
    ]

  defp stored_history_warnings("unversioned"),
    do: ["Stored history contains legacy rows without market_data_snapshot_id."]

  defp stored_history_warnings(_coherence_status), do: []

  defp quality_state(rows) do
    states =
      rows
      |> Enum.map(&(Map.get(&1, "quality_state") || "valid"))
      |> Enum.uniq()

    if states -- ["valid"] == [], do: "valid", else: "mixed"
  end

  defp single_or_nil([single]), do: single
  defp single_or_nil(_values), do: nil

  defp validate_window(start_date, end_date) do
    cond do
      Date.compare(start_date, end_date) == :gt ->
        {:error, "start date must be before end date"}

      Date.diff(end_date, start_date) > @max_history_days ->
        {:error, "date range exceeds #{@max_history_days} days"}

      true ->
        :ok
    end
  end

  defp validate_symbols(symbols) do
    raw_symbols = to_string(symbols)

    symbols =
      raw_symbols
      |> String.split(",", trim: true)
      |> Enum.map(&String.trim/1)
      |> Enum.map(&String.upcase/1)
      |> Enum.reject(&(&1 == ""))
      |> Enum.uniq()

    cond do
      String.length(raw_symbols) > @max_symbol_query_length ->
        {:error, "symbols query is too long"}

      symbols == [] ->
        {:error, "at least one symbol is required"}

      length(symbols) > @max_symbols ->
        {:error, "at most #{@max_symbols} symbols are allowed"}

      invalid = Enum.find(symbols, &(not Regex.match?(@symbol_regex, &1))) ->
        {:error, "unsupported symbol format: #{invalid}"}

      true ->
        {:ok, symbols}
    end
  end

  defp to_float(nil), do: nil
  defp to_float(value) when is_integer(value), do: value * 1.0
  defp to_float(value) when is_float(value), do: value

  defp to_float(value) do
    case Float.parse(to_string(value)) do
      {parsed, _rest} -> parsed
      :error -> nil
    end
  end

  defp blank?(nil), do: true
  defp blank?(""), do: true
  defp blank?(_value), do: false
end
