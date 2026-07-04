defmodule StonksBackend.YieldCurvesTest do
  use ExUnit.Case, async: true

  alias StonksBackend.YieldCurves

  test "enriches yield macro tiles with 24 monthly official observations" do
    request_fun = fn
      "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
      opts ->
        year = opts |> Keyword.fetch!(:params) |> Keyword.fetch!(:field_tdr_date_value)
        {:ok, %{status: 200, body: us_xml_for_year(year)}}

      "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
      _opts ->
        {:ok, %{status: 200, body: japan_csv()}}
    end

    data = %{
      "macro_tiles" => [
        base_tile("us_2y", "4.01"),
        base_tile("us_3y", "4.02"),
        base_tile("us_5y", "4.03"),
        base_tile("us_10y", "4.04"),
        base_tile("japan_2y", "1.01"),
        base_tile("japan_5y", "1.02"),
        base_tile("japan_10y", "1.03")
      ]
    }

    assert {:ok, enriched} =
             YieldCurves.enrich_home_snapshot_data(data,
               enabled: true,
               fetch: true,
               history_months: 24,
               request_fun: request_fun,
               today: ~D[2026-07-02],
               timeout: 1
             )

    us_10y = tile(enriched, "us_10y")
    japan_10y = tile(enriched, "japan_10y")

    assert us_10y["source"] == "U.S. Treasury XML feed"
    assert japan_10y["source"] == "Japan MOF JGB historical CSV"
    assert length(us_10y["points"]) == 24
    assert length(japan_10y["points"]) == 24
    assert List.last(us_10y["points"])["date"] == "2026-06-30"
    assert List.last(japan_10y["points"])["date"] == "2026-06-30"
    assert us_10y["updated_at"] == "2026-06-30T21:00:00Z"
    assert japan_10y["updated_at"] == "2026-06-30T21:00:00Z"
    assert us_10y["delay_label"] == "official daily data, monthly sampled through 2026-06-30"
    assert is_number(us_10y["refresh_delta"])
  end

  test "snapshot enrichment is cached-only by default and does not fetch official feeds" do
    request_fun = fn _url, _opts -> flunk("snapshot enrichment must not fetch external feeds") end
    data = %{"macro_tiles" => [base_tile("us_10y", "4.04")]}

    assert {:ok, enriched} =
             YieldCurves.enrich_home_snapshot_data(data,
               enabled: true,
               request_fun: request_fun,
               today: ~D[2026-07-02],
               timeout: 1
             )

    assert enriched == data
  end

  test "history refresh can dry-run the official observation collector" do
    request_fun = fn
      "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml",
      opts ->
        year = opts |> Keyword.fetch!(:params) |> Keyword.fetch!(:field_tdr_date_value)
        {:ok, %{status: 200, body: us_xml_for_year(year)}}

      "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
      _opts ->
        {:ok, %{status: 200, body: japan_csv()}}
    end

    assert {:ok, result} =
             YieldCurves.refresh_history(
               %{"dry_run" => true, "today" => "2026-07-02", "history_months" => 24},
               enabled: true,
               request_fun: request_fun,
               timeout: 1
             )

    assert result.status == "dry_run"
    assert result.would_persist == false
    assert result.history_months == 24
    assert result.countries == 2
    assert result.observations == 168
  end

  test "keeps existing tiles when an official feed fails" do
    request_fun = fn _url, _opts -> {:ok, %{status: 503, body: ""}} end
    data = %{"macro_tiles" => [base_tile("us_10y", "4.04")]}

    assert {:ok, enriched} =
             YieldCurves.enrich_home_snapshot_data(data,
               enabled: true,
               fetch: true,
               request_fun: request_fun,
               today: ~D[2026-07-02],
               timeout: 1
             )

    assert enriched == data
  end

  defp base_tile(key, value) do
    %{
      "key" => key,
      "label" => key,
      "value" => value,
      "unit" => "%",
      "source" => "seed",
      "freshness" => "watch",
      "delay_label" => "seed",
      "updated_at" => "2026-05-01T00:00:00Z"
    }
  end

  defp tile(data, key), do: Enum.find(data["macro_tiles"], &(&1["key"] == key))

  defp us_xml_for_year(year) do
    entries =
      monthly_dates()
      |> Enum.filter(&(&1.year == year))
      |> Enum.with_index()
      |> Enum.map(fn {date, index} ->
        value = 4.0 + index / 100

        """
        <entry>
          <content type="application/xml">
            <m:properties>
              <d:NEW_DATE m:type="Edm.DateTime">#{Date.to_iso8601(date)}T00:00:00</d:NEW_DATE>
              <d:BC_2YEAR m:type="Edm.Double">#{value}</d:BC_2YEAR>
              <d:BC_3YEAR m:type="Edm.Double">#{value + 0.05}</d:BC_3YEAR>
              <d:BC_5YEAR m:type="Edm.Double">#{value + 0.1}</d:BC_5YEAR>
              <d:BC_10YEAR m:type="Edm.Double">#{value + 0.2}</d:BC_10YEAR>
            </m:properties>
          </content>
        </entry>
        """
      end)
      |> Enum.join("\n")

    """
    <?xml version="1.0" encoding="utf-8" standalone="yes" ?>
    <feed xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns="http://www.w3.org/2005/Atom">
      #{entries}
    </feed>
    """
  end

  defp japan_csv do
    rows =
      monthly_dates()
      |> Enum.with_index()
      |> Enum.map(fn {date, index} ->
        value = 1.0 + index / 100

        [
          japan_date(date),
          value,
          value + 0.05,
          value + 0.08,
          value + 0.1,
          value + 0.2,
          value + 0.25,
          value + 0.3,
          value + 0.35,
          value + 0.4,
          value + 0.5,
          value + 0.55,
          value + 0.6,
          value + 0.65,
          value + 0.7,
          value + 0.75
        ]
        |> Enum.join(",")
      end)
      |> Enum.join("\n")

    """
    Interest Rate,,,,,,,,,,,,,,,(Unit : %)
    Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y
    #{rows}
    """
  end

  defp monthly_dates do
    for month_offset <- 0..25 do
      ~D[2024-05-01]
      |> Date.add(month_offset * 31)
      |> Date.end_of_month()
    end
    |> Enum.uniq()
  end

  defp japan_date(date), do: "#{date.year}/#{date.month}/#{date.day}"
end
