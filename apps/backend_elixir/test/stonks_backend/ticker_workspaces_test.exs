defmodule StonksBackend.TickerWorkspacesTest do
  use ExUnit.Case, async: true

  alias StonksBackend.TickerWorkspaces

  test "normalizes and validates bounded ticker workspace state" do
    assert {:ok, workspace} =
             TickerWorkspaces.validate(%{
               version: 1,
               watchlist: [" aapl ", "AAPL", "msft"],
               notes: %{"aapl" => "Thesis"},
               comparisons: [%{id: "core", symbols: ["aapl", "msft"]}]
             })

    assert workspace["watchlist"] == ["AAPL", "MSFT"]
    assert workspace["notes"]["AAPL"]["content"] == "Thesis"
    assert hd(workspace["comparisons"])["symbols"] == ["AAPL", "MSFT"]
  end

  test "enforces workspace limits and symbol validation" do
    too_many = for index <- 1..101, do: "S#{index}"

    assert {:error, :watchlist_limit} =
             TickerWorkspaces.validate(%{version: 1, watchlist: too_many})

    assert {:error, :invalid_symbol} =
             TickerWorkspaces.validate(%{
               version: 1,
               watchlist: ["AAPL$"],
               notes: %{},
               comparisons: []
             })

    assert {:error, :invalid_notes} =
             TickerWorkspaces.validate(%{
               version: 1,
               watchlist: [],
               notes: %{"AAPL" => String.duplicate("x", 20_001)},
               comparisons: []
             })
  end

  test "merge unions watchlists, keeps newer notes, preserves conflicts, and merges comparisons by id" do
    server = %{
      version: 1,
      watchlist: ["AAPL"],
      notes: %{"AAPL" => %{content: "old server", updated_at: "2026-07-13T00:00:00Z"}},
      comparisons: [%{id: "core", symbols: ["AAPL"], updated_at: "2026-07-13T00:00:00Z"}]
    }

    local = %{
      version: 1,
      watchlist: ["MSFT"],
      notes: %{"AAPL" => %{content: "new local", updated_at: "2026-07-14T00:00:00Z"}},
      comparisons: [%{id: "core", symbols: ["AAPL", "MSFT"], updated_at: "2026-07-14T00:00:00Z"}]
    }

    assert {:ok, merged} = TickerWorkspaces.merge_workspaces(server, local)
    assert merged["watchlist"] == ["AAPL", "MSFT"]
    assert merged["notes"]["AAPL"]["content"] == "new local"

    assert [%{"content" => "old server"}] =
             Enum.map(merged["notes"]["AAPL"]["conflicts"], &Map.take(&1, ["content"]))

    assert hd(merged["comparisons"])["symbols"] == ["AAPL", "MSFT"]
  end
end
