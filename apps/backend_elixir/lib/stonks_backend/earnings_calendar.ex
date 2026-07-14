defmodule StonksBackend.EarningsCalendar do
  @moduledoc "Provider-backed earnings calendar ingestion and snapshot projection helpers."

  alias StonksBackend.{SafeFetch, Settings, Sql, TrackedTickers}

  @alpha_vantage_source "https://www.alphavantage.co/documentation/#earnings-calendar"
  @alpha_vantage_query_url "https://www.alphavantage.co/query"

  def fetch_earnings_calendar(payload \\ %{}, opts \\ []) do
    if ingestion_enabled?(opts) do
      do_fetch_earnings_calendar(payload, opts)
    else
      {:ok, disabled_result()}
    end
  end

  def enrich_snapshot_data(data) when is_map(data) do
    enrich_snapshot_data(data, latest_provider_rows())
  end

  def enrich_snapshot_data(data), do: data

  def enrich_snapshot_data(data, provider_rows) when is_map(data) and is_list(provider_rows) do
    data
    |> update_calendar_items("items", provider_rows)
    |> update_calendar_items("central_banks", provider_rows)
  end

  def enrich_home_snapshot_data(data) when is_map(data) do
    enrich_home_snapshot_data(data, latest_provider_rows())
  end

  def enrich_home_snapshot_data(data), do: data

  def enrich_home_snapshot_data(data, provider_rows)
      when is_map(data) and is_list(provider_rows) do
    update_calendar_items(data, "calendar_preview", provider_rows)
  end

  def parse_alpha_vantage_csv(text, opts \\ []) do
    with :ok <- reject_provider_error_text(text) do
      do_parse_alpha_vantage_csv(text, opts)
    end
  end

  defp do_parse_alpha_vantage_csv(text, opts) do
    watched_symbols =
      opts
      |> Keyword.get(:symbols)
      |> normalize_symbol_set()

    now = Keyword.get(opts, :now, DateTime.utc_now())
    checked_at = DateTime.to_iso8601(now)
    csv_rows = parse_csv_rows(text)

    rows =
      csv_rows
      |> Enum.map(&alpha_vantage_row(&1, checked_at))
      |> Enum.filter(& &1)
      |> Enum.filter(fn row ->
        watched_symbols == :all or MapSet.member?(watched_symbols, row.symbol)
      end)

    {:ok, %{rows: rows, total_rows: length(csv_rows)}}
  end

  defp do_fetch_earnings_calendar(payload, opts) do
    now = Keyword.get(opts, :now, DateTime.utc_now())

    horizon =
      normalize_horizon(
        Map.get(payload, "horizon") || Settings.get(:earnings_calendar_horizon, "12month")
      )

    symbols = payload_symbols(payload)
    api_key = Keyword.get(opts, :api_key) || provider_api_key()
    fetch_fun = Keyword.get(opts, :fetch_fun, &SafeFetch.fetch_url/1)

    with {:ok, api_key} <- present_api_key(api_key),
         url <- alpha_vantage_url(api_key, horizon),
         {:ok, fetched} <- fetch_fun.(url),
         text <- Map.get(fetched, "text", ""),
         {:ok, parsed} <- parse_alpha_vantage_csv(text, symbols: symbols, now: now) do
      rows = add_rollout_metadata(parsed.rows, now)
      persisted = persist_provider_rows(rows)

      record_source_health("ready", %{
        horizon: horizon,
        rows_seen: parsed.total_rows,
        rows_parsed: length(rows),
        persisted: persisted.persisted,
        persist_failed: persisted.failed,
        source_url: @alpha_vantage_source
      })

      {:ok,
       %{
         status: if(rows == [], do: "coverage_gap", else: "ready"),
         source_key: "alpha_vantage_earnings_calendar",
         source_url: @alpha_vantage_source,
         horizon: horizon,
         rows_seen: parsed.total_rows,
         rows_parsed: length(rows),
         persisted_count: persisted.persisted,
         persist_failed_count: persisted.failed
       }}
    else
      {:error, :missing_api_key} ->
        record_source_health("degraded", %{
          reason: "missing_alpha_vantage_api_key",
          source_url: @alpha_vantage_source
        })

        {:ok,
         %{
           status: "coverage_gap",
           source_key: "alpha_vantage_earnings_calendar",
           reason: "missing_alpha_vantage_api_key",
           source_url: @alpha_vantage_source
         }}

      {:error, reason} ->
        record_source_health("failed", %{
          reason: inspect(reason),
          source_url: @alpha_vantage_source
        })

        {:error, reason}
    end
  end

  defp update_calendar_items(data, _key, []), do: data

  defp update_calendar_items(data, key, provider_rows) do
    rows_by_symbol =
      provider_rows
      |> Enum.group_by(&to_string(&1["symbol"]))
      |> Map.new(fn {symbol, rows} -> {symbol, preferred_provider_row(rows)} end)

    update_in(data, [key], fn items ->
      items
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(&merge_provider_calendar_item(&1, rows_by_symbol))
      |> append_missing_provider_items(rows_by_symbol)
      |> sort_calendar_items()
    end)
  end

  defp merge_provider_calendar_item(item, rows_by_symbol) do
    case Map.get(rows_by_symbol, calendar_item_symbol(item)) do
      nil -> item
      row -> provider_calendar_item(item, row)
    end
  end

  defp append_missing_provider_items(items, rows_by_symbol) do
    existing_symbols =
      items
      |> Enum.map(&calendar_item_symbol/1)
      |> Enum.reject(&(&1 == ""))
      |> MapSet.new()

    rows_by_symbol
    |> Enum.reject(fn {symbol, _row} -> MapSet.member?(existing_symbols, symbol) end)
    |> Enum.map(fn {_symbol, row} -> provider_calendar_item(%{}, row) end)
    |> Kernel.++(items)
  end

  defp provider_calendar_item(item, row) do
    company_name = row["company_name"] || row["symbol"]
    estimate = row["eps_estimate"]
    currency = row["currency"]

    item
    |> Map.put("id", item["id"] || "cal_earnings_#{row["symbol"]}")
    |> Map.put("title", item["title"] || "#{company_name} earnings calendar")
    |> Map.put(
      "country_region_key",
      item["country_region_key"] || country_region_key(row["symbol"])
    )
    |> Map.put("release_type", "earnings")
    |> Map.put("scheduled_at", nil)
    |> Map.put("scheduled_local_date", row["earnings_date"])
    |> Map.put("timezone", "UTC")
    |> Map.put("time_precision", "date_only")
    |> Map.put("status", "scheduled")
    |> Map.put("expectation_type", "provider_calendar")
    |> Map.put("expectation_value", provider_expectation_value(estimate, currency))
    |> Map.put("actual_value", item["actual_value"])
    |> Map.put("previous_value", item["previous_value"])
    |> Map.put("surprise", item["surprise"])
    |> Map.put("source", "Alpha Vantage")
    |> Map.put("source_url", row["source_url"] || @alpha_vantage_source)
    |> Map.put("freshness", "fresh")
  end

  defp provider_expectation_value(nil, _currency),
    do: "Provider earnings calendar date; confirm with company IR before trading-sensitive use."

  defp provider_expectation_value("", _currency), do: provider_expectation_value(nil, nil)

  defp provider_expectation_value(estimate, nil),
    do: "EPS estimate #{estimate}; confirm with company IR before trading-sensitive use."

  defp provider_expectation_value(estimate, ""), do: provider_expectation_value(estimate, nil)

  defp provider_expectation_value(estimate, currency),
    do:
      "EPS estimate #{estimate} #{currency}; confirm with company IR before trading-sensitive use."

  defp preferred_provider_row(rows) do
    rows
    |> Enum.sort_by(&{&1["earnings_date"] || "9999-12-31", &1["symbol"] || ""})
    |> List.first()
  end

  defp calendar_item_symbol(item) do
    id = to_string(item["id"] || "")

    cond do
      is_binary(item["symbol"]) ->
        normalize_symbol(item["symbol"])

      String.starts_with?(id, "cal_earnings_") ->
        id |> String.replace_prefix("cal_earnings_", "") |> normalize_symbol()

      true ->
        ""
    end
  end

  defp sort_calendar_items(items) do
    Enum.sort_by(items, fn item ->
      date = item["scheduled_local_date"] || "9999-12-31"

      time =
        if is_binary(item["scheduled_at"]) and String.contains?(item["scheduled_at"], "T"),
          do: String.slice(item["scheduled_at"], 11, 8),
          else: "23:59:59"

      {date, time, item["id"] || ""}
    end)
  end

  defp latest_provider_rows(limit \\ 250) do
    """
    select object_json
    from source_fact
    where fact_type = 'earnings_calendar'
      and public_allowed = true
      and review_status in ('approved', 'owner_approved', 'editor_approved')
      and object_json->>'source' = 'Alpha Vantage'
    order by object_json->>'earnings_date' asc, created_at desc
    limit $1
    """
    |> Sql.all([limit])
    |> Enum.map(& &1["object_json"])
    |> Enum.filter(&is_map/1)
    |> Enum.filter(&future_or_current_earnings?/1)
  rescue
    _ -> []
  end

  defp future_or_current_earnings?(row) do
    case Date.from_iso8601(to_string(row["earnings_date"] || "")) do
      {:ok, date} -> Date.compare(date, Date.utc_today()) in [:gt, :eq]
      _ -> false
    end
  end

  defp persist_provider_rows(rows) do
    Enum.reduce(rows, %{persisted: 0, failed: 0}, fn row, acc ->
      if persist_provider_row(row) do
        %{acc | persisted: acc.persisted + 1}
      else
        %{acc | failed: acc.failed + 1}
      end
    end)
  end

  defp persist_provider_row(row) do
    object_json = Jason.encode!(row)
    time_reference = Jason.encode!(%{"earnings_date" => row.earnings_date})

    Sql.execute(
      """
      insert into source_fact(
        fact_type, predicate, object_json, time_reference, confidence,
        extraction_source, review_status, public_allowed, dedupe_key
      )
      values (
        'earnings_calendar', 'reports', $1::text::jsonb, $2::text::jsonb, 0.85,
        'rule', 'approved', true, $3
      )
      on conflict (dedupe_key) where dedupe_key is not null do update set
        object_json = excluded.object_json,
        time_reference = excluded.time_reference,
        confidence = excluded.confidence,
        review_status = excluded.review_status,
        public_allowed = excluded.public_allowed
      """,
      [object_json, time_reference, row.provider_observation_key]
    )

    true
  rescue
    _ -> false
  end

  defp add_rollout_metadata(rows, now) do
    ingestion_run_id = ingestion_run_id(now)
    release_id = release_id()

    Enum.map(rows, fn row ->
      row
      |> Map.put(:ingestion_run_id, ingestion_run_id)
      |> Map.put(:release_id, release_id)
      |> Map.put(:source_policy_version, 1)
    end)
  end

  defp alpha_vantage_row(row, checked_at) do
    symbol = normalize_symbol(row["symbol"])
    earnings_date = normalize_date(row["reportdate"])

    if symbol == "" or is_nil(earnings_date) do
      nil
    else
      %{
        symbol: symbol,
        company_name: non_empty(row["name"]) || symbol,
        earnings_date: Date.to_iso8601(earnings_date),
        time_of_day: "unknown",
        fiscal_period: non_empty(row["fiscaldateending"]),
        eps_estimate: non_empty(row["estimate"]),
        revenue_estimate: nil,
        currency: non_empty(row["currency"]),
        source: "Alpha Vantage",
        source_url: @alpha_vantage_source,
        confirmed_status: "provider_calendar",
        last_checked_at: checked_at,
        dataset: "alpha_vantage_earnings_calendar",
        provider_observation_key:
          "alpha_vantage_earnings_calendar:#{symbol}:#{Date.to_iso8601(earnings_date)}"
      }
      |> drop_nil_values()
    end
  end

  defp parse_csv_rows(text) do
    case text |> to_string() |> String.split(~r/\R/, trim: true) do
      [] ->
        []

      [header | rows] ->
        headers = header |> csv_fields() |> Enum.map(&normalize_header/1)

        rows
        |> Enum.map(&csv_fields/1)
        |> Enum.filter(&(&1 != []))
        |> Enum.map(fn fields -> headers |> Enum.zip(fields) |> Map.new() end)
    end
  end

  defp reject_provider_error_text(text) do
    text = to_string(text) |> String.trim()

    if String.starts_with?(text, "{") do
      case Jason.decode(text) do
        {:ok, payload} when is_map(payload) ->
          message =
            payload["Note"] || payload["Information"] || payload["Error Message"] ||
              "Alpha Vantage returned JSON instead of CSV"

          {:error, {:provider_error, message}}

        _ ->
          {:error, :invalid_alpha_vantage_csv}
      end
    else
      :ok
    end
  end

  defp csv_fields(line), do: csv_fields(String.graphemes(line), "", [], false)
  defp csv_fields([], field, fields, _quoted), do: Enum.reverse([field | fields])
  defp csv_fields(["\"" | rest], field, fields, false), do: csv_fields(rest, field, fields, true)

  defp csv_fields(["\"", "\"" | rest], field, fields, true),
    do: csv_fields(rest, field <> "\"", fields, true)

  defp csv_fields(["\"" | rest], field, fields, true), do: csv_fields(rest, field, fields, false)

  defp csv_fields(["," | rest], field, fields, false),
    do: csv_fields(rest, "", [String.trim(field) | fields], false)

  defp csv_fields([char | rest], field, fields, quoted),
    do: csv_fields(rest, field <> char, fields, quoted)

  defp alpha_vantage_url(api_key, horizon) do
    query =
      URI.encode_query(%{
        "function" => "EARNINGS_CALENDAR",
        "horizon" => horizon,
        "apikey" => api_key
      })

    "#{@alpha_vantage_query_url}?#{query}"
  end

  defp payload_symbols(%{"symbols" => symbols}), do: normalize_symbol_list(symbols)
  defp payload_symbols(%{"symbol" => symbol}), do: normalize_symbol_list([symbol])
  defp payload_symbols(_payload), do: configured_symbols()

  defp configured_symbols do
    Settings.get(:earnings_calendar_symbols, "")
    |> Settings.split_csv()
    |> case do
      [] ->
        TrackedTickers.ticker_entities()
        |> Enum.map(&Map.get(&1, "symbol"))
        |> Enum.filter(&us_calendar_symbol?/1)

      symbols ->
        symbols
    end
    |> normalize_symbol_list()
  end

  defp us_calendar_symbol?(symbol) do
    symbol = to_string(symbol)
    symbol != "" and not String.contains?(symbol, ".")
  end

  defp normalize_symbol_list(symbols) when is_list(symbols) do
    symbols
    |> Enum.map(&normalize_symbol/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp normalize_symbol_list(symbols) when is_binary(symbols),
    do: Settings.split_csv(symbols) |> normalize_symbol_list()

  defp normalize_symbol_list(_symbols), do: []

  defp normalize_symbol_set([]), do: MapSet.new()
  defp normalize_symbol_set(nil), do: :all
  defp normalize_symbol_set(symbols), do: symbols |> normalize_symbol_list() |> MapSet.new()

  defp normalize_symbol(value), do: value |> to_string() |> String.trim() |> String.upcase()

  defp normalize_horizon(value) when value in ["3month", "6month", "12month"], do: value
  defp normalize_horizon(_value), do: "12month"

  defp normalize_header(value),
    do:
      value
      |> to_string()
      |> String.trim()
      |> String.downcase()
      |> String.replace(~r/[^a-z0-9]/, "")

  defp normalize_date(value) do
    case Date.from_iso8601(to_string(value || "")) do
      {:ok, date} -> date
      _ -> nil
    end
  end

  defp country_region_key(symbol) do
    if String.contains?(to_string(symbol), ".KS"), do: "KOR", else: "USA"
  end

  defp ingestion_enabled?(opts) do
    Keyword.get_lazy(opts, :enabled, fn ->
      Settings.truthy?(Settings.get(:earnings_calendar_ingestion_enabled, "true"))
    end)
  end

  defp provider_api_key do
    Settings.get(:earnings_calendar_api_key) ||
      Settings.get(:alpha_vantage_api_key) ||
      Settings.get(:market_data_api_key)
  end

  defp present_api_key(nil), do: {:error, :missing_api_key}

  defp present_api_key(value) do
    value = value |> to_string() |> String.trim()
    if value == "", do: {:error, :missing_api_key}, else: {:ok, value}
  end

  defp disabled_result do
    %{
      status: "disabled",
      source_key: "alpha_vantage_earnings_calendar",
      reason: "earnings_calendar_ingestion_enabled_false"
    }
  end

  defp record_source_health(status, details) do
    Sql.execute(
      """
      insert into source_health_status(source_key, status, last_checked_at, last_success_at, details)
      values ($1, $2, now(), case when $2 = 'ready' then now() else null end, $3::text::jsonb)
      on conflict (source_key) do update set
        status = excluded.status,
        last_checked_at = excluded.last_checked_at,
        last_success_at = coalesce(excluded.last_success_at, source_health_status.last_success_at),
        details = excluded.details
      """,
      ["alpha_vantage_earnings_calendar", status, Jason.encode!(details)]
    )

    :ok
  rescue
    _ -> :ok
  end

  defp ingestion_run_id(now) do
    timestamp = now |> DateTime.truncate(:second) |> DateTime.to_iso8601()
    "ingestion:calendar:alpha_vantage_earnings:#{timestamp}:#{System.unique_integer([:positive])}"
  end

  defp release_id do
    System.get_env("STONKS_RELEASE_ID") ||
      System.get_env("GITHUB_SHA") ||
      "local"
  end

  defp non_empty(value) do
    value = value |> to_string() |> String.trim()
    if value == "", do: nil, else: value
  end

  defp drop_nil_values(map), do: Map.reject(map, fn {_key, value} -> is_nil(value) end)
end
