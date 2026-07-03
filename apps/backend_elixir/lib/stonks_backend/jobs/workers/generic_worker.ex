defmodule StonksBackend.Jobs.Workers.GenericWorker do
  @moduledoc "Oban worker dispatch surface for migrated backend job components."
  use Oban.Worker, max_attempts: 5

  alias StonksBackend.{Instruments, MarketData, News, Shorts, Snapshots, Sources}
  alias StonksBackend.Jobs.RuntimeLock

  require Logger

  @impl Oban.Worker
  def perform(%Oban.Job{args: %{"job_type" => job_type} = args} = job) do
    payload = normalize_payload(Map.get(args, "payload"))
    Logger.info("oban_job_dispatch job_type=#{job_type} id=#{job.id}")

    owner = "oban:#{job.id}"
    scopes = RuntimeLock.scopes_from_args(args)

    case RuntimeLock.acquire_many(scopes, owner) do
      {:ok, acquired_scopes} ->
        try do
          job_type
          |> dispatch(payload)
          |> normalize_result(job_type)
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

  def perform(%Oban.Job{args: args}) do
    {:discard, "missing job_type in Oban args: #{inspect(args)}"}
  end

  defp dispatch(job_type, payload) do
    case job_type do
      "snapshot_build" -> Snapshots.build_candidate(payload)
      "snapshot_publish" -> Snapshots.publish_from_payload(payload)
      "snapshot_refresh" -> Snapshots.refresh(payload)
      "news.publish_snapshots" -> Snapshots.refresh(payload)
      "instrument_search_index_update" -> Instruments.refresh_index(payload)
      "market_data.refresh_history" -> MarketData.refresh_history(payload)
      "trump_disclosures_ingest" -> Sources.ingest_disclosures(payload)
      "shorts.finra_daily_short_volume" -> Shorts.fetch_daily_short_volume(payload)
      "shorts.finra_short_interest_release" -> Shorts.fetch_short_interest_release(payload)
      "shorts.short_research_metadata" -> Shorts.refresh_short_research_metadata(payload)
      "news.fetch_source" -> News.fetch_source(payload)
      "news.read_pages" -> News.read_pages(payload)
      "news.purge_email_raw" -> News.purge_email_raw(payload)
      "news.normalize_document" -> News.normalize_documents(payload)
      "news.extract_evidence" -> News.normalize_documents(payload)
      "news.classify_entities" -> News.classify_documents(payload)
      "news.classify_regions" -> News.classify_documents(payload)
      "news.classify_topics" -> News.classify_documents(payload)
      "news.cluster_events" -> News.cluster_events(payload)
      "news.score_events" -> News.score_events(payload)
      "news.generate_summary" -> News.generate_summary(payload)
      "news.translate_summary" -> News.translate_summary(payload)
      "news.rebuild_search_index" -> News.rebuild_search_index(payload)
      "news.backfill_source" -> News.backfill_source(payload)
      _ -> {:discard, "unsupported Elixir job type: #{job_type}"}
    end
  end

  defp normalize_result(result, _job_type) do
    case result do
      :ok -> :ok
      {:ok, value} -> {:ok, value}
      {:error, reason} -> {:error, reason}
      {:discard, reason} -> {:discard, reason}
      {:snooze, seconds} -> {:snooze, seconds}
      value -> {:ok, value}
    end
  end

  defp normalize_payload(payload) when is_map(payload), do: payload
  defp normalize_payload(_), do: %{}
end
