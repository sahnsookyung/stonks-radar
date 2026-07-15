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

  @fractional_sample_file """
  Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
  20260714|AAPL|513401.055176|0|734668.693683|B,Q,N
  """

  @sample_short_interest_rows [
    %{
      "symbolCode" => "AAPL",
      "issueName" => "Apple Inc. Common Stock",
      "currentShortPositionQuantity" => 140_526_320,
      "previousShortPositionQuantity" => 144_248_476,
      "averageDailyVolumeQuantity" => 81_121_306,
      "daysToCoverQuantity" => 1.73,
      "changePercent" => -2.58,
      "changePreviousNumber" => -3_722_156,
      "settlementDate" => "2026-06-30",
      "marketClassCode" => "NNM",
      "issuerServicesGroupExchangeCode" => "R"
    },
    %{
      "symbolCode" => "OTHER",
      "currentShortPositionQuantity" => 100,
      "settlementDate" => "2026-06-30"
    },
    %{"symbolCode" => "BROKEN", "settlementDate" => "2026-06-30"}
  ]

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

  test "preserves fractional quantities from current official FINRA daily files" do
    assert {:ok, parsed} =
             Shorts.parse_daily_short_volume(@fractional_sample_file,
               tracked_symbols: ["AAPL"]
             )

    assert [aapl] = parsed.rows
    assert aapl.short_volume == 513_401.055176
    assert aapl.short_exempt_volume == 0
    assert aapl.total_volume == 734_668.693683
    assert aapl.short_volume_ratio == 0.6988
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

  test "parses official FINRA consolidated short-interest rows without changing their cadence" do
    parsed =
      Shorts.parse_short_interest_rows(
        @sample_short_interest_rows,
        ~D[2026-06-30],
        ["AAPL"]
      )

    assert parsed.total_rows == 3
    assert parsed.unknown_symbol_count == 1
    assert parsed.malformed_count == 1
    assert [aapl] = parsed.rows
    assert aapl.symbol == "AAPL"
    assert aapl.short_interest == 140_526_320
    assert aapl.previous_short_interest == 144_248_476
    assert aapl.change_percent == -2.58
    assert aapl.change_previous == -3_722_156
    assert aapl.days_to_cover == 1.73
    assert aapl.settlement_date == "2026-06-30"
    assert aapl.provider_observation_key == "finra_short_interest:2026-06-30:AAPL"
  end

  test "short-interest ingestion discovers the latest FINRA partition and fetches tracked symbols" do
    partition_fetch_fun = fn ->
      {:ok,
       %{
         "availablePartitions" => [
           %{"partitions" => ["2026-06-15"]},
           %{"partitions" => ["2026-06-30"]}
         ]
       }}
    end

    data_fetch_fun = fn settlement_date, symbols ->
      assert settlement_date == ~D[2026-06-30]
      assert symbols == ["AAPL"]
      {:ok, @sample_short_interest_rows}
    end

    assert {:ok, result} =
             Shorts.fetch_short_interest_release(%{},
               tracked_symbols: ["AAPL"],
               partition_fetch_fun: partition_fetch_fun,
               data_fetch_fun: data_fetch_fun
             )

    assert result.status == "ready"
    assert result.settlement_date == "2026-06-30"
    assert result.rows_seen == 3
    assert result.rows_parsed == 1
    assert result.unknown_symbol_count == 1
    assert result.malformed_count == 1
    assert result.cadence == "twice_monthly"
    refute result.realtime
  end

  test "short-interest ingestion honors an explicit settlement date and reports upstream failure" do
    partition_fetch_fun = fn -> flunk("explicit dates must not fetch FINRA partitions") end

    data_fetch_fun = fn settlement_date, _symbols ->
      assert settlement_date == ~D[2026-06-15]
      {:error, :finra_down}
    end

    assert {:error, :finra_down} =
             Shorts.fetch_short_interest_release(
               %{"settlement_date" => "2026-06-15"},
               tracked_symbols: ["AAPL"],
               partition_fetch_fun: partition_fetch_fun,
               data_fetch_fun: data_fetch_fun
             )
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

  test "snapshot enrichment leaves missing shorts observations visibly unavailable" do
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

    assert lanes["short_volume_monitor"]["value"] == "unavailable"
    assert lanes["short_volume_monitor"]["source"] == "FINRA daily short sale volume"
    assert lanes["short_volume_monitor"]["items"] == []

    assert lanes["highest_short_interest"]["value"] == "unavailable"
    assert lanes["highest_short_interest"]["freshness"] == "unsupported"
    assert lanes["highest_short_interest"]["items"] == []

    assert lanes["other_lane"]["value"] == "unchanged"
  end
end
