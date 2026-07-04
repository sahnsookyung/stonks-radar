defmodule StonksBackend.ReleaseControls do
  @moduledoc """
  Admin-only release readiness and rollback helpers.

  Public health intentionally stays minimal. This module gathers the richer
  operational facts needed for canary promotion, rollback, and provenance-based
  cleanup without exposing provider internals to public routes.
  """

  alias StonksBackend.{Settings, Sql}

  @payload_version 1
  @runtime_switches [
    :worker_scheduler_enabled,
    :news_gdelt_enabled,
    :gdelt_runtime_fetch_enabled,
    :news_pipeline_runtime_enabled,
    :market_data_scheduled_refresh_enabled,
    :yield_curve_history_enabled,
    :shorts_ingestion_enabled
  ]
  @funnel_keys [
    "fetched",
    "parsed",
    "deduped",
    "classified",
    "clustered",
    "published",
    "published_or_projected",
    "blocked_or_denied"
  ]
  @default_thresholds %{
    queue_depth: 100,
    queue_age_seconds: 900,
    unsafe_dead_jobs: 0,
    provider_failure_rate: 0.25,
    failed_sources: 0,
    snapshot_age_seconds: 7_200,
    public_p95_ms: 2_500
  }

  def payload_version, do: @payload_version

  def admin_summary(opts \\ []) do
    metrics = collect_metrics(opts)
    thresholds = thresholds(opts)
    release_id = release_id()

    %{
      release_id: release_id,
      payload_version: @payload_version,
      runtime_switches: runtime_switches(opts),
      canary: evaluate_canary(metrics, thresholds),
      source_funnel: source_funnel_totals(source_health_rows(opts)),
      provenance: provenance_summary(release_id, opts),
      rollback_controls: rollback_controls()
    }
  end

  def runtime_switches(opts \\ []) do
    settings = Keyword.get(opts, :settings)

    Enum.map(@runtime_switches, fn key ->
      configured = setting_value(settings, key, default_switch_value(key))

      %{
        key: to_string(key),
        enabled: Settings.truthy?(configured),
        rollback_value: "false"
      }
    end)
  end

  def evaluate_canary(metrics, thresholds \\ @default_thresholds) do
    checks = [
      threshold_check(
        "queue_depth",
        metric(metrics, :queue_depth),
        threshold(thresholds, :queue_depth),
        "Oban queue depth is below target"
      ),
      threshold_check(
        "queue_age_seconds",
        metric(metrics, :max_queue_age_seconds),
        threshold(thresholds, :queue_age_seconds),
        "Oldest queued/scheduled job age is below target"
      ),
      threshold_check(
        "unsafe_dead_jobs",
        metric(metrics, :unsafe_dead_jobs),
        threshold(thresholds, :unsafe_dead_jobs),
        "No unsafe dead/discarded jobs are present",
        :blocked
      ),
      ratio_check(
        "provider_failure_rate_24h",
        metric(metrics, :provider_failure_rate_24h),
        threshold(thresholds, :provider_failure_rate),
        "Provider failure rate stays below canary threshold"
      ),
      threshold_check(
        "failed_sources",
        metric(metrics, :failed_sources),
        threshold(thresholds, :failed_sources),
        "No sources are failed, denied, or quarantined"
      ),
      threshold_check(
        "snapshot_age_seconds",
        metric(metrics, :snapshot_age_seconds),
        threshold(thresholds, :snapshot_age_seconds),
        "Published snapshot age is fresh enough"
      ),
      threshold_check(
        "public_p95_ms",
        metric(metrics, :public_p95_ms),
        threshold(thresholds, :public_p95_ms),
        "Public p95 latency is below target"
      ),
      presence_check(
        "manifest_hash",
        metric(metrics, :manifest_hash),
        "Published manifest hash is present for origin/CDN comparison"
      ),
      severity_check(
        "disk_watermark",
        metric(metrics, :disk_watermark),
        "Disk watermark is below warning level"
      )
    ]

    %{
      status: aggregate_status(checks),
      checks: checks,
      thresholds: thresholds
    }
  end

  def source_funnel_totals(rows) do
    per_source =
      Enum.map(rows, fn row ->
        counters =
          row
          |> Map.get("details", %{})
          |> decode_json()
          |> funnel_counters()

        %{
          source_key: row["source_key"],
          status: row["status"],
          counters: counters
        }
      end)

    totals =
      Enum.reduce(per_source, empty_counters(), fn row, acc ->
        merge_counters(acc, row.counters)
      end)

    %{totals: totals, sources: per_source}
  end

  def provenance_summary(release_id, opts \\ []) do
    %{
      release_id: release_id,
      source_documents: query_scalar(opts, source_document_provenance_sql(), [release_id], 0),
      source_facts: query_scalar(opts, source_fact_provenance_sql(), [release_id], 0),
      market_bars: query_scalar(opts, market_bar_provenance_sql(), [release_id], 0),
      quarantine_available: release_id not in [nil, "", "local"]
    }
  end

  def quarantine_by_provenance(release_id, opts \\ []) do
    release_id = to_string(release_id || "")

    if release_id in ["", "local"] do
      {:error, :release_id_required}
    else
      {:ok,
       %{
         release_id: release_id,
         source_documents: execute_count(opts, quarantine_source_documents_sql(), [release_id]),
         source_facts: execute_count(opts, quarantine_source_facts_sql(), [release_id]),
         market_bars: execute_count(opts, quarantine_market_bars_sql(), [release_id])
       }}
    end
  end

  def rollback_controls do
    %{
      scheduler_pause_keys: Enum.map(@runtime_switches, &to_string/1),
      unsafe_job_states: ["executing", "available", "scheduled", "retryable"],
      rollback_actions: [
        "pause scheduler and provider runtime switches",
        "let executing jobs finish or snooze unsafe queues",
        "quarantine rollout rows by release_id",
        "publish a previously validated snapshot version",
        "verify origin and CDN manifest version/hash"
      ],
      payload_versions: %{current: @payload_version, accepted: [@payload_version]}
    }
  end

  defp collect_metrics(opts) do
    %{
      queue_depth:
        query_scalar(
          opts,
          "select count(*) from oban_jobs where state in ('available','scheduled','executing','retryable')",
          [],
          0
        ),
      max_queue_age_seconds:
        query_scalar(
          opts,
          """
          select extract(epoch from now() - min(inserted_at))::int
          from oban_jobs
          where state in ('available','scheduled','executing','retryable')
          """,
          [],
          0
        ),
      unsafe_dead_jobs:
        query_scalar(
          opts,
          "select count(*) from oban_jobs where state in ('discarded','cancelled')",
          [],
          0
        ),
      provider_failure_rate_24h: provider_failure_rate(opts),
      failed_sources:
        query_scalar(
          opts,
          "select count(*) from source_health_status where status in ('failed','denied','quarantined')",
          [],
          0
        ),
      snapshot_age_seconds:
        query_scalar(
          opts,
          """
          select extract(epoch from now() - max(coalesce(published_at, generated_at)))::int
          from publication_manifest
          where publication_status = 'published'
          """,
          [],
          nil
        ),
      public_p95_ms: operation_numeric(opts, "public_p95_ms"),
      disk_watermark: operation_value(opts, "disk_watermark", "unknown"),
      manifest_hash:
        query_scalar(
          opts,
          "select content_hash from publication_manifest where publication_status = 'published' order by published_at desc nulls last, generated_at desc limit 1",
          [],
          nil
        )
    }
  end

  defp provider_failure_rate(opts) do
    row =
      query_one(
        opts,
        """
        select count(*)::float as total,
               count(*) filter (where status not in ('succeeded','skipped'))::float as failed
        from provider_usage_event
        where created_at > now() - interval '24 hours'
        """,
        []
      )

    total = normalize_float(row["total"])
    failed = normalize_float(row["failed"])

    if total <= 0, do: 0.0, else: failed / total
  end

  defp source_health_rows(opts) do
    query_all(
      opts,
      "select source_key, status, details from source_health_status order by source_key",
      []
    )
  end

  defp thresholds(opts) do
    settings = Keyword.get(opts, :settings)

    %{
      queue_depth:
        int_setting(settings, :canary_max_queue_depth, @default_thresholds.queue_depth),
      queue_age_seconds:
        int_setting(
          settings,
          :canary_max_queue_age_seconds,
          @default_thresholds.queue_age_seconds
        ),
      unsafe_dead_jobs: @default_thresholds.unsafe_dead_jobs,
      provider_failure_rate:
        float_setting(
          settings,
          :canary_max_provider_failure_rate,
          @default_thresholds.provider_failure_rate
        ),
      failed_sources:
        int_setting(settings, :canary_max_failed_sources, @default_thresholds.failed_sources),
      snapshot_age_seconds:
        int_setting(
          settings,
          :canary_max_snapshot_age_seconds,
          @default_thresholds.snapshot_age_seconds
        ),
      public_p95_ms:
        int_setting(settings, :canary_max_public_p95_ms, @default_thresholds.public_p95_ms)
    }
  end

  defp threshold_check(key, value, target, summary, failure_status \\ :warning) do
    status =
      cond do
        is_nil(value) -> "warning"
        normalize_float(value) <= normalize_float(target) -> "pass"
        failure_status == :blocked -> "blocked"
        true -> "warning"
      end

    %{key: key, status: status, value: value, threshold: target, summary: summary}
  end

  defp ratio_check(key, value, target, summary) do
    threshold_check(key, Float.round(normalize_float(value), 4), target, summary)
  end

  defp presence_check(key, value, summary) do
    status = if is_binary(value) and String.trim(value) != "", do: "pass", else: "warning"
    %{key: key, status: status, value: value, threshold: "present", summary: summary}
  end

  defp severity_check(key, value, summary) do
    status =
      case value do
        "critical" -> "blocked"
        "warning" -> "warning"
        "info" -> "pass"
        "ok" -> "pass"
        _ -> "warning"
      end

    %{key: key, status: status, value: value, threshold: "info_or_ok", summary: summary}
  end

  defp aggregate_status(checks) do
    cond do
      Enum.any?(checks, &(&1.status == "blocked")) -> "blocked"
      Enum.any?(checks, &(&1.status == "warning")) -> "warning"
      true -> "ready"
    end
  end

  defp funnel_counters(details) do
    counters =
      case details do
        %{"discovery" => %{} = discovery} -> discovery
        %{} -> details
        _ -> %{}
      end

    Map.new(@funnel_keys, fn key -> {key, normalize_int(counters[key])} end)
  end

  defp empty_counters, do: Map.new(@funnel_keys, &{&1, 0})

  defp merge_counters(left, right) do
    Map.new(@funnel_keys, fn key ->
      {key, normalize_int(left[key]) + normalize_int(right[key])}
    end)
  end

  defp operation_value(opts, key, default) do
    query_scalar(
      opts,
      "select severity from operation_status where status_key = $1",
      [key],
      default
    )
  end

  defp operation_numeric(opts, key) do
    opts
    |> query_scalar("select status_value from operation_status where status_key = $1", [key], nil)
    |> normalize_int()
  end

  defp source_document_provenance_sql do
    "select count(*) from source_document where #{source_document_release_expr()} = $1"
  end

  defp source_fact_provenance_sql do
    "select count(*) from source_fact where object_json->>'release_id' = $1"
  end

  defp market_bar_provenance_sql do
    "select count(*) from market_price_bar where source_policy_json->>'release_id' = $1"
  end

  defp quarantine_source_documents_sql do
    "update source_document set status = 'quarantined', updated_at = now() where #{source_document_release_expr()} = $1"
  end

  defp source_document_release_expr,
    do: "coalesce(metadata->>'release_id', metadata->'metadata'->>'release_id')"

  defp quarantine_source_facts_sql do
    "update source_fact set review_status = 'quarantined', public_allowed = false where object_json->>'release_id' = $1"
  end

  defp quarantine_market_bars_sql do
    "update market_price_bar set quality_state = 'quarantined', updated_at = now() where source_policy_json->>'release_id' = $1"
  end

  defp query_scalar(opts, sql, params, default) do
    query_fun = Keyword.get(opts, :scalar_fun, &Sql.scalar/3)
    query_fun.(sql, params, default)
  end

  defp query_one(opts, sql, params) do
    query_fun = Keyword.get(opts, :one_fun, &Sql.one/2)
    query_fun.(sql, params) || %{}
  end

  defp query_all(opts, sql, params) do
    query_fun = Keyword.get(opts, :all_fun, &Sql.all/2)
    query_fun.(sql, params)
  end

  defp execute_count(opts, sql, params) do
    execute_fun = Keyword.get(opts, :execute_fun, &Sql.execute/2)
    result = execute_fun.(sql, params)
    Map.get(result, :num_rows, 0)
  end

  defp setting_value(nil, key, default), do: Settings.get(key, default)
  defp setting_value(settings, key, default), do: Keyword.get(settings, key, default)

  defp default_switch_value(:news_gdelt_enabled), do: "false"
  defp default_switch_value(:gdelt_runtime_fetch_enabled), do: "false"
  defp default_switch_value(_), do: "true"

  defp int_setting(settings, key, default) do
    settings
    |> setting_value(key, default)
    |> normalize_int(default)
  end

  defp float_setting(settings, key, default) do
    settings
    |> setting_value(key, default)
    |> normalize_float(default)
  end

  defp metric(metrics, key), do: Map.get(metrics, key) || Map.get(metrics, to_string(key))

  defp threshold(thresholds, key),
    do: Map.get(thresholds, key) || Map.get(thresholds, to_string(key))

  defp decode_json(%{} = value), do: value

  defp decode_json(value) when is_binary(value) do
    case Jason.decode(value) do
      {:ok, decoded} when is_map(decoded) -> decoded
      _ -> %{}
    end
  end

  defp decode_json(_), do: %{}

  defp normalize_int(value, default \\ 0)
  defp normalize_int(value, _default) when is_integer(value), do: value
  defp normalize_int(value, _default) when is_float(value), do: round(value)

  defp normalize_int(%Decimal{} = value, default) do
    Decimal.to_integer(value)
  rescue
    _ -> default
  end

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(value) do
      {parsed, _} -> parsed
      :error -> default
    end
  end

  defp normalize_int(_, default), do: default

  defp normalize_float(value, default \\ 0.0)
  defp normalize_float(value, _default) when is_integer(value), do: value / 1
  defp normalize_float(value, _default) when is_float(value), do: value

  defp normalize_float(%Decimal{} = value, default) do
    Decimal.to_float(value)
  rescue
    _ -> default
  end

  defp normalize_float(value, default) when is_binary(value) do
    case Float.parse(value) do
      {parsed, _} -> parsed
      :error -> default
    end
  end

  defp normalize_float(_, default), do: default

  defp release_id do
    System.get_env("STONKS_RELEASE_ID") ||
      System.get_env("GITHUB_SHA") ||
      "local"
  end
end
