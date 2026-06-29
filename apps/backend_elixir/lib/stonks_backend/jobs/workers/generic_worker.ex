defmodule StonksBackend.Jobs.Workers.GenericWorker do
  @moduledoc "Initial Oban worker dispatch surface for migrated legacy job types."
  use Oban.Worker, max_attempts: 5

  alias StonksBackend.Jobs.RuntimeLock

  require Logger

  @impl Oban.Worker
  def perform(%Oban.Job{args: %{"job_type" => job_type, "payload" => payload} = args} = job) do
    Logger.info("oban_job_dispatch job_type=#{job_type} id=#{job.id}")

    owner = "oban:#{job.id}"
    scopes = RuntimeLock.scopes_from_args(args)

    case RuntimeLock.acquire_many(scopes, owner) do
      {:ok, acquired_scopes} ->
        try do
          dispatch(job_type, payload)
        after
          RuntimeLock.release_many(acquired_scopes, owner)
        end

      {:error, {:locked, scope}} ->
        Logger.info(
          "oban_job_runtime_lock_busy job_type=#{job_type} id=#{job.id} scope=#{scope["scope_type"]}:#{scope["scope_key"]}"
        )

        {:snooze, RuntimeLock.retry_in_seconds()}
    end
  end

  defp dispatch(job_type, payload) do
    case job_type do
      "snapshot_build" -> StonksBackend.Snapshots.build_candidate(payload)
      "snapshot_publish" -> StonksBackend.Snapshots.publish_from_payload(payload)
      "snapshot_refresh" -> StonksBackend.Snapshots.refresh(payload)
      "news.publish_snapshots" -> StonksBackend.Snapshots.refresh(payload)
      "instrument_search_index_update" -> StonksBackend.Instruments.refresh_index(payload)
      "market_data.refresh_history" -> StonksBackend.MarketData.refresh_history(payload)
      "trump_disclosures_ingest" -> StonksBackend.Sources.ingest_disclosures(payload)
      _ -> {:ok, %{status: "ignored_unknown_job_type", job_type: job_type}}
    end
  end
end
