defmodule StonksBackend.News do
  @moduledoc "Elixir news job component used by Oban during the backend cutover."

  alias StonksBackend.{News.Gdelt, News.Pipeline, News.SourceFetcher, Settings, Sources, Sql}

  @discovery_zero %{
    fetched: 0,
    parsed: 0,
    deduped: 0,
    title_enriched: 0,
    title_fallback: 0,
    stale_dropped: 0,
    irrelevant_dropped: 0,
    no_geo_dropped: 0,
    blocked_or_denied: 0,
    published_or_projected: 0
  }

  def fetch_source(%{"source_key" => "gdelt"} = payload) do
    max_documents = payload |> Map.get("max_documents") |> normalize_int(default_max_documents())
    cycle_index = payload |> Map.get("cycle_index") |> normalize_int(current_cycle_index())

    summary =
      Gdelt.query_pack_summary(
        pack_name: Settings.get(:gdelt_doc_query_pack, "market_watch"),
        max_documents: max_documents,
        cycle_budget: Settings.get(:gdelt_doc_cycle_budget, 10),
        provider_cap: Settings.get(:gdelt_doc_max_records, 250),
        cycle_index: cycle_index,
        timespan: gdelt_doc_timespan(payload)
      )

    cond do
      not gdelt_runtime_fetch_enabled?() ->
        record_source_health(
          "gdelt",
          "ready",
          Map.put(summary_details(summary), :discovery, @discovery_zero)
        )

        {:ok,
         Map.merge(summary, %{
           status: "query_pack_ready",
           source_key: "gdelt",
           trust_tier: "T4_WEAK_SIGNAL",
           copyright_mode: "metadata_only",
           discovery_only: true,
           discovery: @discovery_zero
         })}

      not gdelt_enabled?() ->
        record_source_health("gdelt", "disabled", %{
          reason: "NEWS_GDELT_ENABLED is false",
          discovery: @discovery_zero,
          elixir_component: "gdelt_doc_runtime_fetch"
        })

        {:ok,
         %{
           status: "disabled",
           source_key: "gdelt",
           documents: 0,
           trust_tier: "T4_WEAK_SIGNAL",
           copyright_mode: "metadata_only",
           discovery_only: true,
           discovery: @discovery_zero
         }}

      true ->
        {documents, discovery} =
          Gdelt.fetch_doc_documents(summary,
            endpoint:
              Settings.get(:gdelt_doc_api_url, "https://api.gdeltproject.org/api/v2/doc/doc"),
            max_documents: max_documents,
            title_fetch_limit: Settings.get(:gdelt_title_fetch_limit, 20),
            title_fetch_timeout_seconds: Settings.get(:gdelt_title_fetch_timeout_seconds, 8),
            title_fetch_max_bytes: Settings.get(:gdelt_title_fetch_max_bytes, 131_072),
            title_per_host_interval_seconds:
              Settings.get(:gdelt_title_per_host_interval_seconds, 2)
          )

        persisted = Sources.persist_metadata_documents("gdelt", documents)
        status = if documents == [], do: "empty", else: "ready"
        health_status = if documents == [], do: "degraded", else: "ready"

        details =
          Map.merge(summary_details(summary), %{
            discovery: discovery,
            elixir_component: "gdelt_doc_runtime_fetch",
            persisted: persisted,
            document_count: length(documents)
          })

        record_source_health("gdelt", health_status, details)

        {:ok,
         Map.merge(summary, %{
           status: status,
           source_key: "gdelt",
           documents: length(documents),
           persisted: persisted,
           trust_tier: "T4_WEAK_SIGNAL",
           copyright_mode: "metadata_only",
           discovery_only: true,
           discovery: discovery
         })}
    end
  end

  def fetch_source(payload) do
    source_key = payload |> Map.get("source_key", "unknown") |> to_string()

    case SourceFetcher.fetch_documents(source_key, payload) do
      {:ok, documents, fetch_details} ->
        persisted = Sources.persist_metadata_documents(source_key, documents)
        status = if documents == [], do: "empty", else: "ready"
        health_status = if documents == [], do: "degraded", else: "ready"

        record_source_health(source_key, health_status, %{
          elixir_component: "metadata_source_fetch",
          source_key: source_key,
          fetch: fetch_details,
          persisted: persisted,
          document_count: length(documents),
          discovery: discovery_counters(length(documents))
        })

        {:ok,
         %{
           status: status,
           source_key: source_key,
           documents: length(documents),
           persisted: persisted,
           trust_tier: profile_trust_tier(source_key, payload),
           copyright_mode: profile_copyright_mode(source_key, payload),
           discovery: discovery_counters(length(documents))
         }}

      {:error, :unsupported_source} ->
        record_source_health(source_key, "unsupported", %{
          reason: "elixir_news_source_fetch_component_not_enabled",
          source_key: source_key
        })

        {:error,
         %{
           status: "unsupported",
           source_key: source_key,
           documents: 0,
           reason: "Elixir metadata fetch for this source is not enabled yet"
         }}

      {:error, reason} ->
        record_source_health(source_key, "failed", %{
          reason: inspect(reason),
          source_key: source_key,
          elixir_component: "metadata_source_fetch"
        })

        {:error, reason}
    end
  end

  def read_pages(payload), do: Pipeline.read_pages(payload)
  def purge_email_raw(payload), do: Pipeline.purge_email_raw(payload)
  def normalize_documents(payload), do: Pipeline.normalize_documents(payload)
  def classify_documents(payload), do: Pipeline.classify_documents(payload)
  def cluster_events(payload), do: Pipeline.cluster_events(payload)
  def score_events(payload), do: Pipeline.score_events(payload)
  def generate_summary(payload), do: Pipeline.generate_summary(payload)
  def translate_summary(payload), do: Pipeline.translate_summary(payload)
  def rebuild_search_index(payload), do: Pipeline.rebuild_search_index(payload)
  def backfill_source(payload), do: Pipeline.backfill_source(payload)
  def prune_metadata(payload), do: Pipeline.prune_metadata(payload)

  defp record_source_health(source_key, status, details) do
    status = normalize_health_status(status)

    Sql.execute(
      """
      insert into source_health_status(source_key, status, last_checked_at, details)
      values ($1, $2, now(), $3::jsonb)
      on conflict (source_key) do update
      set status = excluded.status,
          last_checked_at = excluded.last_checked_at,
          details = excluded.details
      """,
      [source_key, status, Jason.encode!(details)]
    )
  rescue
    _ -> :ok
  end

  defp profile_trust_tier(source_key, payload) do
    case SourceFetcher.profile_for(source_key, payload) do
      %{trust_tier: trust_tier} -> trust_tier
      _ -> "T4_WEAK_SIGNAL"
    end
  end

  defp profile_copyright_mode(source_key, payload) do
    case SourceFetcher.profile_for(source_key, payload) do
      %{copyright_mode: copyright_mode} -> copyright_mode
      _ -> "metadata_only"
    end
  end

  defp discovery_counters(document_count) do
    @discovery_zero
    |> Map.put(:fetched, 1)
    |> Map.put(:parsed, document_count)
    |> Map.put(:published_or_projected, document_count)
  end

  defp normalize_health_status(status)
       when status in [
              "ready",
              "degraded",
              "unsupported",
              "failed",
              "disabled",
              "denied",
              "quarantined"
            ],
       do: status

  defp normalize_health_status("empty"), do: "degraded"
  defp normalize_health_status(_), do: "failed"

  defp summary_details(summary) do
    %{
      object_key: "news:gdelt:query-pack:#{summary.query_pack}",
      query_pack: summary.query_pack,
      query_count: summary.query_count,
      candidate_records_per_query: summary.candidate_records_per_query,
      timespan: Map.get(summary, :timespan),
      query_buckets: Map.get(summary, :query_buckets, []),
      coverage_window: "36h",
      elixir_component: "gdelt_query_pack"
    }
  end

  defp gdelt_runtime_fetch_enabled? do
    Settings.truthy?(Settings.get(:gdelt_runtime_fetch_enabled, "false"))
  end

  defp gdelt_enabled? do
    Settings.truthy?(Settings.get(:news_gdelt_enabled, "false"))
  end

  defp gdelt_doc_timespan(payload) do
    cond do
      is_binary(payload["timespan"]) and String.trim(payload["timespan"]) != "" ->
        payload["timespan"]

      payload["mode"] in ["backfill", "manual_backfill"] or payload["backfill"] == true ->
        Settings.get(:gdelt_doc_backfill_timespan, "7d")

      true ->
        Settings.get(:gdelt_doc_timespan, "36h")
    end
  end

  defp current_cycle_index do
    cycle_seconds =
      Settings.get(:news_source_refresh_seconds, 900)
      |> normalize_int(900)
      |> max(300)

    System.system_time(:second) |> div(cycle_seconds)
  end

  defp default_max_documents do
    Settings.get(:news_max_documents_per_source_per_run, 100)
    |> normalize_int(100)
    |> max(1)
  end

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp normalize_int(_, default), do: default
end
