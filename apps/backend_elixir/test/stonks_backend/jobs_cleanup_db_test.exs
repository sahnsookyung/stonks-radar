defmodule StonksBackend.JobsCleanupDbTest do
  use ExUnit.Case, async: false

  alias StonksBackend.Jobs
  alias StonksBackend.Jobs.RuntimeLock
  alias StonksBackend.Jobs.Workers.GenericWorker
  alias StonksBackend.Repo

  @tag :db
  test "stale snapshot refresh cleanup preserves only the current window" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    stale = insert_snapshot_job!("snapshot-refresh:100")
    current = insert_snapshot_job!("snapshot-refresh:101")

    assert Jobs.discard_stale_snapshot_refresh_jobs("snapshot-refresh:101") == 1
    assert Repo.get!(Oban.Job, stale.id).state == "discarded"
    assert Repo.get!(Oban.Job, current.id).state == "available"
  end

  @tag :db
  test "runtime locks acquire, reject contention, and release" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    assert RuntimeLock.acquire("global", "snapshots", "oban:1", 900)
    refute RuntimeLock.acquire("global", "snapshots", "oban:2", 900)
    assert RuntimeLock.release("global", "snapshots", "oban:1").num_rows == 1
    assert RuntimeLock.acquire("global", "snapshots", "oban:2", 900)
  end

  @tag :db
  test "completed snapshot refresh windows remain idempotent" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    start_supervised!(
      {Oban, repo: Repo, queues: false, plugins: false, peer: false, testing: :disabled}
    )

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    opts = [
      queue: "snapshots",
      idempotency_key: "snapshot-refresh:101",
      unique_states: [:available, :scheduled, :executing, :completed]
    ]

    assert {:ok, first_id} = Jobs.enqueue("snapshot_refresh", %{}, opts)
    assert {:ok, {:oban, job_id}} = Jobs.parse_external_id(first_id)

    job = Repo.get!(Oban.Job, job_id)

    job
    |> Ecto.Changeset.change(state: "completed", completed_at: DateTime.utc_now())
    |> Repo.update!()

    assert {:ok, ^first_id} = Jobs.enqueue("snapshot_refresh", %{}, opts)
    assert Repo.aggregate(Oban.Job, :count, :id) == 1
  end

  @tag :db
  test "published manifests durably gate snapshot refresh windows" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    refresh_seconds = 900
    current_window = div(DateTime.to_unix(DateTime.utc_now()), refresh_seconds)
    window = current_window + 1
    window_start = DateTime.from_unix!(window * refresh_seconds)
    assert Jobs.snapshot_refresh_due?(window_start)

    version = System.unique_integer([:positive])

    Ecto.Adapters.SQL.query!(
      Repo,
      """
      insert into publication_manifest(
        snapshot_version,
        manifest_json,
        storage_object_key,
        content_hash,
        byte_size,
        generated_at,
        published_at,
        publication_status
      )
      values ($1, '{}'::jsonb, $2, $3, 2, $4, $4, 'published')
      """,
      [version, "test/manifests/#{version}.json", "test-#{version}", window_start]
    )

    refute Jobs.snapshot_refresh_due?(window_start)
    assert Jobs.snapshot_refresh_due?(DateTime.add(window_start, refresh_seconds, :second))

    job = %Oban.Job{
      id: System.unique_integer([:positive]),
      args: %{
        "job_type" => "snapshot_refresh",
        "idempotency_key" => "snapshot-refresh:#{window}",
        "payload" => %{}
      }
    }

    assert {:discard, reason} = GenericWorker.perform(job)
    assert reason == "snapshot refresh window #{window} is already published"
  end

  defp insert_snapshot_job!(idempotency_key) do
    args =
      Jobs.worker_args("snapshot_refresh", %{},
        queue: "snapshots",
        idempotency_key: idempotency_key
      )

    args
    |> GenericWorker.new(queue: :snapshots)
    |> Repo.insert!()
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
