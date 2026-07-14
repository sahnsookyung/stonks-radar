defmodule StonksBackend.TickerFundamentalsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.TickerFundamentals

  test "normalizes official CompanyFacts and leaves unsupported valuation data null" do
    payload = %{
      "facts" => %{
        "us-gaap" => %{
          "Revenues" => %{
            "units" => %{
              "USD" => [
                fact(100, "2025-12-31", "2026-02-01", "FY", "0001"),
                fact(80, "2024-12-31", "2025-02-01", "FY", "0000")
              ]
            }
          },
          "NetIncomeLoss" => %{
            "units" => %{"USD" => [fact(20, "2025-12-31", "2026-02-01", "FY", "0001")]}
          },
          "OperatingIncomeLoss" => %{
            "units" => %{"USD" => [fact(25, "2025-12-31", "2026-02-01", "FY", "0001")]}
          }
        }
      }
    }

    normalized =
      TickerFundamentals.normalize_company_facts(
        payload,
        "AAPL",
        "320193",
        ~U[2026-07-14 00:00:00Z]
      )

    assert normalized.status == "ready"
    assert normalized.metrics["revenue"] == 100
    assert_in_delta normalized.metrics["revenue_growth"], 0.25, 0.0001
    assert_in_delta normalized.metrics["operating_margin"], 0.25, 0.0001
    assert normalized.metrics["valuation_ratios"] == nil
    assert normalized.metrics["missing_reasons"]["cash"] == "concept_not_reported"
    assert normalized.filing_url =~ "sec.gov/Archives/edgar/data/320193"
  end

  test "returns precise unavailable coverage when no supported concepts exist" do
    normalized = TickerFundamentals.normalize_company_facts(%{"facts" => %{}}, "UNKNOWN", "1")
    assert normalized.status == "unavailable"
    assert normalized.coverage_reason == "no_supported_us_gaap_companyfacts"
    assert normalized.metrics["revenue"] == nil
  end

  defp fact(value, period_end, filed, fp, accession) do
    %{
      "val" => value,
      "end" => period_end,
      "filed" => filed,
      "form" => "10-K",
      "fp" => fp,
      "accn" => accession
    }
  end
end
