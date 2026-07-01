defmodule StonksBackend.JobsSchedulerRunnerTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Jobs.SchedulerRunner

  defp settings(overrides \\ []) do
    Keyword.merge(
      [
        worker_scheduler_enabled: true,
        worker_scheduler_tick_seconds: 10,
        trump_disclosure_sec_poll_seconds: 0,
        trump_disclosure_oge_poll_seconds: 0,
        snapshot_refresh_seconds: 900,
        news_source_refresh_seconds: 0,
        news_publication_interval_seconds: 0,
        market_data_scheduled_refresh_enabled: false,
        market_data_refresh_symbol_list: [],
        instrument_universe_refresh_seconds: 0
      ],
      overrides
    )
  end

  test "run_once delegates due recurring specs to the configured enqueue function" do
    parent = self()

    enqueue = fn job_type, payload, opts ->
      send(parent, {:enqueue, job_type, payload, opts})
      {:ok, "oban:42"}
    end

    assert ["oban:42"] =
             SchedulerRunner.run_once(
               now: ~U[2026-05-26 01:17:00Z],
               settings: settings(),
               enqueue_fun: enqueue
             )

    assert_receive {:enqueue, "snapshot_refresh", %{}, opts}
    assert opts[:queue] == "snapshots"
    assert opts[:provider_key] == "snapshot_refresh"
    assert opts[:idempotency_key] == "snapshot-refresh:1977509"
  end

  test "supervised runner performs an initial tick without requiring the Python worker loop" do
    parent = self()

    enqueue = fn job_type, _payload, opts ->
      send(parent, {:tick_enqueue, job_type, opts[:idempotency_key]})
      {:ok, "oban:#{System.unique_integer([:positive])}"}
    end

    {:ok, pid} =
      SchedulerRunner.start_link(
        name: nil,
        initial_delay_ms: 0,
        now_fun: fn -> ~U[2026-05-26 01:17:00Z] end,
        settings: settings(worker_scheduler_tick_seconds: 1),
        enqueue_fun: enqueue
      )

    assert_receive {:tick_enqueue, "snapshot_refresh", "snapshot-refresh:1977509"}, 500
    GenServer.stop(pid)
  end

  test "disabled runner starts quietly and does not enqueue jobs" do
    parent = self()

    enqueue = fn job_type, _payload, _opts ->
      send(parent, {:unexpected_enqueue, job_type})
      {:ok, "oban:1"}
    end

    {:ok, pid} =
      SchedulerRunner.start_link(
        name: nil,
        initial_delay_ms: 0,
        now_fun: fn -> ~U[2026-05-26 01:17:00Z] end,
        settings: settings(worker_scheduler_enabled: false),
        enqueue_fun: enqueue
      )

    refute_receive {:unexpected_enqueue, _job_type}, 100
    GenServer.stop(pid)
  end
end
