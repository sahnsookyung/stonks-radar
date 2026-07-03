defmodule StonksBackend.JobsWorkerTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Jobs.Workers.GenericWorker

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
