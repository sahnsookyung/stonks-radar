defmodule StonksBackend.JobsWorkerTest do
  use ExUnit.Case, async: false

  alias StonksBackend.Jobs.Workers.GenericWorker

  setup do
    original = Application.get_env(:stonks_backend, :settings)

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end
    end)
  end

  test "GDELT fetch-source jobs dispatch to the Elixir news component" do
    job = %Oban.Job{
      id: 123,
      args: %{
        "job_type" => "news.fetch_source",
        "payload" => %{"source_key" => "gdelt", "max_documents" => 30, "cycle_index" => 0}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "query_pack_ready"
    assert result.source_key == "gdelt"
    assert result.trust_tier == "T4_WEAK_SIGNAL"
    assert result.discovery_only
    assert result.copyright_mode == "metadata_only"
    assert result.query_count > 0
    assert length(result.requests) == result.query_count
  end

  test "news pipeline jobs dispatch to metadata-only Elixir stages" do
    job = %Oban.Job{
      id: 124,
      args: %{
        "job_type" => "news.cluster_events",
        "payload" => %{"batch_id" => "batch-1"}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "ready"
    assert result.documents_seen == 0
    assert result.clusters_upserted == 0
    assert result.links_upserted == 0
  end

  test "news pipeline runtime kill switch disables replayed pipeline jobs" do
    Application.put_env(:stonks_backend, :settings, news_pipeline_runtime_enabled: "false")

    job = %Oban.Job{
      id: 134,
      args: %{
        "job_type" => "news.cluster_events",
        "payload" => %{"batch_id" => "batch-1"}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "disabled"
    assert result.reason == "news_pipeline_runtime_enabled_false"
  end

  test "GDELT backfill jobs expose a bounded 7-day dry-run plan" do
    job = %Oban.Job{
      id: 131,
      args: %{
        "job_type" => "news.backfill_source",
        "payload" => %{
          "source_key" => "gdelt",
          "dry_run" => true,
          "max_documents" => 25,
          "cycle_index" => 0
        }
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "dry_run"
    assert result.source_key == "gdelt"
    assert result.backfill == true
    assert result.mode == "manual_backfill"
    assert result.would_fetch == false
    assert result.timespan == "7d"
    assert result.provider_call_count == result.query_count
    assert result.estimated_candidate_records >= result.capped_documents
    assert result.resume_cursor == "start"
    assert result.next_resume_cursor == "cycle:#{result.query_count}"
    assert result.resumable == true
    assert result.release_id in ["local", System.get_env("GITHUB_SHA")]
    assert result.source_policy_version == 1
    assert String.starts_with?(result.idempotency_key, "news:backfill:gdelt:7d:")
  end

  test "GDELT real backfill path is resumable even during runtime dark launch" do
    job = %Oban.Job{
      id: 133,
      args: %{
        "job_type" => "news.backfill_source",
        "payload" => %{
          "source_key" => "gdelt",
          "cursor" => "cycle:10",
          "max_documents" => 25,
          "cycle_index" => 10
        }
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.backfill == true
    assert result.mode == "manual_backfill"
    assert result.resume_cursor == "cycle:10"
    assert result.next_resume_cursor == "cycle:#{10 + result.query_count}"
    assert result.resumable == true
    assert result.provider_call_count == result.query_count
    assert result.coverage_window == "7d"
    assert result.release_id in ["local", System.get_env("GITHUB_SHA")]
    assert result.source_policy_version == 1
    assert result.idempotency_key =~ "news:backfill:gdelt:7d:cycle:10:max:25"
  end

  test "jobs with unfinished Oban dependencies snooze instead of running out of order" do
    job = %Oban.Job{
      id: 130,
      args: %{
        "job_type" => "news.cluster_events",
        "depends_on_job_id" => "oban:999999999",
        "payload" => %{"batch_id" => "batch-1"}
      }
    }

    assert {:snooze, 30} = GenericWorker.perform(job)
  end

  test "LLM news stages drain as explicit policy-gated skips" do
    job = %Oban.Job{
      id: 127,
      args: %{
        "job_type" => "news.generate_summary",
        "payload" => %{"event_id" => "event-1"}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "skipped"
    assert result.llm_output_written == false
    assert result.reason == "llm_summary_translation_requires_policy_and_prompt_parity"
  end

  test "news prune metadata jobs dispatch to retention policy cleanup" do
    job = %Oban.Job{
      id: 129,
      args: %{
        "job_type" => "news.prune_metadata",
        "payload" => %{
          "discovery_retention_days" => 30,
          "metadata_retention_days" => 90,
          "event_retention_days" => 365
        }
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "ready"
    assert result.discovery_retention_days == 30
    assert result.metadata_retention_days == 90
    assert result.event_retention_days == 365
  end

  test "shorts metadata jobs dispatch to metadata-only source discovery" do
    job = %Oban.Job{
      id: 128,
      args: %{
        "job_type" => "shorts.short_research_metadata",
        "payload" => %{}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status == "ready"
    assert result.source_key == "short_research_metadata"
    assert result.metadata_only == true
    assert length(result.sources) >= 3
  end

  test "yield curve history jobs dispatch to the collector" do
    job = %Oban.Job{
      id: 132,
      args: %{
        "job_type" => "yield_curves.refresh_history",
        "payload" => %{"dry_run" => true, "today" => "2026-07-02"}
      }
    }

    assert {:ok, result} = GenericWorker.perform(job)
    assert result.status in ["dry_run", "disabled"]
    assert Map.has_key?(result, :observations)
  end

  test "unsupported jobs discard explicitly instead of reporting success" do
    job = %Oban.Job{id: 125, args: %{"job_type" => "legacy.unknown", "payload" => %{}}}

    assert {:discard, "unsupported Elixir job type: legacy.unknown"} = GenericWorker.perform(job)
  end

  test "jobs without a job type are discarded with diagnostics" do
    assert {:discard, message} =
             GenericWorker.perform(%Oban.Job{id: 126, args: %{"payload" => %{}}})

    assert message =~ "missing job_type"
  end
end
