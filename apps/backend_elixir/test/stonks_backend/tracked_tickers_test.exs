defmodule StonksBackend.TrackedTickersTest do
  use ExUnit.Case, async: true

  alias StonksBackend.TrackedTickers

  test "all configured tickers are filterable and source-backed" do
    tickers = TrackedTickers.ticker_entities()
    filter_options = TrackedTickers.ticker_filter_options()

    assert length(tickers) >= 19
    assert Enum.map(tickers, & &1["symbol"]) |> Enum.member?("RKLB")
    assert Enum.map(tickers, & &1["symbol"]) |> Enum.member?("005930.KS")

    assert Enum.map(filter_options, & &1["key"]) |> Enum.sort() ==
             tickers |> Enum.map(& &1["symbol"]) |> Enum.sort()

    assert TrackedTickers.source_issues() == []
  end

  test "ticker terms include symbols, companies, and aliases for news search" do
    terms = TrackedTickers.gdelt_terms()

    assert "RKLB" in terms
    assert ~s|"Rocket Lab"| in terms
    assert "NVDA" in terms
    assert ~s|"NVIDIA Corporation"| in terms
  end
end
