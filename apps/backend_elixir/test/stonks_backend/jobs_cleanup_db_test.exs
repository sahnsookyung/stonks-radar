defmodule StonksBackend.JobsCleanupDbTest do
  use ExUnit.Case, async: false

  alias StonksBackend.Jobs
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
