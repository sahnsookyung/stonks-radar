defmodule StonksBackend.EarningsCalendarTest do
  use ExUnit.Case, async: true

  alias StonksBackend.EarningsCalendar

  @alpha_csv """
  symbol,name,reportDate,fiscalDateEnding,estimate,currency
  AAPL,"Apple, Inc.",2099-08-01,2099-06-30,2.31,USD
  NVDA,NVIDIA Corporation,2099-08-20,2099-07-31,5.42,USD
  ZZZZ,Ignored Co,2099-08-22,2099-07-31,1.00,USD
  """

  test "parses Alpha Vantage earnings calendar CSV for watched symbols" do
    assert {:ok, parsed} =
             EarningsCalendar.parse_alpha_vantage_csv(@alpha_csv,
               symbols: ["AAPL", "NVDA"],
               now: ~U[2026-07-05 12:00:00Z]
             )

    assert parsed.total_rows == 3
    assert Enum.map(parsed.rows, & &1.symbol) == ["AAPL", "NVDA"]

    assert [aapl | _] = parsed.rows
    assert aapl.company_name == "Apple, Inc."
    assert aapl.earnings_date == "2099-08-01"
    assert aapl.eps_estimate == "2.31"
    assert aapl.provider_observation_key == "alpha_vantage_earnings_calendar:AAPL:2099-08-01"
  end

  test "Alpha Vantage JSON error payloads are not treated as empty CSV calendars" do
    assert {:error, {:provider_error, message}} =
             EarningsCalendar.parse_alpha_vantage_csv(~s({"Information":"rate limit"}))

    assert message == "rate limit"
  end

  test "provider rows replace manual watch calendar entries and keep fallback rows" do
    provider_rows = [
      %{
        "symbol" => "AAPL",
        "company_name" => "Apple, Inc.",
        "earnings_date" => "2099-08-01",
        "eps_estimate" => "2.31",
        "currency" => "USD",
        "source" => "Alpha Vantage",
        "source_url" => "https://www.alphavantage.co/documentation/#earnings-calendar"
      }
    ]

    data = %{
      "items" => [
        %{
          "id" => "cal_earnings_AAPL",
          "title" => "Apple earnings calendar",
          "country_region_key" => "USA",
          "release_type" => "earnings_watch",
          "scheduled_at" => nil,
          "scheduled_local_date" => "2026-07-01",
          "timezone" => "UTC",
          "time_precision" => "date_only",
          "status" => "monitoring",
          "expectation_type" => "manual_watch",
          "expectation_value" => "No provider date confirmed.",
          "actual_value" => nil,
          "previous_value" => nil,
          "surprise" => nil,
          "source" => "Apple IR",
          "source_url" => "https://investor.apple.com/",
          "freshness" => "watch"
        },
        %{
          "id" => "cal_us_cpi",
          "title" => "US CPI release",
          "country_region_key" => "USA",
          "release_type" => "macro_release",
          "scheduled_at" => "2099-07-14T12:00:00Z",
          "scheduled_local_date" => "2099-07-14",
          "timezone" => "America/New_York",
          "time_precision" => "date_only",
          "status" => "scheduled",
          "expectation_type" => "official_calendar",
          "expectation_value" => "BLS CPI release schedule",
          "actual_value" => nil,
          "previous_value" => nil,
          "surprise" => nil,
          "source" => "BLS",
          "source_url" => "https://www.bls.gov/schedule/news_release/cpi.htm",
          "freshness" => "fresh"
        }
      ],
      "central_banks" => [],
      "methodology" => "fixture"
    }

    enriched = EarningsCalendar.enrich_snapshot_data(data, provider_rows)
    apple = Enum.find(enriched["items"], &(&1["id"] == "cal_earnings_AAPL"))
    cpi = Enum.find(enriched["items"], &(&1["id"] == "cal_us_cpi"))

    assert apple["scheduled_local_date"] == "2099-08-01"
    assert apple["expectation_type"] == "provider_calendar"
    assert apple["source"] == "Alpha Vantage"
    assert apple["expectation_value"] =~ "EPS estimate 2.31 USD"
    assert cpi["expectation_type"] == "official_calendar"
  end
end
