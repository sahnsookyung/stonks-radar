defmodule StonksBackend.Shorts do
  @moduledoc "Official short-pressure ingestion and snapshot projection helpers."

  alias StonksBackend.{SafeFetch, Settings, Sql, TrackedTickers}

  @daily_short_volume_source "https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files"
  @short_interest_source "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
  @short_interest_partitions_url "https://api.finra.org/partitions/group/otcmarket/name/consolidatedShortInterest"
  @short_interest_data_url "https://api.finra.org/data/group/otcmarket/name/consolidatedShortInterest"
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
    if shorts_ingestion_enabled?(opts) do
      do_fetch_daily_short_volume(payload, opts)
    else
      {:ok, disabled_result("finra_daily_short_volume")}
    end
  end

  defp do_fetch_daily_short_volume(payload, opts) do
    now = Keyword.get(opts, :now, DateTime.utc_now())
    date = payload_date(payload) || default_trade_date(now)
    tracked_symbols = Keyword.get(opts, :tracked_symbols, tracked_symbols())
    fetch_fun = Keyword.get(opts, :fetch_fun, &safe_fetch_daily_file/1)

    case fetch_daily_short_volume_file(payload, date, fetch_fun, opts) do
      {:ok, fetched, fetched_date, url, attempts} ->
        text = Map.get(fetched, "text", "")

        {:ok, parsed} =
          parse_daily_short_volume(text,
            source_url: url,
            tracked_symbols: tracked_symbols,
            fallback_date: fetched_date
          )

        rows = add_rollout_metadata(parsed.rows, fetched_date)
        persisted = persist_short_volume_rows(rows)

        record_source_health("finra_daily_short_volume", health_status(parsed.rows), %{
          requested_as_of_date: Date.to_iso8601(date),
          as_of_date: Date.to_iso8601(fetched_date),
          fetched: parsed.total_rows,
          parsed: length(parsed.rows),
          malformed: parsed.malformed_count,
          unknown_symbol: parsed.unknown_symbol_count,
          persisted: persisted.persisted,
          persist_failed: persisted.failed,
          attempts: attempts
        })

        {:ok,
         %{
           status: if(parsed.rows == [], do: "coverage_gap", else: "ready"),
           source_key: "finra_daily_short_volume",
           source_url: url,
           requested_as_of_date: Date.to_iso8601(date),
           as_of_date: Date.to_iso8601(fetched_date),
           rows_seen: parsed.total_rows,
           rows_parsed: length(rows),
           malformed_count: parsed.malformed_count,
           unknown_symbol_count: parsed.unknown_symbol_count,
           persisted_count: persisted.persisted,
           persist_failed_count: persisted.failed,
           attempts: attempts,
           short_interest_guardrail:
             "daily_short_volume_is_transaction_flow_not_open_short_interest"
         }}

      {:error, reason, attempts} ->
        record_source_health("finra_daily_short_volume", "failed", %{
          as_of_date: Date.to_iso8601(date),
          reason: inspect(reason),
          attempts: attempts
        })

        {:error, reason}
    end
  end

  defp fetch_daily_short_volume_file(payload, date, fetch_fun, opts) do
    payload
    |> daily_short_volume_attempts(date, opts)
    |> Enum.reduce_while({:error, :no_attempts, []}, fn {attempt_date, url},
                                                        {:error, _reason, errors} ->
      case fetch_fun.(url) do
        {:ok, fetched} ->
          attempt = %{
            "as_of_date" => Date.to_iso8601(attempt_date),
            "url" => url,
            "status" => "ready"
          }

          {:halt, {:ok, fetched, attempt_date, url, Enum.reverse([attempt | errors])}}

        {:error, reason} ->
          attempt = %{
            "as_of_date" => Date.to_iso8601(attempt_date),
            "url" => url,
            "status" => "failed",
            "reason" => inspect(reason)
          }

          {:cont, {:error, reason, [attempt | errors]}}
      end
    end)
    |> case do
      {:error, reason, attempts} -> {:error, reason, Enum.reverse(attempts)}
      other -> other
    end
  end

  defp daily_short_volume_attempts(%{"url" => url}, date, _opts)
       when is_binary(url) and url != "" do
    [{date, url}]
  end

  defp daily_short_volume_attempts(_payload, date, opts) do
    fallback_days =
      opts
      |> Keyword.get(:fallback_trade_days, Settings.get(:shorts_daily_fallback_trade_days, 5))
      |> normalize_int(5)
      |> max(1)
      |> min(10)

    date
    |> recent_weekdays(fallback_days)
    |> Enum.map(&{&1, daily_short_volume_url(&1)})
  end

  def fetch_short_interest_release(payload \\ %{}, opts \\ []) do
    if shorts_ingestion_enabled?(opts) do
      do_fetch_short_interest_release(payload, opts)
    else
      {:ok, disabled_result("finra_short_interest")}
    end
  end

  defp do_fetch_short_interest_release(payload, opts) do
    tracked_symbols = Keyword.get(opts, :tracked_symbols, tracked_symbols())

    partition_fetch_fun =
      Keyword.get(opts, :partition_fetch_fun, &fetch_short_interest_partitions/0)

    data_fetch_fun = Keyword.get(opts, :data_fetch_fun, &fetch_short_interest_rows/2)

    with {:ok, settlement_date} <- short_interest_settlement_date(payload, partition_fetch_fun),
         {:ok, response_rows} <- data_fetch_fun.(settlement_date, tracked_symbols) do
      parsed = parse_short_interest_rows(response_rows, settlement_date, tracked_symbols)
      rows = add_rollout_metadata(parsed.rows, settlement_date)
      persisted = persist_short_interest_rows(rows)

      record_source_health("finra_short_interest", health_status(rows), %{
        settlement_date: Date.to_iso8601(settlement_date),
        fetched: parsed.total_rows,
        parsed: length(rows),
        malformed: parsed.malformed_count,
        unknown_symbol: parsed.unknown_symbol_count,
        persisted: persisted.persisted,
        persist_failed: persisted.failed,
        source_url: @short_interest_source
      })

      {:ok,
       %{
         status: if(rows == [], do: "coverage_gap", else: "ready"),
         source_key: "finra_short_interest",
         source_url: @short_interest_source,
         settlement_date: Date.to_iso8601(settlement_date),
         rows_seen: parsed.total_rows,
         rows_parsed: length(rows),
         malformed_count: parsed.malformed_count,
         unknown_symbol_count: parsed.unknown_symbol_count,
         persisted_count: persisted.persisted,
         persist_failed_count: persisted.failed,
         cadence: "twice_monthly",
         realtime: false
       }}
    else
      {:error, reason} ->
        record_source_health("finra_short_interest", "failed", %{
          requested_settlement_date: payload["settlement_date"],
          reason: inspect(reason),
          source_url: @short_interest_source
        })

        {:error, reason}
    end
  end

  def parse_short_interest_rows(response_rows, settlement_date, tracked_symbols \\ nil)

  def parse_short_interest_rows(response_rows, %Date{} = settlement_date, tracked_symbols)
      when is_list(response_rows) do
    tracked_symbols = normalize_tracked_symbols(tracked_symbols)

    {rows, malformed_count, unknown_symbol_count} =
      Enum.reduce(response_rows, {[], 0, 0}, fn response_row, {rows, malformed, unknown} ->
        case parse_short_interest_row(response_row, settlement_date) do
          {:ok, row} ->
            if tracked_symbols == :all or MapSet.member?(tracked_symbols, row.symbol) do
              {[row | rows], malformed, unknown}
            else
              {rows, malformed, unknown + 1}
            end

          :malformed ->
            {rows, malformed + 1, unknown}
        end
      end)

    %{
      rows: Enum.reverse(rows),
      malformed_count: malformed_count,
      unknown_symbol_count: unknown_symbol_count,
      total_rows: length(response_rows)
    }
  end

  def parse_short_interest_rows(_response_rows, _settlement_date, _tracked_symbols) do
    %{rows: [], malformed_count: 1, unknown_symbol_count: 0, total_rows: 0}
  end

  def refresh_short_research_metadata(payload \\ %{}, opts \\ []) do
    if shorts_ingestion_enabled?(opts) do
      do_refresh_short_research_metadata(payload)
    else
      {:ok, disabled_result("short_research_metadata")}
    end
  end

  defp do_refresh_short_research_metadata(_payload) do
    {:ok,
     %{
       status: "ready",
       source_key: "short_research_metadata",
       metadata_only: true,
       sources: Enum.map(@short_research_sources, fn {name, url} -> %{name: name, url: url} end)
     }}
  end

  defp disabled_result(source_key) do
    %{
      status: "disabled",
      source_key: source_key,
      reason: "shorts_ingestion_enabled_false"
    }
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
    TrackedTickers.ticker_entities()
    |> Enum.filter(&(Map.get(&1, "country") == "USA"))
    |> Enum.map(&Map.get(&1, "symbol"))
    |> Enum.map(&normalize_symbol/1)
    |> Enum.reject(&(&1 == "" or String.contains?(&1, ".")))
    |> Enum.uniq()
  end

  defp shorts_ingestion_enabled?(opts) do
    Keyword.get_lazy(opts, :enabled, fn ->
      Settings.truthy?(Settings.get(:shorts_ingestion_enabled, "true"))
    end)
  end

  defp safe_fetch_daily_file(url) do
    SafeFetch.fetch_url(url,
      max_bytes: 3_000_000,
      text_max_chars: 3_000_000,
      timeout_seconds: 20
    )
  end

  defp fetch_short_interest_partitions do
    case Req.get(@short_interest_partitions_url,
           headers: [{"accept", "application/json"}],
           receive_timeout: 20_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 -> {:ok, body}
      {:ok, %{status: status}} -> {:error, {:finra_http_status, status}}
      {:error, reason} -> {:error, {:finra_unavailable, Exception.message(reason)}}
    end
  end

  defp fetch_short_interest_rows(_settlement_date, []), do: {:ok, []}

  defp fetch_short_interest_rows(%Date{} = settlement_date, tracked_symbols) do
    request_body = %{
      "compareFilters" => [
        %{
          "compareType" => "equal",
          "fieldName" => "settlementDate",
          "fieldValue" => Date.to_iso8601(settlement_date)
        }
      ],
      "domainFilters" => [
        %{"fieldName" => "symbolCode", "values" => Enum.map(tracked_symbols, &normalize_symbol/1)}
      ],
      "limit" => min(max(length(tracked_symbols) * 2, 100), 5_000)
    }

    case Req.post(@short_interest_data_url,
           headers: [{"accept", "application/json"}],
           json: request_body,
           receive_timeout: 20_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_list(body) ->
        {:ok, body}

      {:ok, %{status: status, body: body}} when status in 200..299 ->
        {:error, {:finra_invalid_response, body}}

      {:ok, %{status: status}} ->
        {:error, {:finra_http_status, status}}

      {:error, reason} ->
        {:error, {:finra_unavailable, Exception.message(reason)}}
    end
  end

  defp short_interest_settlement_date(%{"settlement_date" => value}, _partition_fetch_fun)
       when not is_nil(value) do
    case parse_date(value) do
      %Date{} = date -> {:ok, date}
      nil -> {:error, :invalid_settlement_date}
    end
  end

  defp short_interest_settlement_date(_payload, partition_fetch_fun) do
    with {:ok, response} <- partition_fetch_fun.(),
         partitions when is_list(partitions) <- Map.get(response, "availablePartitions"),
         dates when dates != [] <-
           Enum.map(partitions, &partition_date/1) |> Enum.reject(&is_nil/1) do
      {:ok, Enum.max(dates, Date)}
    else
      {:error, reason} -> {:error, reason}
      _ -> {:error, :finra_partitions_unavailable}
    end
  end

  defp partition_date(%{"partitions" => [value | _]}), do: parse_date(value)
  defp partition_date(_partition), do: nil

  defp parse_short_interest_row(row, fallback_date) when is_map(row) do
    symbol = normalize_symbol(row["symbolCode"])
    settlement_date = parse_date(row["settlementDate"]) || fallback_date
    short_interest = parse_integer(row["currentShortPositionQuantity"])

    if symbol == "" or is_nil(settlement_date) or is_nil(short_interest) do
      :malformed
    else
      {:ok,
       %{
         symbol: symbol,
         issue_name: present_string(row["issueName"]),
         settlement_date: Date.to_iso8601(settlement_date),
         as_of_date: Date.to_iso8601(settlement_date),
         short_interest: short_interest,
         previous_short_interest: parse_integer(row["previousShortPositionQuantity"]),
         change_percent: parse_number(row["changePercent"]),
         change_previous: parse_signed_integer(row["changePreviousNumber"]),
         average_daily_volume: parse_integer(row["averageDailyVolumeQuantity"]),
         days_to_cover: parse_number(row["daysToCoverQuantity"]),
         revision_flag: present_string(row["revisionFlag"]),
         market_class: present_string(row["marketClassCode"]),
         exchange_code: present_string(row["issuerServicesGroupExchangeCode"]),
         source: "FINRA consolidated short interest",
         source_url: @short_interest_source,
         dataset: "finra_short_interest",
         provider_observation_key:
           "finra_short_interest:#{Date.to_iso8601(settlement_date)}:#{symbol}",
         retrieved_at: DateTime.utc_now() |> DateTime.truncate(:second) |> DateTime.to_iso8601()
       }}
    end
  end

  defp parse_short_interest_row(_row, _fallback_date), do: :malformed

  defp add_rollout_metadata(rows, date) do
    ingestion_run_id = ingestion_run_id(date)
    release_id = release_id()

    Enum.map(rows, fn row ->
      row
      |> Map.put(:ingestion_run_id, ingestion_run_id)
      |> Map.put(:release_id, release_id)
      |> Map.put(:source_policy_version, 1)
    end)
  end

  defp ingestion_run_id(date) do
    timestamp = DateTime.utc_now() |> DateTime.truncate(:second) |> DateTime.to_iso8601()

    "ingestion:shorts:finra_daily_short_volume:#{Date.to_iso8601(date)}:#{timestamp}:#{System.unique_integer([:positive])}"
  end

  defp release_id do
    System.get_env("STONKS_RELEASE_ID") ||
      System.get_env("GITHUB_SHA") ||
      "local"
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
             {:ok, short_volume} <- row_nonnegative_number(values, header, "shortvolume"),
             {:ok, short_exempt_volume} <-
               row_nonnegative_number(values, header, "shortexemptvolume"),
             {:ok, total_volume} <- row_nonnegative_number(values, header, "totalvolume") do
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

  defp row_nonnegative_number(values, header, key) do
    case row_value(values, header, key) |> parse_nonnegative_number() do
      nil -> :error
      number -> {:ok, number}
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

  defp parse_nonnegative_number(nil), do: nil

  defp parse_nonnegative_number(value) do
    case parse_integer(value) do
      integer when is_integer(integer) ->
        integer

      nil ->
        case parse_number(value) do
          number when is_number(number) and number >= 0 -> number
          _ -> nil
        end
    end
  end

  defp parse_signed_integer(nil), do: nil

  defp parse_signed_integer(value) do
    value = value |> to_string() |> String.replace(",", "") |> String.trim()

    case Integer.parse(value) do
      {integer, ""} -> integer
      _ -> nil
    end
  end

  defp parse_number(nil), do: nil
  defp parse_number(value) when is_integer(value), do: value * 1.0
  defp parse_number(value) when is_float(value), do: value

  defp parse_number(value) do
    case value |> to_string() |> String.replace(",", "") |> String.trim() |> Float.parse() do
      {number, ""} -> number
      _ -> nil
    end
  end

  defp present_string(nil), do: nil

  defp present_string(value) do
    case value |> to_string() |> String.trim() do
      "" -> nil
      string -> string
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

  defp persist_short_interest_rows(rows) do
    Enum.reduce(rows, %{persisted: 0, failed: 0}, fn row, acc ->
      if persist_short_interest_row(row) do
        %{acc | persisted: acc.persisted + 1}
      else
        %{acc | failed: acc.failed + 1}
      end
    end)
  end

  defp persist_short_interest_row(row) do
    object_json = Jason.encode!(row)
    time_reference = Jason.encode!(%{"settlement_date" => row.settlement_date})

    Sql.execute(
      """
      insert into source_fact(
        fact_type, predicate, object_json, time_reference, confidence,
        extraction_source, review_status, public_allowed, dedupe_key
      )
      values (
        'short_interest', 'reports', $1::text::jsonb, $2::text::jsonb, 1.0,
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
        'short_volume', 'reports', $1::text::jsonb, $2::text::jsonb, 0.95,
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

  defp record_source_health(source_key, status, details) do
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

  defp short_volume_lane(lane, [], _updated_at) do
    lane
    |> Map.put("value", "unavailable")
    |> Map.put("freshness", "unsupported")
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA daily short sale volume")
    |> Map.put("source_url", @daily_short_volume_source)
    |> Map.put(
      "summary",
      "No tracked-symbol FINRA daily short-sale volume rows are available in this snapshot."
    )
    |> Map.put("items", [])
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

  defp short_interest_lane(lane, [], _updated_at) do
    lane
    |> Map.put("value", "unavailable")
    |> Map.put("freshness", "unsupported")
    |> Map.put("severity", "medium")
    |> Map.put("source", "FINRA consolidated short interest")
    |> Map.put("source_url", @short_interest_source)
    |> Map.put(
      "summary",
      "Official short interest is delayed twice-monthly open-position data; no tracked rows are available in this snapshot."
    )
    |> Map.put("items", [])
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
      "value" => int_display(row["short_interest"] || row["value"]),
      "detail" => short_interest_detail(row, settlement_date),
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

  defp short_interest_detail(row, settlement_date) do
    days_to_cover = row["days_to_cover"]
    change_percent = row["change_percent"]

    details =
      [
        "Official open short-interest position for settlement date #{settlement_date}",
        if(is_number(days_to_cover), do: "#{days_to_cover} days to cover"),
        if(is_number(change_percent), do: "#{change_percent}% versus the prior report")
      ]
      |> Enum.reject(&is_nil/1)

    Enum.join(details, "; ") <> "."
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

  defp int_display(value) when is_float(value) do
    value
    |> :erlang.float_to_binary(decimals: 3)
    |> String.trim_trailing("0")
    |> String.trim_trailing(".")
  end

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

  defp recent_weekdays(date, count), do: recent_weekdays(date, count, [])

  defp recent_weekdays(_date, 0, acc), do: Enum.reverse(acc)

  defp recent_weekdays(date, count, acc) do
    if weekday?(date) do
      recent_weekdays(Date.add(date, -1), count - 1, [date | acc])
    else
      recent_weekdays(Date.add(date, -1), count, acc)
    end
  end

  defp weekday?(date), do: Date.day_of_week(date) in 1..5

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp normalize_int(_value, default), do: default
end
