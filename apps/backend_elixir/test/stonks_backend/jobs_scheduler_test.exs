defmodule StonksBackend.JobsSchedulerTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Jobs.Scheduler

  defp settings(overrides \\ []) do
    Keyword.merge(
      [
        worker_scheduler_enabled: true,
        trump_disclosure_sec_poll_seconds: 1_800,
        trump_disclosure_oge_poll_seconds: 86_400,
        trump_disclosure_oge_pdf_limit: 12,
        snapshot_refresh_seconds: 900,
        news_source_refresh_seconds: 900,
        news_publication_interval_seconds: 300,
        news_pipeline_runtime_enabled: true,
        news_max_documents_per_source_per_run: 100,
        news_processing_batch_limit: 500,
        news_page_read_batch_limit: 25,
        gdelt_doc_max_records: 250,
        gdelt_bulk_max_documents: 500,
        news_rss_enabled: true,
        news_gdelt_enabled: false,
        news_public_health_enabled: true,
        gdelt_bulk_runtime_enabled: false,
        yield_curve_history_enabled: true,
        yield_curve_history_months: 24,
        shorts_ingestion_enabled: true,
        earnings_calendar_ingestion_enabled: true,
        earnings_calendar_refresh_seconds: 86_400,
        earnings_calendar_horizon: "12month",
        market_data_scheduled_refresh_enabled: true,
        market_data_refresh_symbol_list: [],
        market_data_refresh_spread_minutes: 240,
        market_data_snapshot_window_days: 1_095,
        market_data_refresh_after_close_minutes: 45,
        instrument_universe_refresh_seconds: 14_400
      ],
      overrides
    )
  end

  test "snapshot refresh specs preserve the 15 minute idempotency window" do
    specs =
      Scheduler.snapshot_refresh_job_specs(
        now: ~U[2026-05-26 01:17:00Z],
        settings: settings(),
        snapshot_refresh_due_fun: fn _window_start -> true end
      )

    assert specs == [
             %{
               job_type: "snapshot_refresh",
               idempotency_key: "snapshot-refresh:1977509",
               payload: %{},
               job_group: "snapshots",
               priority: 60,
               unique_states: [:available, :scheduled, :executing, :completed]
             }
           ]
  end

  test "snapshot refresh specs skip a window that is already published" do
    assert Scheduler.snapshot_refresh_job_specs(
             now: ~U[2026-05-26 01:17:00Z],
             settings: settings(),
             snapshot_refresh_due_fun: fn window_start ->
               assert window_start == ~U[2026-05-26 01:15:00Z]
               false
             end
           ) == []
  end

  test "news fetch specs respect source toggles and keep GDELT disabled by default" do
    specs = Scheduler.news_fetch_job_specs(now: ~U[2026-05-26 01:17:00Z], settings: settings())
    keys = specs |> Enum.map(& &1.payload["source_key"]) |> MapSet.new()

    assert MapSet.subset?(MapSet.new(["federal_reserve", "who", "google_news_rss"]), keys)
    refute MapSet.member?(keys, "gdelt")
    refute MapSet.member?(keys, "gdelt_events")
    refute MapSet.member?(keys, "gdelt_gkg")
    assert Enum.all?(specs, &(&1.job_type == "news.fetch_source"))
    assert Enum.all?(specs, &(&1.job_group == "news"))
    assert Enum.all?(specs, &Map.has_key?(&1, :run_after))
  end

  test "news fetch specs can enable GDELT Doc API and disable RSS/public-health sources" do
    specs =
      Scheduler.news_fetch_job_specs(
        now: ~U[2026-05-26 01:17:00Z],
        settings:
          settings(
            news_rss_enabled: false,
            news_public_health_enabled: false,
            news_gdelt_enabled: true
          )
      )

    keys = specs |> Enum.map(& &1.payload["source_key"]) |> MapSet.new()

    refute MapSet.member?(keys, "google_news_rss")
    refute MapSet.member?(keys, "who")
    assert MapSet.member?(keys, "gdelt")
    refute MapSet.member?(keys, "gdelt_events")
    refute MapSet.member?(keys, "gdelt_gkg")
  end

  test "GDELT bulk sources require an explicit runtime gate" do
    specs =
      Scheduler.news_fetch_job_specs(
        now: ~U[2026-05-26 01:17:00Z],
        settings: settings(news_gdelt_enabled: true, gdelt_bulk_runtime_enabled: true)
      )

    keys = specs |> Enum.map(& &1.payload["source_key"]) |> MapSet.new()

    assert MapSet.subset?(MapSet.new(["gdelt", "gdelt_events", "gdelt_gkg"]), keys)
  end

  test "news fetch specs include generated watchlist sources" do
    specs =
      Scheduler.news_fetch_job_specs(
        now: ~U[2026-05-26 01:17:00Z],
        settings: settings()
      )

    by_key = Map.new(specs, &{&1.payload["source_key"], &1})

    assert by_key["sec_nvda_filings"].provider_key == "sec_edgar"
    assert by_key["google_news_NVDA"].provider_key == "google_news_rss"
    assert by_key["yahoo_finance_NVDA"].provider_key == "yahoo_finance_rss"
    assert by_key["google_news_NVDA"].payload["query"] =~ "NVIDIA Corporation"
  end

  test "source cadence and document caps match Python scheduler semantics" do
    profiles =
      Scheduler.enabled_news_sources(
        settings(news_gdelt_enabled: true, gdelt_bulk_runtime_enabled: true)
      )

    by_key = Map.new(profiles, &{&1.source_key, &1})

    assert Scheduler.source_poll_seconds(by_key["who"], settings()) == 3_600
    assert Scheduler.source_max_documents(by_key["who"], settings()) == 20
    assert Scheduler.source_max_documents(by_key["google_news_rss"], settings()) == 20

    assert Scheduler.source_max_documents(
             by_key["gdelt"],
             settings(news_max_documents_per_source_per_run: 1_000)
           ) == 250

    assert Scheduler.source_max_documents(
             by_key["gdelt_events"],
             settings(news_max_documents_per_source_per_run: 1_000)
           ) == 500
  end

  test "news pipeline scheduler can be disabled explicitly for rollback windows" do
    assert Scheduler.news_pipeline_job_specs(
             now: ~U[2026-05-26 01:17:00Z],
             settings: settings(news_pipeline_runtime_enabled: false)
           ) ==
             []
  end

  test "news pipeline scheduler creates local processing specs in order" do
    specs = Scheduler.news_pipeline_job_specs(now: ~U[2026-05-26 01:17:00Z], settings: settings())

    assert Enum.map(specs, & &1.job_type) == [
             "news.read_pages",
             "news.normalize_document",
             "news.classify_entities",
             "news.cluster_events",
             "news.score_events",
             "news.purge_email_raw",
             "news.prune_metadata"
           ]

    assert Enum.map(specs, & &1.provider_key) == [
             "company_ir",
             "local",
             "local",
             "local",
             "local",
             "local",
             "local"
           ]
  end

  test "schedule_due_jobs chains local news processing with returned Oban ids" do
    parent = self()

    enqueue = fn job_type, payload, opts ->
      send(parent, {:enqueue, job_type, payload, opts})
      {:ok, "oban:#{System.unique_integer([:positive])}"}
    end

    ids =
      Scheduler.schedule_due_jobs(
        now: ~U[2026-05-26 01:17:00Z],
        settings:
          settings(
            snapshot_refresh_seconds: 0,
            news_source_refresh_seconds: 0,
            news_pipeline_runtime_enabled: true,
            shorts_ingestion_enabled: false,
            earnings_calendar_ingestion_enabled: false,
            yield_curve_history_enabled: false,
            trump_disclosure_sec_poll_seconds: 0,
            trump_disclosure_oge_poll_seconds: 0,
            instrument_universe_refresh_seconds: 0,
            ticker_fundamentals_refresh_seconds: 0
          ),
        enqueue_fun: enqueue
      )

    calls =
      for _ <- 1..7 do
        assert_receive {:enqueue, job_type, _payload, opts}
        {job_type, opts[:depends_on_job_id]}
      end

    assert length(ids) == 7

    assert calls |> Enum.map(&elem(&1, 0)) == [
             "news.read_pages",
             "news.normalize_document",
             "news.classify_entities",
             "news.cluster_events",
             "news.score_events",
             "news.purge_email_raw",
             "news.prune_metadata"
           ]

    assert calls |> Enum.map(&elem(&1, 1)) |> hd() == nil

    assert calls
           |> Enum.drop(1)
           |> Enum.all?(fn {_job_type, depends_on} -> is_binary(depends_on) end)
  end

  test "shorts specs schedule FINRA daily files after the official publication window" do
    specs =
      Scheduler.shorts_job_specs(now: ~U[2026-07-02 21:59:00Z], settings: settings())

    by_type = Map.new(specs, &{&1.job_type, &1})

    daily = by_type["shorts.finra_daily_short_volume"]
    assert daily.idempotency_key == "shorts:finra-daily-short-volume:2026-07-01"
    assert daily.payload == %{"date" => "2026-07-01"}
    assert daily.job_group == "shorts"
    assert daily.provider_key == "finra"
    assert daily.run_after == ~U[2026-07-01 22:30:00Z]

    short_interest = by_type["shorts.finra_short_interest_release"]
    assert short_interest.job_group == "shorts"
    assert short_interest.provider_key == "finra"
    assert short_interest.run_after == ~U[2026-07-02 22:04:00Z]

    metadata = by_type["shorts.short_research_metadata"]
    assert metadata.job_group == "shorts"
    assert metadata.provider_key == "public_web"
    assert metadata.run_after == ~U[2026-07-02 22:09:00Z]
  end

  test "earnings calendar specs schedule Alpha Vantage provider refreshes" do
    specs =
      Scheduler.earnings_calendar_job_specs(
        now: ~U[2026-07-05 12:00:00Z],
        settings:
          settings(
            earnings_calendar_refresh_seconds: 86_400,
            earnings_calendar_horizon: "12month"
          )
      )

    assert [
             %{
               job_type: "calendar.alpha_vantage_earnings",
               idempotency_key: "calendar:alpha-vantage-earnings:12month:20639",
               payload: %{"horizon" => "12month"},
               job_group: "market_data",
               priority: 62,
               provider_key: "alpha_vantage",
               run_after: %DateTime{}
             }
           ] = specs
  end

  test "market history specs stagger rolling refreshes after US close" do
    specs =
      Scheduler.market_history_job_specs(
        now: ~U[2026-05-26 14:17:00Z],
        settings:
          settings(
            market_data_refresh_symbol_list: ["AAPL", "MSFT"],
            market_data_refresh_after_close_minutes: 45,
            market_data_refresh_spread_minutes: 240,
            market_data_snapshot_window_days: 1_095
          )
      )

    assert Enum.map(specs, & &1.job_type) == [
             "market_data.refresh_history",
             "market_data.refresh_history"
           ]

    assert specs |> Enum.map(& &1.payload["symbol"]) |> MapSet.new() ==
             MapSet.new(["AAPL", "MSFT"])

    assert Enum.all?(specs, &(&1.payload["mode"] == "rolling_3y_snapshot"))
    assert Enum.all?(specs, &(&1.payload["market_session_date"] == "2026-05-26"))
    assert Enum.all?(specs, &(&1.payload["start"] == "2023-05-27"))
    assert Enum.all?(specs, &(&1.payload["end"] == "2026-05-26"))
    assert Enum.all?(specs, &(&1.run_after >= ~U[2026-05-26 20:45:00Z]))
    assert Enum.all?(specs, &(&1.run_after < ~U[2026-05-27 00:45:00Z]))
  end

  test "market history uses early-close anchor" do
    [spec] =
      Scheduler.market_history_job_specs(
        now: ~U[2026-11-27 15:00:00Z],
        settings:
          settings(
            market_data_refresh_symbol_list: ["AAPL"],
            market_data_refresh_after_close_minutes: 45,
            market_data_refresh_spread_minutes: 15
          )
      )

    assert spec.payload["market_session_date"] == "2026-11-27"
    assert spec.run_after >= ~U[2026-11-27 18:45:00Z]
    assert spec.run_after < ~U[2026-11-27 19:00:00Z]
  end

  test "yield curve history specs schedule cached-observation refreshes once per day" do
    [spec] =
      Scheduler.yield_curve_history_job_specs(
        now: ~U[2026-07-02 12:00:00Z],
        settings: settings(yield_curve_history_enabled: true, yield_curve_history_months: 24)
      )

    assert spec.job_type == "yield_curves.refresh_history"
    assert spec.idempotency_key == "yield-curves:history:20636"
    assert spec.payload == %{"history_months" => 24}
    assert spec.job_group == "market_data"
    assert spec.provider_key == "yield_curves"

    assert Scheduler.yield_curve_history_job_specs(
             now: ~U[2026-07-02 12:00:00Z],
             settings: settings(yield_curve_history_enabled: false)
           ) == []
  end

  test "instrument search index specs use the configured Elixir Oban queue" do
    [spec] =
      Scheduler.instrument_search_index_job_specs(
        now: ~U[2026-05-26 01:17:00Z],
        settings: settings()
      )

    assert spec.job_type == "instrument_search_index_update"
    assert spec.idempotency_key == "instrument-universe:123594"
    assert spec.payload == %{"source" => "CONFIGURED_FREE_SOURCES", "mode" => "FULL"}
    assert spec.job_group == "instruments"
    assert spec.provider_key == "instrument_universe"
    assert spec.run_after |> DateTime.to_date() == ~D[2026-05-26]
  end

  test "disclosure specs keep SEC and OGE cadence keys" do
    specs =
      Scheduler.trump_disclosure_job_specs(now: ~U[2026-05-26 01:17:00Z], settings: settings())

    assert Enum.map(specs, & &1.provider_key) == ["sec_edgar", "oge_disclosures"]
    assert Enum.at(specs, 0).payload == %{"include_sec" => true, "include_oge" => false}
    assert Enum.at(specs, 1).payload == %{"include_sec" => false, "include_oge" => true}
    assert Enum.at(specs, 0).idempotency_key =~ "trump-disclosures:sec:"
    assert Enum.at(specs, 1).idempotency_key =~ "trump-disclosures:oge:"
  end
end
