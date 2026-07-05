defmodule StonksBackend.ReleaseControlsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.ReleaseControls

  test "runtime switches expose every rollback kill switch" do
    switches =
      ReleaseControls.runtime_switches(
        settings: [
          worker_scheduler_enabled: true,
          news_gdelt_enabled: false,
          gdelt_runtime_fetch_enabled: false,
          news_pipeline_runtime_enabled: true,
          market_data_scheduled_refresh_enabled: true,
          yield_curve_history_enabled: true,
          shorts_ingestion_enabled: false
        ]
      )

    keys = MapSet.new(switches, & &1.key)

    assert MapSet.subset?(
             MapSet.new([
               "worker_scheduler_enabled",
               "news_gdelt_enabled",
               "gdelt_runtime_fetch_enabled",
               "news_pipeline_runtime_enabled",
               "market_data_scheduled_refresh_enabled",
               "yield_curve_history_enabled",
               "shorts_ingestion_enabled"
             ]),
             keys
           )

    assert Enum.all?(switches, &(&1.rollback_value == "false"))
  end

  test "canary evaluation blocks unsafe dead jobs and warns on stale metrics" do
    summary =
      ReleaseControls.evaluate_canary(
        %{
          queue_depth: 12,
          max_queue_age_seconds: 30,
          unsafe_dead_jobs: 1,
          provider_failure_rate_24h: 0.4,
          failed_sources: 0,
          snapshot_age_seconds: 10_000,
          public_p95_ms: 900,
          manifest_hash: "hash",
          disk_watermark: "info"
        },
        %{
          queue_depth: 100,
          queue_age_seconds: 900,
          unsafe_dead_jobs: 0,
          provider_failure_rate: 0.25,
          failed_sources: 0,
          snapshot_age_seconds: 7_200,
          public_p95_ms: 2_500
        }
      )

    assert summary.status == "blocked"

    by_key = Map.new(summary.checks, &{&1.key, &1})
    assert by_key["unsafe_dead_jobs"].status == "blocked"
    assert by_key["provider_failure_rate_24h"].status == "warning"
    assert by_key["snapshot_age_seconds"].status == "warning"
  end

  test "source funnel totals reconcile direct and nested discovery counters" do
    summary =
      ReleaseControls.source_funnel_totals([
        %{
          "source_key" => "gdelt",
          "status" => "ready",
          "details" => %{"discovery" => %{"fetched" => 10, "deduped" => 7, "published" => 2}}
        },
        %{
          "source_key" => "rss",
          "status" => "ready",
          "details" => Jason.encode!(%{"fetched" => 3, "parsed" => 2, "blocked_or_denied" => 1})
        },
        %{
          "source_key" => "news_pipeline:classified",
          "status" => "ready",
          "details" => %{"discovery" => %{"classified" => 4, "clustered" => 2}}
        }
      ])

    assert summary.totals["fetched"] == 13
    assert summary.totals["deduped"] == 7
    assert summary.totals["published"] == 2
    assert summary.totals["classified"] == 4
    assert summary.totals["clustered"] == 2
    assert summary.totals["blocked_or_denied"] == 1
  end

  test "pipeline health summarizes stage timing and counters" do
    summary =
      ReleaseControls.pipeline_health_summary([
        %{
          "source_key" => "gdelt",
          "status" => "ready",
          "details" => %{"discovery" => %{"fetched" => 10}}
        },
        %{
          "source_key" => "news_pipeline:classified",
          "status" => "ready",
          "details" =>
            Jason.encode!(%{
              "stage" => "classified",
              "status" => "ready",
              "release_id" => "release-123",
              "runtime_enabled" => true,
              "stage_started_at" => "2026-07-04T11:00:00Z",
              "stage_completed_at" => "2026-07-04T11:00:01Z",
              "duration_ms" => 1200,
              "discovery" => %{"classified" => 4}
            })
        },
        %{
          "source_key" => "news_pipeline:clustered",
          "status" => "ready",
          "details" => %{
            "stage" => "clustered",
            "runtime_enabled" => true,
            "stage_completed_at" => "2026-07-04T11:00:03Z",
            "duration_ms" => 300,
            "discovery" => %{"clustered" => 2}
          }
        }
      ])

    assert summary.status == "ready"
    assert summary.stage_count == 2
    assert summary.last_completed_at == "2026-07-04T11:00:03Z"
    assert summary.total_duration_ms == 1500
    assert [classified | _] = summary.stages
    assert classified.stage == "classified"
    assert classified.release_id == "release-123"
    assert classified.counters["classified"] == 4
  end

  test "deployment summary exposes image, artifact, and expected commit refs" do
    summary =
      ReleaseControls.deployment_summary("release-123",
        env: %{
          "STONKS_EXPECTED_COMMIT" => "abc123",
          "STONKS_API_IMAGE_REF" => "iad.ocir.io/ns/stonks-api:abc123",
          "STONKS_WEB_ARTIFACT_VERSION" => "web-abc123",
          "MIX_ENV" => "prod"
        }
      )

    assert summary.release_id == "release-123"
    assert summary.expected_commit == "abc123"
    assert summary.api_image_ref == "iad.ocir.io/ns/stonks-api:abc123"
    assert summary.web_artifact_version == "web-abc123"
    assert summary.runtime_environment == "prod"
  end

  test "snapshot publish health reports latest manifest and stale status" do
    one_fun = fn sql, [] ->
      if sql =~ "publication_manifest" do
        %{
          "snapshot_version" => 7,
          "content_hash" => "sha256:manifest",
          "generated_at" => ~U[2026-07-05 09:00:00Z],
          "published_at" => ~U[2026-07-05 09:05:00Z],
          "publication_status" => "published"
        }
      else
        %{}
      end
    end

    health =
      ReleaseControls.snapshot_publish_health(
        %{snapshot_age_seconds: 8_000, manifest_hash: "sha256:metric"},
        %{snapshot_age_seconds: 7_200},
        one_fun: one_fun
      )

    assert health.status == "stale"
    assert health.latest_manifest_version == 7
    assert health.latest_manifest_hash == "sha256:manifest"
    assert health.snapshot_age_seconds == 8_000
    assert health.max_snapshot_age_seconds == 7_200
    assert health.publish_health == "published_manifest_stale"
  end

  test "provenance summary uses the current release id and disables local quarantine" do
    scalar_fun = fn sql, [release_id], default ->
      cond do
        sql =~ "source_document" and release_id == "local" -> 2
        sql =~ "source_fact" and release_id == "local" -> 3
        sql =~ "market_price_bar" and release_id == "local" -> 5
        true -> default
      end
    end

    summary = ReleaseControls.provenance_summary("local", scalar_fun: scalar_fun)

    assert summary.source_documents == 2
    assert summary.source_facts == 3
    assert summary.market_bars == 5
    refute summary.quarantine_available
    assert ReleaseControls.quarantine_by_provenance("local") == {:error, :release_id_required}
  end
end
