defmodule StonksBackend.JobsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Jobs
  alias StonksBackend.Jobs.{LegacyQueue, RuntimeLock}

  @legacy_id "550e8400-e29b-41d4-a716-446655440000"

  test "external ids are explicitly namespaced" do
    assert Jobs.external_id(42) == "oban:42"
  end

  test "job id parsing accepts only oban and legacy replay ids" do
    assert Jobs.parse_external_id("oban:123") == {:ok, {:oban, 123}}
    assert Jobs.parse_external_id("legacy:#{@legacy_id}") == {:ok, {:legacy, @legacy_id}}

    assert Jobs.accepted_replay_id?("oban:123")
    assert Jobs.accepted_replay_id?("legacy:#{@legacy_id}")

    refute Jobs.accepted_replay_id?("123")
    refute Jobs.accepted_replay_id?("oban:0")
    refute Jobs.accepted_replay_id?("legacy:not-a-uuid")
  end

  test "job references are normalized into explicit replay namespaces" do
    assert Jobs.normalize_reference_id(42) == "oban:42"
    assert Jobs.normalize_reference_id("42") == "oban:42"
    assert Jobs.normalize_reference_id("oban:0042") == "oban:42"

    assert Jobs.normalize_reference_id("legacy:#{String.upcase(@legacy_id)}") ==
             "legacy:#{@legacy_id}"

    assert Jobs.normalize_reference_id(String.upcase(@legacy_id)) == "legacy:#{@legacy_id}"

    assert Jobs.normalize_reference_id("not-a-job-id") == nil
    assert Jobs.normalize_reference_id("0") == nil
  end

  test "queue routing preserves migration domains" do
    assert Jobs.queue_for("snapshot_refresh") == :snapshots
    assert Jobs.queue_for("news.fetch_source") == :news
    assert Jobs.queue_for("market_data.refresh_history") == :market_data
    assert Jobs.queue_for("instrument_search_index_update") == :instruments
    assert Jobs.queue_for("trump_disclosures_ingest") == :disclosures
  end

  test "unknown queues are normalized to the default Oban queue" do
    args = Jobs.worker_args("legacy.migrated", %{}, queue: "legacy-custom")

    assert args["job_group"] == "default"
  end

  test "worker args preserve queue, idempotency, source, provider, priority, and lock metadata" do
    args =
      Jobs.worker_args(
        "market_data.refresh_history",
        %{"symbol" => "NVDA", "provider_key" => "alpha_vantage", "source_id" => "source-1"},
        idempotency_key: "NVDA:daily",
        priority: "2",
        global_lock: true,
        global_lock_key: "market-data-refresh"
      )

    assert args["job_type"] == "market_data.refresh_history"
    assert args["payload_version"] == 1
    assert args["job_group"] == "market_data"
    assert args["priority"] == 2
    assert args["idempotency_key"] == "NVDA:daily"
    assert args["payload"]["symbol"] == "NVDA"

    assert args["runtime_locks"] == [
             %{"scope_type" => "provider", "scope_key" => "alpha_vantage"},
             %{"scope_type" => "source", "scope_key" => "source-1"},
             %{"scope_type" => "global", "scope_key" => "market-data-refresh"}
           ]

    clamped =
      Jobs.worker_args("legacy.migrated", %{"depends_on_job_id" => @legacy_id}, priority: "100")

    assert clamped["priority"] == 9
    assert clamped["depends_on_job_id"] == "legacy:#{@legacy_id}"
  end

  test "snapshot jobs derive a durable global runtime lock" do
    args = Jobs.worker_args("snapshot_publish", %{"snapshot_version" => 2})

    assert args["runtime_locks"] == [
             %{"scope_type" => "global", "scope_key" => "snapshots"}
           ]
  end

  test "legacy job_queue rows map defensively to Oban enqueue shape" do
    run_after = "2026-06-28T10:30:00"

    row = %{
      id: @legacy_id,
      job_type: "news.publish_snapshots",
      job_group: "snapshots",
      priority: "1",
      idempotency_key: "",
      payload: Jason.encode!(%{requested_by: "admin", provider_key: "newsapi"}),
      source_id: "source-2",
      depends_on_job_id: String.upcase(@legacy_id),
      run_after: run_after
    }

    assert {:ok, {job_type, payload, opts}} = Jobs.legacy_row_to_enqueue(row)
    assert job_type == "news.publish_snapshots"
    assert payload == %{"requested_by" => "admin", "provider_key" => "newsapi"}
    assert opts[:queue] == "snapshots"
    assert opts[:priority] == 1
    assert opts[:idempotency_key] == @legacy_id
    assert opts[:provider_key] == "newsapi"
    assert opts[:source_id] == "source-2"
    assert opts[:depends_on_job_id] == "legacy:#{@legacy_id}"
    assert opts[:run_after] == run_after
    assert opts[:legacy_job_id] == @legacy_id
  end

  test "legacy nonterminal query only projects available columns" do
    query = LegacyQueue.nonterminal_query(["id", "job_type", "status", "created_at"])

    assert query =~ "id::text as id"
    assert query =~ "job_type"
    assert query =~ "where status = any($1)"
    assert query =~ "created_at asc"
    assert query =~ "limit $2"
    refute query =~ "payload"
  end

  test "runtime lock scope derivation handles duplicates, invalid scopes, and stale leases" do
    scopes =
      RuntimeLock.normalize_scopes([
        %{"scope_type" => "provider", "scope_key" => "alpha"},
        {:provider, "alpha"},
        %{"scope_type" => "source", "scope_key" => "source-1"},
        %{"scope_type" => "job_type", "scope_key" => "ignored"}
      ])

    assert scopes == [
             %{"scope_type" => "provider", "scope_key" => "alpha"},
             %{"scope_type" => "source", "scope_key" => "source-1"}
           ]

    now = DateTime.utc_now()
    assert RuntimeLock.stale?(DateTime.add(now, -1, :second), now)
    assert RuntimeLock.stale?(now, now)
    assert RuntimeLock.stale?(NaiveDateTime.to_iso8601(DateTime.to_naive(now)), now)
    refute RuntimeLock.stale?(DateTime.add(now, 1, :second), now)
    refute RuntimeLock.stale?(nil, now)
  end
end
