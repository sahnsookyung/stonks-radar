defmodule StonksBackend.ShortsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Shorts

  @sample_file """
  Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
  20260702|AAPL|1200|10|4000|Q
  20260702|RKLB|800|0|1000|Q
  20260702|ZZZZ|12|0|30|Q
  20260702|BROKEN|oops|0|100|Q
  File Creation Time: 202607022100
  """

  test "parses official FINRA daily short-sale volume rows for tracked symbols" do
    assert {:ok, parsed} =
             Shorts.parse_daily_short_volume(@sample_file,
               tracked_symbols: ["AAPL", "RKLB"],
               source_url: "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260702.txt"
             )

    assert parsed.total_rows == 3
    assert parsed.unknown_symbol_count == 1
    assert parsed.malformed_count == 1
    assert Enum.map(parsed.rows, & &1.symbol) == ["AAPL", "RKLB"]

    assert [aapl | _] = parsed.rows
    assert aapl.as_of_date == "2026-07-02"
    assert aapl.settlement_date == "2026-07-02"
    assert aapl.short_volume == 1200
    assert aapl.short_exempt_volume == 10
    assert aapl.total_volume == 4000
    assert aapl.short_volume_ratio == 0.3
    assert aapl.dataset == "finra_daily_short_sale_volume"
    assert aapl.provider_observation_key == "finra_daily_short_volume:2026-07-02:AAPL"
  end

  test "empty and malformed daily files become explicit empty parse results" do
    assert {:ok, parsed} = Shorts.parse_daily_short_volume("", tracked_symbols: ["AAPL"])
    assert parsed.rows == []
    assert parsed.total_rows == 0
    assert parsed.malformed_count == 0
    assert parsed.unknown_symbol_count == 0

    assert {:ok, parsed} =
             Shorts.parse_daily_short_volume("not a pipe row\nFile Creation Time: 202607022100",
               tracked_symbols: ["AAPL"],
               fallback_date: ~D[2026-07-02]
             )

    assert parsed.rows == []
    assert parsed.malformed_count == 1
  end

  test "daily file URLs and publication window use FINRA after-hours timing" do
    assert Shorts.daily_short_volume_url(~D[2026-07-02]) ==
             "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260702.txt"

    assert Shorts.finra_daily_publication_anchor(~D[2026-07-02]) ==
             ~U[2026-07-02 22:30:00Z]

    assert Shorts.default_trade_date(~U[2026-07-02 21:59:00Z]) == ~D[2026-07-01]
    assert Shorts.default_trade_date(~U[2026-07-02 22:31:00Z]) == ~D[2026-07-02]
    assert Shorts.default_trade_date(~U[2026-07-06 15:00:00Z]) == ~D[2026-07-03]
  end

  test "daily ingestion uses injectable fetches and reports official guardrails" do
    fetch_fun = fn url ->
      assert url == "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260702.txt"
      {:ok, %{"text" => @sample_file}}
    end

    assert {:ok, result} =
             Shorts.fetch_daily_short_volume(
               %{"date" => "2026-07-02"},
               fetch_fun: fetch_fun,
               tracked_symbols: ["AAPL", "RKLB"]
             )

    assert result.status == "ready"
    assert result.as_of_date == "2026-07-02"
    assert result.rows_seen == 3
    assert result.rows_parsed == 2
    assert result.unknown_symbol_count == 1
    assert result.malformed_count == 1

    assert result.short_interest_guardrail ==
             "daily_short_volume_is_transaction_flow_not_open_short_interest"
  end

  test "daily ingestion falls back across recent weekdays when the latest FINRA file is unavailable" do
    fetch_fun = fn
      "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260703.txt" ->
        {:error, {:http_status, 404}}

      "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260702.txt" ->
        {:ok, %{"text" => @sample_file}}
    end

    assert {:ok, result} =
             Shorts.fetch_daily_short_volume(
               %{"date" => "2026-07-03"},
               fetch_fun: fetch_fun,
               tracked_symbols: ["AAPL", "RKLB"],
               fallback_trade_days: 2
             )

    assert result.status == "ready"
    assert result.requested_as_of_date == "2026-07-03"
    assert result.as_of_date == "2026-07-02"
    assert Enum.map(result.attempts, & &1["as_of_date"]) == ["2026-07-03", "2026-07-02"]
    assert Enum.map(result.attempts, & &1["status"]) == ["failed", "ready"]
  end

  test "ingestion entrypoints honor the runtime kill switch" do
    fetch_fun = fn _url -> flunk("disabled shorts ingestion must not fetch FINRA files") end

    assert {:ok, daily} =
             Shorts.fetch_daily_short_volume(
               %{"date" => "2026-07-02"},
               enabled: false,
               fetch_fun: fetch_fun
             )

    assert daily.status == "disabled"
    assert daily.reason == "shorts_ingestion_enabled_false"

    assert {:ok, release} = Shorts.fetch_short_interest_release(%{}, enabled: false)
    assert release.status == "disabled"

    assert {:ok, metadata} = Shorts.refresh_short_research_metadata(%{}, enabled: false)
    assert metadata.status == "disabled"
  end

  test "snapshot enrichment replaces placeholder shorts lanes with honest coverage gaps" do
    data = %{
      "generated_label" => "2026-07-02T23:00:00Z",
      "alternative_signals" => [
        %{"key" => "highest_short_interest", "value" => "placeholder", "items" => []},
        %{"key" => "short_volume_monitor", "value" => "placeholder", "items" => []},
        %{"key" => "other_lane", "value" => "unchanged"}
      ]
    }

    enriched = Shorts.enrich_home_snapshot_data(data)
    lanes = Map.new(enriched["alternative_signals"], &{&1["key"], &1})

    assert lanes["short_volume_monitor"]["value"] == "coverage gap"
    assert lanes["short_volume_monitor"]["source"] == "FINRA daily short sale volume"

    assert lanes["short_volume_monitor"]["items"] |> hd() |> Map.get("detail") =~
             "not live intraday short interest"

    assert lanes["highest_short_interest"]["value"] == "twice monthly"

    assert lanes["highest_short_interest"]["items"] |> hd() |> Map.get("detail") =~
             "not a substitute for open short interest"

    assert lanes["other_lane"]["value"] == "unchanged"
  end
end
