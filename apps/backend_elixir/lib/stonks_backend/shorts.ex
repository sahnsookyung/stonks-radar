defmodule StonksBackend.Shorts do
  @moduledoc "Official short-pressure ingestion and snapshot projection helpers."

  alias StonksBackend.{SafeFetch, Sql}

  @repo_root Path.expand("../../../..", __DIR__)
  @daily_short_volume_source "https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files"
  @short_interest_source "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest"
  @short_interest_guardrail_source "https://www.finra.org/investors/insights/short-interest"
  @nasdaq_short_interest_source "https://www.nasdaqtrader.com/Trader.aspx?id=ShortInterest"
  @short_research_sources [
    {"Muddy Waters", "https://www.muddywatersresearch.com/"},
    {"Viceroy Research", "https://viceroyresearch.org/"},
    {"Spruce Point", "https://www.sprucepointcap.com/"},
    {"Kerrisdale Capital", "https://www.kerrisdalecap.com/"},
    {"Culper Research", "https://culperresearch.com/"},
    {"Blue Orca Capital", "https://www.blueorcacapital.com/"},
    {"Grizzly Research", "https://grizzlyreports.com/"}
  ]

  def fetch_daily_short_volume(payload \\ %{}, opts \\ []) do
    now = Keyword.get(opts, :now, DateTime.utc_now())
    date = payload_date(payload) || default_trade_date(now)
    url = Map.get(payload, "url") || daily_short_volume_url(date)
    tracked_symbols = Keyword.get(opts, :tracked_symbols, tracked_symbols())
    fetch_fun = Keyword.get(opts, :fetch_fun, &safe_fetch_daily_file/1)

    case fetch_fun.(url) do
      {:ok, fetched} ->
        text = Map.get(fetched, "text", "")

        {:ok, parsed} =
          parse_daily_short_volume(text,
            source_url: url,
            tracked_symbols: tracked_symbols,
            fallback_date: date
          )

        persisted = persist_short_volume_rows(parsed.rows)

        record_source_health("finra_daily_short_volume", health_status(parsed.rows), %{
          as_of_date: Date.to_iso8601(date),
          fetched: parsed.total_rows,
          parsed: length(parsed.rows),
          malformed: parsed.malformed_count,
          unknown_symbol: parsed.unknown_symbol_count,
          persisted: persisted.persisted,
          persist_failed: persisted.failed
        })

        {:ok,
         %{
           status: if(parsed.rows == [], do: "coverage_gap", else: "ready"),
           source_key: "finra_daily_short_volume",
           source_url: url,
           as_of_date: Date.to_iso8601(date),
           rows_seen: parsed.total_rows,
           rows_parsed: length(parsed.rows),
           malformed_count: parsed.malformed_count,
           unknown_symbol_count: parsed.unknown_symbol_count,
           persisted_count: persisted.persisted,
           persist_failed_count: persisted.failed,
           short_interest_guardrail:
             "daily_short_volume_is_transaction_flow_not_open_short_interest"
         }}

      {:error, reason} ->
        record_source_health("finra_daily_short_volume", "failed", %{
          as_of_date: Date.to_iso8601(date),
          reason: inspect(reason)
        })

        {:error, reason}
    end
  end

  def fetch_short_interest_release(payload \\ %{}) do
    record_source_health("finra_short_interest", "degraded", %{
      requested_settlement_date: payload["settlement_date"],
      reason: "official_short_interest_is_delayed_twice_monthly",
      source_url: @short_interest_source
    })

    {:ok,
     %{
       status: "coverage_gap",
       source_key: "finra_short_interest",
       source_url: @short_interest_source,
       cadence: "twice_monthly",
       realtime: false
     }}
  end

  def refresh_short_research_metadata(_payload \\ %{}) do
    {:ok,
     %{
       status: "ready",
       source_key: "short_research_metadata",
       metadata_only: true,
       sources: Enum.map(@short_research_sources, fn {name, url} -> %{name: name, url: url} end)
     }}
  end

  def parse_daily_short_volume(text, opts \\ []) do
    tracked_symbols =
      opts
      |> Keyword.get(:tracked_symbols)
      |> normalize_tracked_symbols()

    source_url = Keyword.get(opts, :source_url, @daily_short_volume_source)
    fallback_date = Keyword.get(opts, :fallback_date)

    lines =
      text
      |> to_string()
      |> String.split(~r/\R/, trim: true)
      |> Enum.map(&String.trim/1)
      |> Enum.reject(&(&1 == ""))

    {header, data_lines} = header_and_data_lines(lines)

    {rows, malformed_count, unknown_symbol_count, total_rows} =
      Enum.reduce(data_lines, {[], 0, 0, 0}, fn line, {rows, malformed, unknown, total} ->
        case parse_daily_row(line, header, fallback_date, source_url) do
          {:ok, row} ->
            if tracked_symbols == :all or MapSet.member?(tracked_symbols, row.symbol) do
              {[row | rows], malformed, unknown, total + 1}
            else
              {rows, malformed, unknown + 1, total + 1}
            end

          :footer ->
            {rows, malformed, unknown, total}

          :malformed ->
            {rows, malformed + 1, unknown, total}
        end
      end)

    {:ok,
     %{
       rows: Enum.reverse(rows),
       malformed_count: malformed_count,
       unknown_symbol_count: unknown_symbol_count,
       total_rows: total_rows
     }}
  end

  def daily_short_volume_url(%Date{} = date) do
    "https://cdn.finra.org/equity/regsho/daily/CNMSshvol#{finra_date(date)}.txt"
  end

  def default_trade_date(now \\ DateTime.utc_now()) do
    local_date = eastern_local_date(now)
    anchor = finra_daily_publication_anchor(local_date)

    if DateTime.compare(now, anchor) in [:gt, :eq] and weekday?(local_date) do
      local_date
    else
      previous_weekday(local_date)
    end
  end

  def finra_daily_publication_anchor(%Date{} = date) do
    date
    |> NaiveDateTime.new!(~T[18:30:00])
    |> DateTime.from_naive!("Etc/UTC")
    |> DateTime.add(-eastern_utc_offset_hours(date) * 3_600, :second)
  end

  def enrich_home_snapshot_data(data) when is_map(data) do
    updated_at = Map.get(data, "generated_label") || DateTime.to_iso8601(DateTime.utc_now())
    short_volume_rows = latest_short_volume_rows()
    short_interest_rows = latest_short_interest_rows()

    lanes =
      data
      |> Map.get("alternative_signals", [])
      |> Enum.map(fn
        %{"key" => "short_volume_monitor"} = lane ->
          short_volume_lane(lane, short_volume_rows, updated_at)

        %{"key" => "highest_short_interest"} = lane ->
          short_interest_lane(lane, short_interest_rows, updated_at)

        lane ->
          lane
      end)

    Map.put(data, "alternative_signals", lanes)
  end

  def enrich_home_snapshot_data(data), do: data

  def tracked_symbols do
    tracked_entities_path()
    |> read_json_file()
    |> Map.get("entities", [])
    |> Enum.filter(&(Map.get(&1, "country") == "USA"))
    |> Enum.map(&Map.get(&1, "symbol"))
    |> Enum.map(&normalize_symbol/1)
    |> Enum.reject(&(&1 == "" or String.contains?(&1, ".")))
    |> Enum.uniq()
  end

  defp safe_fetch_daily_file(url) do
    SafeFetch.fetch_url(url,
      max_bytes: 3_000_000,
      text_max_chars: 3_000_000,
      timeout_seconds: 20
    )
  end

  defp payload_date(payload) do
    case Map.get(payload, "date") do
      nil -> nil
      value -> parse_date(value)
    end
  end

  defp header_and_data_lines([]), do: {%{}, []}

  defp header_and_data_lines([first | rest]) do
    if String.contains?(first, "|") and String.contains?(String.downcase(first), "symbol") do
      {header_index(first), rest}
    else
      {default_header(), [first | rest]}
    end
  end

  defp header_index(header_line) do
    header_line
    |> split_finra_row()
    |> Enum.with_index()
    |> Map.new(fn {header, index} -> {normalize_header(header), index} end)
  end

  defp default_header do
    %{
      "date" => 0,
      "symbol" => 1,
      "shortvolume" => 2,
      "shortexemptvolume" => 3,
      "totalvolume" => 4,
      "market" => 5
    }
  end

  defp parse_daily_row(line, header, fallback_date, source_url) do
    cond do
      footer_line?(line) ->
        :footer

      not String.contains?(line, "|") ->
        :malformed

      true ->
        values = split_finra_row(line)

        with {:ok, symbol} <- row_symbol(values, header),
             {:ok, date} <- row_date(values, header, fallback_date),
             {:ok, short_volume} <- row_int(values, header, "shortvolume"),
             {:ok, short_exempt_volume} <- row_int(values, header, "shortexemptvolume"),
             {:ok, total_volume} <- row_int(values, header, "totalvolume") do
          {:ok,
           %{
             symbol: symbol,
             as_of_date: Date.to_iso8601(date),
             settlement_date: Date.to_iso8601(date),
             short_volume: short_volume,
             short_exempt_volume: short_exempt_volume,
             total_volume: total_volume,
             short_volume_ratio: ratio(short_volume, total_volume),
             source: "FINRA daily short sale volume",
             source_url: source_url,
             dataset: "finra_daily_short_sale_volume",
             provider_observation_key:
               "finra_daily_short_volume:#{Date.to_iso8601(date)}:#{symbol}",
             retrieved_at: DateTime.utc_now() |> DateTime.to_iso8601(),
             market: row_value(values, header, "market")
           }}
        else
          _ -> :malformed
        end
    end
  end

  defp split_finra_row(line), do: line |> String.split("|") |> Enum.map(&String.trim/1)

  defp normalize_header(value) do
    value
    |> to_string()
    |> String.downcase()
    |> String.replace(~r/[^a-z0-9]/, "")
  end

  defp footer_line?(line) do
    downcased = String.downcase(line)

    String.starts_with?(downcased, "file creation time") or
      String.starts_with?(downcased, "end of")
  end

  defp row_symbol(values, header) do
    symbol = values |> row_value(header, "symbol") |> normalize_symbol()
    if symbol == "", do: :error, else: {:ok, symbol}
  end

  defp row_date(values, header, fallback_date) do
    case row_value(values, header, "date") |> parse_date() do
      %Date{} = date -> {:ok, date}
      nil -> fallback_date_result(fallback_date)
    end
  end

  defp fallback_date_result(%Date{} = date), do: {:ok, date}
  defp fallback_date_result(_date), do: :error

  defp row_int(values, header, key) do
    case row_value(values, header, key) |> parse_integer() do
      nil -> :error
      integer -> {:ok, integer}
    end
  end

  defp row_value(values, header, key) do
    case Map.get(header, key) do
      index when is_integer(index) -> Enum.at(values, index, "")
      _ -> ""
    end
  end

  defp parse_date(%Date{} = date), do: date

  defp parse_date(value) do
    value = value |> to_string() |> String.trim()

    cond do
      Regex.match?(~r/^\d{8}$/, value) ->
        with {year, ""} <- value |> String.slice(0, 4) |> Integer.parse(),
             {month, ""} <- value |> String.slice(4, 2) |> Integer.parse(),
             {day, ""} <- value |> String.slice(6, 2) |> Integer.parse(),
             {:ok, date} <- Date.new(year, month, day) do
          date
        else
          _ -> nil
        end

      true ->
        case Date.from_iso8601(value) do
          {:ok, date} -> date
          _ -> nil
        end
    end
  end

  defp parse_integer(nil), do: nil

  defp parse_integer(value) do
    value =
      value
      |> to_string()
      |> String.replace(",", "")
      |> String.trim()

    case Integer.parse(value) do
      {integer, ""} when integer >= 0 -> integer
      _ -> nil
    end
  end

  defp ratio(_numerator, 0), do: nil
  defp ratio(numerator, denominator), do: Float.round(numerator / denominator, 4)

  defp normalize_tracked_symbols(nil), do: :all

  defp normalize_tracked_symbols(symbols) when is_list(symbols) do
    symbols
    |> Enum.map(&normalize_symbol/1)
    |> Enum.reject(&(&1 == ""))
    |> MapSet.new()
  end

  defp normalize_tracked_symbols(_), do: :all

  defp normalize_symbol(nil), do: ""
  defp normalize_symbol(value), do: value |> to_string() |> String.trim() |> String.upcase()

  defp finra_date(date), do: date |> Date.to_iso8601(:basic)

  defp persist_short_volume_rows(rows) do
    Enum.reduce(rows, %{persisted: 0, failed: 0}, fn row, acc ->
      if persist_short_volume_row(row) do
        %{acc | persisted: acc.persisted + 1}
      else
        %{acc | failed: acc.failed + 1}
      end
    end)
  end

  defp persist_short_volume_row(row) do
    object_json = Jason.encode!(row)
    time_reference = Jason.encode!(%{"as_of_date" => row.as_of_date})

    Sql.execute(
      """
      insert into source_fact(
        fact_type, predicate, object_json, time_reference, confidence,
        extraction_source, review_status, public_allowed, dedupe_key
      )
      values (
        'short_volume', 'reports', cast($1 as jsonb), cast($2 as jsonb), 0.95,
        'rule', 'approved', true, $3
      )
      on conflict (dedupe_key) do update set
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

  defp record_source_health(source_key, status, details) do
    Sql.execute(
      """
      insert into source_health_status(source_key, status, last_checked_at, last_success_at, details)
      values ($1, $2, now(), case when $2 = 'ready' then now() else null end, cast($3 as jsonb))
      on conflict (source_key) do update set
        status = excluded.status,
        last_checked_at = excluded.last_checked_at,
        last_success_at = coalesce(excluded.last_success_at, source_health_status.last_success_at),
        details = excluded.details
      """,
      [source_key, status, Jason.encode!(details)]
    )

    :ok
  rescue
    _ -> :ok
  end

  defp health_status([]), do: "degraded"
  defp health_status(_rows), do: "ready"

  defp latest_short_volume_rows(limit \\ 50) do
    """
    select object_json
    from source_fact
    where fact_type = 'short_volume'
      and public_allowed = true
      and review_status in ('approved', 'owner_approved', 'editor_approved')
    order by object_json->>'as_of_date' desc,
             nullif(object_json->>'short_volume_ratio', '')::numeric desc nulls last
    limit $1
    """
    |> Sql.all([limit])
    |> Enum.map(& &1["object_json"])
    |> Enum.filter(&is_map/1)
  end

  defp latest_short_interest_rows(limit \\ 50) do
    """
    select object_json
    from source_fact
    where fact_type = 'short_interest'
      and public_allowed = true
      and review_status in ('approved', 'owner_approved', 'editor_approved')
    order by object_json->>'settlement_date' desc
    limit $1
    """
    |> Sql.all([limit])
    |> Enum.map(& &1["object_json"])
    |> Enum.filter(&is_map/1)
  end

  defp short_volume_lane(lane, [], updated_at) do
    lane
    |> Map.put("value", "coverage gap")
    |> Map.put("freshness", "unsupported")
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA daily short sale volume")
    |> Map.put("source_url", @daily_short_volume_source)
    |> Map.put(
      "summary",
      "No tracked-symbol FINRA daily short-sale volume rows are available in this snapshot."
    )
    |> Map.put("items", [
      %{
        "key" => "short_volume_monitor_coverage_gap",
        "label" => "Official daily short-volume rows unavailable",
        "value" => "coverage gap",
        "detail" =>
          "FINRA daily short-sale volume is same-day transaction flow after publication, not live intraday short interest.",
        "source" => "FINRA",
        "source_url" => @daily_short_volume_source,
        "freshness" => "unsupported",
        "severity" => "medium",
        "updated_at" => updated_at,
        "dataset" => "finra_daily_short_sale_volume"
      }
    ])
  end

  defp short_volume_lane(lane, rows, updated_at) do
    latest_date =
      rows
      |> Enum.map(& &1["as_of_date"])
      |> Enum.reject(&is_nil/1)
      |> case do
        [] -> nil
        dates -> Enum.max(dates)
      end

    lane
    |> Map.put("value", "#{length(rows)} official rows")
    |> Map.put("freshness", freshness_for_date(latest_date))
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA daily short sale volume")
    |> Map.put("source_url", @daily_short_volume_source)
    |> Map.put(
      "summary",
      "Official FINRA daily short-sale volume for tracked tickers. This is transaction flow, not open short interest."
    )
    |> Map.put("items", rows |> Enum.take(8) |> Enum.map(&short_volume_item(&1, updated_at)))
  end

  defp short_interest_lane(lane, [], updated_at) do
    lane
    |> Map.put("value", "twice monthly")
    |> Map.put("freshness", "watch")
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA consolidated short interest")
    |> Map.put("source_url", @short_interest_source)
    |> Map.put(
      "summary",
      "Official short interest is delayed twice-monthly open-position data; no tracked rows are available in this snapshot."
    )
    |> Map.put("items", [
      %{
        "key" => "highest_short_interest_release_lag",
        "label" => "Official short interest is delayed",
        "value" => "not realtime",
        "detail" =>
          "Use daily short-sale volume as same-day flow context only. It is not a substitute for open short interest.",
        "source" => "FINRA",
        "source_url" => @short_interest_guardrail_source,
        "freshness" => "watch",
        "severity" => "medium",
        "updated_at" => updated_at,
        "dataset" => "finra_short_interest"
      },
      %{
        "key" => "highest_short_interest_nasdaq_fallback",
        "label" => "Nasdaq Trader issue reference",
        "value" => "fallback",
        "detail" =>
          "Nasdaq Trader can be used as a twice-monthly listed-issue reference where available.",
        "source" => "Nasdaq Trader",
        "source_url" => @nasdaq_short_interest_source,
        "freshness" => "watch",
        "severity" => "medium",
        "updated_at" => updated_at,
        "dataset" => "nasdaq_short_interest"
      }
    ])
  end

  defp short_interest_lane(lane, rows, updated_at) do
    lane
    |> Map.put("value", "#{length(rows)} official rows")
    |> Map.put("freshness", "watch")
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA consolidated short interest")
    |> Map.put("source_url", @short_interest_source)
    |> Map.put("items", rows |> Enum.take(8) |> Enum.map(&short_interest_item(&1, updated_at)))
  end

  defp short_volume_item(row, updated_at) do
    symbol = to_string(row["symbol"] || row[:symbol])
    as_of_date = to_string(row["as_of_date"] || row[:as_of_date])
    short_volume = int_display(row["short_volume"] || row[:short_volume])
    total_volume = int_display(row["total_volume"] || row[:total_volume])

    %{
      "key" => to_string(row["provider_observation_key"] || row[:provider_observation_key]),
      "label" => "#{symbol} daily short-sale volume",
      "value" => percent_display(row["short_volume_ratio"] || row[:short_volume_ratio]),
      "detail" =>
        "#{short_volume} short-sale volume on #{total_volume} total reported volume for #{as_of_date}.",
      "source" => "FINRA",
      "source_url" => to_string(row["source_url"] || @daily_short_volume_source),
      "freshness" => freshness_for_date(as_of_date),
      "severity" => "medium",
      "updated_at" => updated_at,
      "symbols" => [symbol],
      "dataset" => "finra_daily_short_sale_volume",
      "as_of_date" => as_of_date,
      "provider_observation_key" => to_string(row["provider_observation_key"] || "")
    }
  end

  defp short_interest_item(row, updated_at) do
    symbol = to_string(row["symbol"] || row[:symbol])

    settlement_date =
      to_string(row["settlement_date"] || row["as_of_date"] || row[:settlement_date])

    %{
      "key" =>
        to_string(
          row["provider_observation_key"] || "finra_short_interest:#{settlement_date}:#{symbol}"
        ),
      "label" => "#{symbol} short interest",
      "value" => to_string(row["short_interest"] || row["value"] || "official row"),
      "detail" => "Official open short-interest row for settlement date #{settlement_date}.",
      "source" => "FINRA",
      "source_url" => to_string(row["source_url"] || @short_interest_source),
      "freshness" => freshness_for_date(settlement_date),
      "severity" => "medium",
      "updated_at" => updated_at,
      "symbols" => [symbol],
      "dataset" => "finra_short_interest",
      "as_of_date" => settlement_date,
      "provider_observation_key" => to_string(row["provider_observation_key"] || "")
    }
  end

  defp freshness_for_date(nil), do: "watch"
  defp freshness_for_date(""), do: "watch"

  defp freshness_for_date(date) do
    case Date.from_iso8601(to_string(date)) do
      {:ok, date} ->
        if Date.diff(Date.utc_today(), date) <= 5, do: "fresh", else: "watch"

      _ ->
        "watch"
    end
  end

  defp int_display(value) when is_integer(value), do: Integer.to_string(value)

  defp int_display(value) do
    value
    |> parse_integer()
    |> case do
      nil -> "n/a"
      integer -> Integer.to_string(integer)
    end
  end

  defp percent_display(nil), do: "n/a"

  defp percent_display(value) when is_float(value),
    do: "#{Float.round(value * 100, 1)}%"

  defp percent_display(value) do
    value
    |> to_string()
    |> Float.parse()
    |> case do
      {float, _} -> "#{Float.round(float * 100, 1)}%"
      _ -> "n/a"
    end
  end

  defp tracked_entities_path do
    candidates =
      [
        System.get_env("TRACKED_ENTITIES_PATH"),
        Path.join([@repo_root, "config", "tracked_entities.json"]),
        priv_news_source_path("tracked_entities.json")
      ]
      |> Enum.reject(&is_nil/1)

    Enum.find(candidates, &File.exists?/1) || List.first(candidates)
  end

  defp priv_news_source_path(file_name) do
    case :code.priv_dir(:stonks_backend) do
      {:error, _} -> nil
      path -> Path.join([to_string(path), "news_sources", file_name])
    end
  end

  defp read_json_file(nil), do: %{}

  defp read_json_file(path) do
    path
    |> File.read!()
    |> Jason.decode!()
  rescue
    _ -> %{}
  end

  defp eastern_local_date(now) do
    now
    |> DateTime.add(eastern_utc_offset_hours(DateTime.to_date(now)) * 3_600, :second)
    |> DateTime.to_date()
  end

  defp eastern_utc_offset_hours(date) do
    dst_start = nth_weekday(date.year, 3, 7, 2)
    dst_end = nth_weekday(date.year, 11, 7, 1)

    if Date.compare(date, dst_start) in [:gt, :eq] and Date.compare(date, dst_end) == :lt do
      -4
    else
      -5
    end
  end

  defp nth_weekday(year, month, weekday_1_to_7, n) do
    first = Date.new!(year, month, 1)
    offset = rem(weekday_1_to_7 - Date.day_of_week(first) + 7, 7)
    Date.add(first, offset + (n - 1) * 7)
  end

  defp previous_weekday(date) do
    date = Date.add(date, -1)
    if weekday?(date), do: date, else: previous_weekday(date)
  end

  defp weekday?(date), do: Date.day_of_week(date) in 1..5
end
