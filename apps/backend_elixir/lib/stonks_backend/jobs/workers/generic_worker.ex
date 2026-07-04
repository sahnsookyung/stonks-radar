defmodule StonksBackend.Jobs.Workers.GenericWorker do
  @moduledoc "Oban worker dispatch surface for migrated backend job components."
  use Oban.Worker, max_attempts: 5

  alias StonksBackend.{
    Instruments,
    MarketData,
    News,
    Settings,
    Shorts,
    Snapshots,
    Sources,
    Sql,
    YieldCurves
  }

  alias StonksBackend.Jobs.RuntimeLock

  require Logger

  @news_pipeline_job_types MapSet.new([
                             "news.read_pages",
                             "news.purge_email_raw",
                             "news.prune_metadata",
                             "news.normalize_document",
                             "news.extract_evidence",
                             "news.classify_entities",
                             "news.classify_regions",
                             "news.classify_topics",
                             "news.cluster_events",
                             "news.score_events",
                             "news.generate_summary",
                             "news.translate_summary",
                             "news.rebuild_search_index"
                           ])

  @impl Oban.Worker
  def perform(%Oban.Job{args: %{"job_type" => job_type} = args} = job) do
    payload = normalize_payload(Map.get(args, "payload"))
    Logger.info("oban_job_dispatch job_type=#{job_type} id=#{job.id}")

    case dependency_gate(args) do
      :ready ->
        perform_ready(job, job_type, payload, args)

      {:snooze, seconds} ->
        Logger.info("oban_job_dependency_wait job_type=#{job_type} id=#{job.id}")
        {:snooze, seconds}

      {:discard, reason} ->
        {:discard, reason}
    end
  end

  def perform(%Oban.Job{args: args}) do
    {:discard, "missing job_type in Oban args: #{inspect(args)}"}
  end

  defp perform_ready(job, job_type, payload, args) do
    owner = "oban:#{job.id}"
    scopes = RuntimeLock.scopes_from_args(args)

    case RuntimeLock.acquire_many(scopes, owner) do
      {:ok, acquired_scopes} ->
        try do
          if runtime_job_enabled?(job_type) do
            job_type
            |> dispatch(payload)
            |> normalize_result(job_type)
          else
            {:ok, disabled_result(job_type, "news_pipeline_runtime_enabled_false")}
          end
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

  defp dependency_gate(%{"depends_on_job_id" => "oban:" <> raw_id}) do
    with {id, ""} <- Integer.parse(raw_id),
         true <- id > 0 do
      case dependency_state(id) do
        state when state in ["completed"] ->
          :ready

        state when state in ["cancelled", "discarded"] ->
          {:discard, "dependency oban:#{id} #{state}"}

        _state ->
          {:snooze, 30}
      end
    else
      _ -> {:discard, "invalid depends_on_job_id"}
    end
  end

  defp dependency_gate(_args), do: :ready

  defp dependency_state(id) do
    Sql.scalar("select state from oban_jobs where id = $1", [id])
  rescue
    _ -> nil
  end

  defp dispatch(job_type, payload) do
    case job_type do
      "snapshot_build" -> Snapshots.build_candidate(payload)
      "snapshot_publish" -> Snapshots.publish_from_payload(payload)
      "snapshot_refresh" -> Snapshots.refresh(payload)
      "news.publish_snapshots" -> Snapshots.refresh(payload)
      "instrument_search_index_update" -> Instruments.refresh_index(payload)
      "market_data.refresh_history" -> MarketData.refresh_history(payload)
      "yield_curves.refresh_history" -> YieldCurves.refresh_history(payload)
      "trump_disclosures_ingest" -> Sources.ingest_disclosures(payload)
      "shorts.finra_daily_short_volume" -> Shorts.fetch_daily_short_volume(payload)
      "shorts.finra_short_interest_release" -> Shorts.fetch_short_interest_release(payload)
      "shorts.short_research_metadata" -> Shorts.refresh_short_research_metadata(payload)
      "news.fetch_source" -> News.fetch_source(payload)
      "news.read_pages" -> News.read_pages(payload)
      "news.purge_email_raw" -> News.purge_email_raw(payload)
      "news.prune_metadata" -> News.prune_metadata(payload)
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

  defp runtime_job_enabled?(job_type) do
    cond do
      MapSet.member?(@news_pipeline_job_types, job_type) ->
        Settings.truthy?(Settings.get(:news_pipeline_runtime_enabled, "true"))

      true ->
        true
    end
  end

  defp disabled_result(job_type, reason) do
    %{
      status: "disabled",
      job_type: job_type,
      reason: reason,
      elixir_component: "oban_dispatch"
    }
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
