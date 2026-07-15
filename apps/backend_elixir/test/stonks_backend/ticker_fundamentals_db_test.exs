defmodule StonksBackend.TickerFundamentalsDbTest do
  use ExUnit.Case, async: false

  alias StonksBackend.{Repo, TickerFundamentals}

  @tag :db
  test "refresh persists normalized SEC dates and timestamps" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    on_exit(fn ->
      if Process.whereis(Repo), do: Ecto.Adapters.SQL.Sandbox.checkin(Repo)
    end)

    request_fun = fn _url, _opts ->
      {:ok,
       %{
         status: 200,
         body: %{
           "facts" => %{
             "us-gaap" => %{
               "Revenues" => %{
                 "units" => %{
                   "USD" => [
                     %{
                       "val" => 100,
                       "end" => "2026-03-28",
                       "filed" => "2026-05-01",
                       "form" => "10-Q",
                       "fp" => "Q2",
                       "accn" => "0000320193-26-000013"
                     }
                   ]
                 }
               }
             }
           }
         }
       }}
    end

    assert {:ok, %{requested: 1, refreshed: 1, unavailable: 0}} =
             TickerFundamentals.refresh(%{"symbol" => "AAPL"},
               request_fun: request_fun,
               request_delay_ms: 0
             )

    assert %{
             rows: [
               [
                 "AAPL",
                 ~D[2026-03-28],
                 %DateTime{},
                 %{"revenue" => 100},
                 %{"source" => "SEC CompanyFacts"}
               ]
             ]
           } =
             Ecto.Adapters.SQL.query!(
               Repo,
               """
               select symbol, period_end, source_filed_at, metrics, provenance
               from ticker_fundamental_snapshot
               where symbol = 'AAPL'
               order by fetched_at desc
               limit 1
               """
             )
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
