defmodule StonksBackend.Disclosures.PublicProjectionTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Disclosures.PublicProjection

  test "replaces the static disclosure lane with stored filing rows" do
    data = %{
      "alternative_signals" => [
        %{
          "key" => "trump_filings",
          "value" => "unavailable",
          "summary" => "No data",
          "freshness" => "unsupported",
          "items" => []
        }
      ]
    }

    filings_fun = fn params ->
      assert params["ticker"] == "DJT"

      %{
        filings: [
          %{
            "id" => "filing-1",
            "ticker" => "DJT",
            "form_type" => "8-K",
            "issuer_name" => "Trump Media & Technology Group Corp.",
            "filed_at" => DateTime.utc_now(),
            "source_url" => "https://www.sec.gov/Archives/example"
          }
        ]
      }
    end

    enriched = PublicProjection.enrich_home(data, filings_fun: filings_fun)
    lane = hd(enriched["alternative_signals"])

    assert lane["value"] == "1 filings"
    assert [%{"label" => "DJT 8-K", "source" => "SEC EDGAR"}] = lane["items"]
  end

  test "leaves the lane unavailable when no stored filing exists" do
    data = %{
      "alternative_signals" => [
        %{"key" => "trump_filings", "value" => "unavailable", "items" => []}
      ]
    }

    assert PublicProjection.enrich_home(data, filings_fun: fn _ -> %{filings: []} end) == data
  end
end
