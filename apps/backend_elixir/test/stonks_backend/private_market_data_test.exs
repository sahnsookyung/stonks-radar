defmodule StonksBackend.PrivateMarketDataTest do
  use ExUnit.Case, async: true

  alias StonksBackend.PrivateMarketData

  test "normalizes delayed daily candles without exposing provider credentials" do
    payload =
      PrivateMarketData.normalize_history(
        %{
          "t" => [1, 2],
          "o" => [10, 11],
          "h" => [12, 13],
          "l" => [9, 10],
          "c" => [11, 12],
          "v" => [100, 120]
        },
        "AAPL"
      )

    assert payload.status == "ready"
    assert payload.symbol == "AAPL"
    assert [%{open: 10, close: 11}, %{open: 11, close: 12}] = payload.points
    refute Map.has_key?(payload, :token)
  end

  test "normalizes and bounds option chains" do
    row = %{
      "optionSymbol" => "AAPL260117C00100000",
      "expiration" => "2026-01-17",
      "side" => "call",
      "strike" => 100,
      "bid" => 5,
      "ask" => 5.2,
      "volume" => 10,
      "openInterest" => 100,
      "iv" => 0.25,
      "delta" => 0.55,
      "underlyingPrice" => 105
    }

    payload =
      PrivateMarketData.normalize_options(%{"optionChain" => List.duplicate(row, 600)}, "AAPL")

    assert payload.status == "ready"
    assert length(payload.chain) == 500
    assert hd(payload.chain).implied_volatility == 0.25
    assert hd(payload.chain).delta == 0.55
  end
end
