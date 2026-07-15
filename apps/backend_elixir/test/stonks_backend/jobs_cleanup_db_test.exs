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
  test "periodic cleanup discards only old recurring ingestion jobs" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    now = ~U[2026-07-14 18:00:00.000000Z]
    old_news = insert_job!("news.fetch_source", "old-news", DateTime.add(now, -7_201, :second))
    fresh_news = insert_job!("news.fetch_source", "fresh-news", DateTime.add(now, -60, :second))

    old_email =
      insert_job!("ticker_alert_email_delivery", "old-email", DateTime.add(now, -86_400, :second))

    assert Jobs.discard_stale_periodic_jobs(now) == 1
    assert Repo.get!(Oban.Job, old_news.id).state == "discarded"
    assert Repo.get!(Oban.Job, fresh_news.id).state == "available"
    assert Repo.get!(Oban.Job, old_email.id).state == "available"
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
  test "scheduled news fetches coalesce per source and replace obsolete retries" do
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

    payload = %{"source_key" => "google_news_AAPL", "max_documents" => 20}

    first_opts = [
      queue: "news",
      idempotency_key: "news-fetch:google_news_AAPL:100",
      run_after: DateTime.add(DateTime.utc_now(), 60, :second),
      unique_states: [:available, :scheduled, :executing, :retryable, :completed]
    ]

    assert {:ok, first_id} = Jobs.enqueue_scheduled("news.fetch_source", payload, first_opts)

    second_opts =
      Keyword.put(first_opts, :idempotency_key, "news-fetch:google_news_AAPL:101")

    assert {:ok, ^first_id} = Jobs.enqueue_scheduled("news.fetch_source", payload, second_opts)
    assert Repo.aggregate(Oban.Job, :count, :id) == 1

    assert {:ok, {:oban, first_job_id}} = Jobs.parse_external_id(first_id)
    first_job = Repo.get!(Oban.Job, first_job_id)

    first_job
    |> Ecto.Changeset.change(
      state: "retryable",
      scheduled_at: DateTime.add(DateTime.utc_now(), 600)
    )
    |> Repo.update!()

    assert {:ok, second_id} = Jobs.enqueue_scheduled("news.fetch_source", payload, second_opts)
    refute second_id == first_id
    assert Repo.get!(Oban.Job, first_job_id).state == "discarded"
    assert Repo.aggregate(Oban.Job, :count, :id) == 2
  end

  @tag :db
  test "news fetch cleanup discards duplicate queued rows while preserving the earliest" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo) do
        Ecto.Adapters.SQL.Sandbox.checkin(Repo)
      end
    end)

    first = insert_news_fetch_job!("google_news_MSFT", "window-1")
    second = insert_news_fetch_job!("google_news_MSFT", "window-2")
    other = insert_news_fetch_job!("google_news_NVDA", "window-1")

    second
    |> Ecto.Changeset.change(
      state: "retryable",
      scheduled_at: DateTime.add(DateTime.utc_now(), 600)
    )
    |> Repo.update!()

    assert Jobs.discard_duplicate_news_fetch_jobs() == 1
    assert Repo.get!(Oban.Job, first.id).state == "available"
    assert Repo.get!(Oban.Job, second.id).state == "discarded"
    assert Repo.get!(Oban.Job, other.id).state == "available"
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

  defp insert_job!(job_type, idempotency_key, inserted_at) do
    args = Jobs.worker_args(job_type, %{}, idempotency_key: idempotency_key)

    args
    |> GenericWorker.new()
    |> Ecto.Changeset.put_change(:inserted_at, inserted_at)
    |> Repo.insert!()
  end

  defp insert_news_fetch_job!(source_key, idempotency_key) do
    args =
      Jobs.worker_args(
        "news.fetch_source",
        %{"source_key" => source_key, "max_documents" => 20},
        queue: "news",
        idempotency_key: idempotency_key
      )

    args
    |> GenericWorker.new(queue: :news)
    |> Repo.insert!()
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
