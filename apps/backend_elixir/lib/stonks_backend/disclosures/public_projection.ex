defmodule StonksBackend.Disclosures.PublicProjection do
  @moduledoc "Projects stored disclosure records into public snapshot lanes."

  alias StonksBackend.Sources

  def enrich_home(data, opts \\ [])

  def enrich_home(data, opts) when is_map(data) do
    filings_fun = Keyword.get(opts, :filings_fun, &Sources.filings/1)

    rows =
      filings_fun.(%{"ticker" => "DJT", "source" => "SEC", "limit" => 20})
      |> Map.get(:filings, [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)

    update_in(data, ["alternative_signals"], fn lanes ->
      Enum.map(List.wrap(lanes), fn
        %{"key" => "trump_filings"} = lane -> disclosure_lane(lane, rows)
        lane -> lane
      end)
    end)
  rescue
    _ -> data
  end

  def enrich_home(data, _opts), do: data

  defp disclosure_lane(lane, []), do: lane

  defp disclosure_lane(lane, rows) do
    items = Enum.map(rows, &filing_item/1)
    newest = items |> List.first() |> Map.get("updated_at")

    lane
    |> Map.put("value", "#{length(items)} filings")
    |> Map.put(
      "summary",
      "Latest stored SEC filings for DJT. Verify every item at the linked filing."
    )
    |> Map.put("freshness", freshness(newest))
    |> Map.put("items", items)
  end

  defp filing_item(row) do
    form = to_string(row["form_type"] || "filing")
    ticker = to_string(row["ticker"] || "DJT") |> String.upcase()
    filed_at = iso8601(row["filed_at"] || row["doc_date"] || row["created_at"])
    date = String.slice(filed_at, 0, 10)

    %{
      "key" => "trump_filing_#{stable_identifier(row)}",
      "label" => "#{ticker} #{form}",
      "value" => if(date == "", do: "filing date unavailable", else: "filed #{date}"),
      "detail" =>
        "#{to_string(row["issuer_name"] || ticker)} #{form}; verify the filing at SEC EDGAR.",
      "source" => "SEC EDGAR",
      "source_url" => to_string(row["source_url"] || "https://www.sec.gov/edgar/search/"),
      "freshness" => freshness(filed_at),
      "severity" => "medium",
      "updated_at" => filed_at,
      "symbols" => [ticker]
    }
  end

  defp stable_identifier(row) do
    [row["accession_number"], row["id"], row["sha256"]]
    |> Enum.find_value(fn value ->
      value = to_string(value) |> String.trim()
      if value == "", do: nil, else: value
    end)
    |> to_string()
    |> String.replace(~r/[^A-Za-z0-9_.-]/, "_")
    |> String.slice(0, 100)
  end

  defp freshness(value) do
    with %DateTime{} = observed_at <- datetime(value) do
      age_days = DateTime.diff(DateTime.utc_now(), observed_at, :day)

      cond do
        age_days <= 2 -> "fresh"
        age_days <= 14 -> "watch"
        true -> "stale"
      end
    else
      _ -> "unsupported"
    end
  end

  defp datetime(%DateTime{} = value), do: value
  defp datetime(%NaiveDateTime{} = value), do: DateTime.from_naive!(value, "Etc/UTC")
  defp datetime(%Date{} = value), do: DateTime.new!(value, ~T[00:00:00], "Etc/UTC")

  defp datetime(value) when is_binary(value) do
    case DateTime.from_iso8601(value) do
      {:ok, parsed, _offset} ->
        parsed

      _ ->
        case Date.from_iso8601(value) do
          {:ok, date} -> DateTime.new!(date, ~T[00:00:00], "Etc/UTC")
          _ -> nil
        end
    end
  end

  defp datetime(_value), do: nil

  defp iso8601(%DateTime{} = value), do: DateTime.to_iso8601(value)

  defp iso8601(%NaiveDateTime{} = value),
    do: value |> DateTime.from_naive!("Etc/UTC") |> DateTime.to_iso8601()

  defp iso8601(%Date{} = value),
    do: value |> DateTime.new!(~T[00:00:00], "Etc/UTC") |> DateTime.to_iso8601()

  defp iso8601(value) when is_binary(value), do: value
  defp iso8601(_value), do: ""
end
