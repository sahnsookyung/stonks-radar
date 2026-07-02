NimbleCSV.define(StonksBackend.YieldCurves.CSV, separator: ",", escape: "\"")

defmodule StonksBackend.YieldCurves do
  @moduledoc "Official yield-curve collection for public snapshot macro tiles."

  import SweetXml, only: [xpath: 2, sigil_x: 2]

  require Logger

  alias StonksBackend.Settings

  @default_history_months 24
  @default_timeout 15_000
  @us_xml_url "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
  @us_source_url "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"
  @japan_csv_url "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
  @japan_source_url "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"

  @terms [
    %{
      key: "us_2y",
      label: "US Treasury 2Y",
      source: "U.S. Treasury XML feed",
      source_url: @us_source_url,
      property: "BC_2YEAR"
    },
    %{
      key: "us_3y",
      label: "US Treasury 3Y",
      source: "U.S. Treasury XML feed",
      source_url: @us_source_url,
      property: "BC_3YEAR"
    },
    %{
      key: "us_5y",
      label: "US Treasury 5Y",
      source: "U.S. Treasury XML feed",
      source_url: @us_source_url,
      property: "BC_5YEAR"
    },
    %{
      key: "us_10y",
      label: "US Treasury 10Y",
      source: "U.S. Treasury XML feed",
      source_url: @us_source_url,
      property: "BC_10YEAR"
    },
    %{
      key: "japan_2y",
      label: "Japan govt 2Y",
      source: "Japan MOF JGB historical CSV",
      source_url: @japan_source_url,
      csv_index: 2
    },
    %{
      key: "japan_5y",
      label: "Japan govt 5Y",
      source: "Japan MOF JGB historical CSV",
      source_url: @japan_source_url,
      csv_index: 5
    },
    %{
      key: "japan_10y",
      label: "Japan govt 10Y",
      source: "Japan MOF JGB historical CSV",
      source_url: @japan_source_url,
      csv_index: 10
    }
  ]

  @doc """
  Replaces yield curve macro-tile points with monthly samples from official daily
  feeds. Existing tiles are preserved when an upstream feed is unavailable.
  """
  def enrich_home_snapshot_data(data, opts \\ [])

  def enrich_home_snapshot_data(data, opts) when is_map(data) do
    if enabled?(opts) do
      today = Keyword.get(opts, :today, Date.utc_today())
      history_months = history_months(opts)

      histories =
        []
        |> maybe_merge_histories(fetch_us_rows(today, opts), today, history_months)
        |> maybe_merge_histories(fetch_japan_rows(opts), today, history_months)

      {:ok, merge_macro_tiles(data, histories, today)}
    else
      {:ok, data}
    end
  rescue
    error ->
      Logger.warning("Yield curve enrichment failed: #{Exception.message(error)}")
      {:ok, data}
  end

  def enrich_home_snapshot_data(data, _opts), do: {:ok, data}

  defp enabled?(opts) do
    Keyword.get_lazy(opts, :enabled, fn ->
      Settings.truthy?(Settings.get(:yield_curve_history_enabled, "true"))
    end)
  end

  defp history_months(opts) do
    opts
    |> Keyword.get_lazy(:history_months, fn ->
      Settings.get(:yield_curve_history_months, "#{@default_history_months}")
    end)
    |> parse_positive_int(@default_history_months)
  end

  defp request_fun(opts), do: Keyword.get(opts, :request_fun, &Req.get/2)

  defp timeout(opts) do
    opts
    |> Keyword.get_lazy(:timeout, fn ->
      Settings.get(:yield_curve_fetch_timeout_seconds, "#{div(@default_timeout, 1000)}")
    end)
    |> parse_positive_int(div(@default_timeout, 1000))
    |> Kernel.*(1000)
  end

  defp fetch_us_rows(today, opts) do
    years =
      today
      |> years_for_history(history_months(opts))
      |> Enum.to_list()

    Enum.reduce_while(years, {:ok, []}, fn year, {:ok, rows} ->
      case fetch_us_year(year, opts) do
        {:ok, year_rows} -> {:cont, {:ok, rows ++ year_rows}}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp fetch_us_year(year, opts) do
    options = [
      params: [data: "daily_treasury_yield_curve", field_tdr_date_value: year],
      receive_timeout: timeout(opts),
      retry: false
    ]

    case request_fun(opts).(@us_xml_url, options) do
      {:ok, %{status: status, body: body}} when status in 200..299 ->
        {:ok, parse_us_xml(body)}

      {:ok, %{status: status}} ->
        {:error, "U.S. Treasury yield feed returned HTTP #{status}"}

      {:error, reason} ->
        {:error, "U.S. Treasury yield feed failed: #{inspect(reason)}"}
    end
  end

  defp fetch_japan_rows(opts) do
    options = [receive_timeout: timeout(opts), retry: false]

    case request_fun(opts).(@japan_csv_url, options) do
      {:ok, %{status: status, body: body}} when status in 200..299 ->
        {:ok, parse_japan_csv(body)}

      {:ok, %{status: status}} ->
        {:error, "Japan MOF yield CSV returned HTTP #{status}"}

      {:error, reason} ->
        {:error, "Japan MOF yield CSV failed: #{inspect(reason)}"}
    end
  end

  defp maybe_merge_histories(histories, {:ok, rows}, today, history_months) do
    histories ++ rows_to_histories(rows, today, history_months)
  end

  defp maybe_merge_histories(histories, {:error, reason}, _today, _history_months) do
    Logger.warning("Skipping yield curve feed during snapshot enrichment: #{reason}")
    histories
  end

  defp parse_us_xml(body) when is_binary(body) do
    body
    |> SweetXml.parse()
    |> xpath(~x"//*[local-name()='entry']"l)
    |> Enum.map(&us_entry_to_row/1)
    |> Enum.reject(&is_nil/1)
  end

  defp us_entry_to_row(entry) do
    with {:ok, date} <- parse_iso_datetime_date(xml_text(entry, "NEW_DATE")) do
      values =
        @terms
        |> Enum.filter(&Map.has_key?(&1, :property))
        |> Map.new(fn term -> {term.key, parse_float(xml_text(entry, term.property))} end)
        |> reject_nil_values()

      if map_size(values) == 0, do: nil, else: %{date: date, values: values}
    else
      :error -> nil
    end
  end

  defp xml_text(entry, local_name) do
    xpath(entry, ~x".//*[local-name()='#{local_name}']/text()"s)
  end

  defp parse_japan_csv(body) when is_binary(body) do
    body
    |> StonksBackend.YieldCurves.CSV.parse_string(skip_headers: false)
    |> Enum.map(&japan_csv_row_to_observation/1)
    |> Enum.reject(&is_nil/1)
  end

  defp japan_csv_row_to_observation([date_value | columns]) do
    with {:ok, date} <- parse_japan_date(date_value) do
      values =
        @terms
        |> Enum.filter(&Map.has_key?(&1, :csv_index))
        |> Map.new(fn term ->
          {term.key, columns |> Enum.at(term.csv_index - 1) |> parse_float()}
        end)
        |> reject_nil_values()

      if map_size(values) == 0, do: nil, else: %{date: date, values: values}
    else
      :error -> nil
    end
  end

  defp japan_csv_row_to_observation(_), do: nil

  defp rows_to_histories(rows, today, history_months) do
    cutoff = Date.add(today, -40 * (history_months + 2))
    rows = Enum.filter(rows, &(Date.compare(&1.date, cutoff) != :lt))

    @terms
    |> Enum.map(fn term ->
      points =
        rows
        |> Enum.filter(&Map.has_key?(&1.values, term.key))
        |> latest_observation_per_month()
        |> Enum.take(-history_months)
        |> Enum.map(fn row ->
          %{"date" => Date.to_iso8601(row.date), "value" => Float.round(row.values[term.key], 3)}
        end)

      {term.key, %{term: term, points: points}}
    end)
    |> Enum.reject(fn {_key, %{points: points}} -> points == [] end)
  end

  defp latest_observation_per_month(rows) do
    rows
    |> Enum.group_by(&month_key(&1.date))
    |> Enum.map(fn {_month, month_rows} ->
      Enum.max_by(month_rows, &Date.to_gregorian_days(&1.date))
    end)
    |> Enum.sort_by(&Date.to_gregorian_days(&1.date))
  end

  defp merge_macro_tiles(data, histories, today) do
    histories = Map.new(histories)
    macro_tiles = Map.get(data, "macro_tiles", [])
    existing_by_key = Map.new(macro_tiles, &{&1["key"], &1})
    existing_keys = Enum.map(macro_tiles, & &1["key"])
    yield_keys = Enum.map(@terms, & &1.key)
    ordered_keys = Enum.uniq(existing_keys ++ yield_keys)

    tiles =
      ordered_keys
      |> Enum.map(fn key ->
        case Map.fetch(histories, key) do
          {:ok, history} ->
            upsert_yield_tile(Map.get(existing_by_key, key, %{}), history, today)

          :error ->
            Map.get(existing_by_key, key)
        end
      end)
      |> Enum.reject(&is_nil/1)

    Map.put(data, "macro_tiles", tiles)
  end

  defp upsert_yield_tile(tile, %{term: term, points: points}, today) do
    latest = List.last(points)
    previous = Enum.at(points, -2)
    latest_date = latest["date"]
    value = latest["value"]

    tile
    |> Map.drop(["refresh_delta", "refresh_delta_percent"])
    |> Map.merge(%{
      "key" => term.key,
      "label" => Map.get(tile, "label", term.label),
      "value" => format_rate(value),
      "unit" => "%",
      "source" => term.source,
      "source_url" => term.source_url,
      "freshness" => freshness(latest_date, today),
      "delay_label" => "official daily data, monthly sampled through #{latest_date}",
      "updated_at" => "#{latest_date}T21:00:00Z",
      "refresh_seconds" => 86_400,
      "points" => points
    })
    |> maybe_put_delta(value, previous)
  end

  defp maybe_put_delta(tile, _value, nil), do: tile

  defp maybe_put_delta(tile, value, previous) do
    delta = Float.round(value - previous["value"], 4)
    Map.put(tile, "refresh_delta", delta)
  end

  defp freshness(date, today) do
    case Date.from_iso8601(date) do
      {:ok, parsed} ->
        age = Date.diff(today, parsed)

        cond do
          age <= 7 -> "fresh"
          age <= 35 -> "watch"
          true -> "stale"
        end

      {:error, _reason} ->
        "watch"
    end
  end

  defp years_for_history(today, history_months) do
    earliest = Date.add(today, -40 * (history_months + 2))
    earliest.year..today.year
  end

  defp month_key(date), do: "#{date.year}-#{pad2(date.month)}"

  defp parse_iso_datetime_date(value) when is_binary(value) do
    value
    |> String.slice(0, 10)
    |> Date.from_iso8601()
  end

  defp parse_iso_datetime_date(_), do: :error

  defp parse_japan_date(value) when is_binary(value) do
    with [year, month, day] <- String.split(value, "/", trim: true),
         {year, ""} <- Integer.parse(year),
         {month, ""} <- Integer.parse(month),
         {day, ""} <- Integer.parse(day) do
      Date.new(year, month, day)
    else
      _ -> :error
    end
  end

  defp parse_japan_date(_), do: :error

  defp parse_float(value) when is_binary(value) do
    value = String.trim(value)

    if value in ["", "-"] do
      nil
    else
      case Float.parse(value) do
        {number, ""} -> number
        {number, _suffix} -> number
        :error -> nil
      end
    end
  end

  defp parse_float(value) when is_number(value), do: value * 1.0
  defp parse_float(_), do: nil

  defp reject_nil_values(values) do
    values
    |> Enum.reject(fn {_key, value} -> is_nil(value) end)
    |> Map.new()
  end

  defp parse_positive_int(value, _default) when is_integer(value) and value > 0, do: value

  defp parse_positive_int(value, default) when is_binary(value) do
    case Integer.parse(value) do
      {parsed, ""} when parsed > 0 -> parsed
      _ -> default
    end
  end

  defp parse_positive_int(_value, default), do: default

  defp format_rate(value) do
    value
    |> :erlang.float_to_binary(decimals: 3)
    |> String.trim_trailing("0")
    |> String.trim_trailing(".")
  end

  defp pad2(value) when value < 10, do: "0#{value}"
  defp pad2(value), do: "#{value}"
end
