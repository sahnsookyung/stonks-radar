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
      Scheduler.snapshot_refresh_job_specs(now: ~U[2026-05-26 01:17:00Z], settings: settings())

    assert specs == [
             %{
               job_type: "snapshot_refresh",
               idempotency_key: "snapshot-refresh:1977509",
               payload: %{},
               job_group: "snapshots",
               priority: 60,
               provider_key: "snapshot_refresh"
             }
           ]
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
             "news.purge_email_raw"
           ]

    assert Enum.map(specs, & &1.provider_key) == [
             "company_ir",
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
            trump_disclosure_sec_poll_seconds: 0,
            trump_disclosure_oge_poll_seconds: 0,
            instrument_universe_refresh_seconds: 0
          ),
        enqueue_fun: enqueue
      )

    calls =
      for _ <- 1..6 do
        assert_receive {:enqueue, job_type, _payload, opts}
        {job_type, opts[:depends_on_job_id]}
      end

    assert length(ids) == 6

    assert calls |> Enum.map(&elem(&1, 0)) == [
             "news.read_pages",
             "news.normalize_document",
             "news.classify_entities",
             "news.cluster_events",
             "news.score_events",
             "news.purge_email_raw"
           ]

    assert calls |> Enum.map(&elem(&1, 1)) |> hd() == nil

    assert calls
           |> Enum.drop(1)
           |> Enum.all?(fn {_job_type, depends_on} -> is_binary(depends_on) end)
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
