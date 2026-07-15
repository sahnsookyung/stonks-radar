defmodule StonksBackend.NewsHealthDbTest do
  use ExUnit.Case, async: false

  alias StonksBackend.{News, Repo, Sql}

  @tag :db
  test "successful source and pipeline health records include a success timestamp" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo), do: Ecto.Adapters.SQL.Sandbox.checkin(Repo)
    end)

    assert {:ok, %{status: "query_pack_ready"}} =
             News.fetch_source(%{"source_key" => "gdelt", "max_documents" => 1})

    assert %{
             "status" => "ready",
             "last_success_at" => source_success
           } =
             Sql.one(
               "select status, last_success_at from source_health_status where source_key = 'gdelt'"
             )

    assert is_binary(source_success)

    assert {:ok, _result} = News.normalize_documents(%{"limit" => 1})

    assert %{
             "status" => "ready",
             "last_success_at" => pipeline_success
           } =
             Sql.one(
               "select status, last_success_at from source_health_status where source_key = 'news_pipeline:normalized'"
             )

    assert is_binary(pipeline_success)
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
