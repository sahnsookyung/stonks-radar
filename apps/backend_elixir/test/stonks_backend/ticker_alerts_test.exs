defmodule StonksBackend.TickerAlertsTest do
  use ExUnit.Case, async: true

  alias StonksBackend.TickerAlerts

  test "validates every supported alert family and rejects malformed thresholds" do
    for type <- ~w(sec_filing news_spike short_interest_update) do
      assert {:ok, %{rule_type: ^type}} =
               TickerAlerts.validate_rule(%{
                 "symbol" => "AAPL",
                 "rule_type" => type,
                 "configuration" => %{}
               })
    end

    assert {:ok, rule} =
             TickerAlerts.validate_rule(%{
               "symbol" => "aapl",
               "rule_type" => "price_threshold",
               "configuration" => %{"operator" => "above", "value" => 200},
               "cooldown_seconds" => 7200,
               "email_enabled" => true
             })

    assert rule.symbol == "AAPL"
    assert rule.email_enabled

    assert {:error, :invalid_configuration} =
             TickerAlerts.validate_rule(%{
               "symbol" => "AAPL",
               "rule_type" => "rsi",
               "configuration" => %{}
             })
  end

  test "evaluates numeric, crossover, and ingestion-driven rules" do
    price = %{
      "rule_type" => "price_threshold",
      "configuration" => %{"operator" => "above", "value" => 100}
    }

    assert {:triggered, %{source_event_key: "price:1"}} =
             TickerAlerts.evaluate(price, %{"price" => 101, "source_event_key" => "price:1"})

    assert :not_triggered = TickerAlerts.evaluate(price, %{"price" => 99})

    macd = %{"rule_type" => "macd_cross", "configuration" => %{"direction" => "bullish"}}

    assert {:triggered, _} =
             TickerAlerts.evaluate(macd, %{
               "direction" => "bullish",
               "source_event_key" => "macd:1"
             })

    filing = %{"rule_type" => "sec_filing", "configuration" => %{}}

    assert {:triggered, _} =
             TickerAlerts.evaluate(filing, %{"matched" => true, "source_event_key" => "filing:1"})
  end

  test "hourly catch-up evaluates observations, advances watermarks, and counts only new events" do
    parent = self()

    rules = [
      %{
        "id" => "rule-1",
        "user_id" => "user-1",
        "symbol" => "AAPL",
        "rule_type" => "price_threshold",
        "configuration" => %{"operator" => "above", "value" => 100}
      }
    ]

    observation_fun = fn _rule ->
      [
        %{price: 101, source_at: ~U[2026-07-14 10:00:00Z], source_event_key: "price:1"},
        %{price: 99, source_at: ~U[2026-07-14 11:00:00Z], source_event_key: "price:2"}
      ]
    end

    create_event_fun = fn rule, key, source_at, reason, payload ->
      send(parent, {:event, rule["id"], key, source_at, reason, payload})
      {:ok, %{id: "event-1", deduplicated: false}}
    end

    watermark_fun = fn rule, source_at ->
      send(parent, {:watermark, rule["id"], source_at})
      :ok
    end

    assert %{
             status: "ready",
             mode: "hourly_watermark",
             rules_seen: 1,
             observations_seen: 2,
             events_created: 1,
             watermark_window: 99
           } =
             TickerAlerts.catch_up(%{"watermark_window" => 99},
               rules: rules,
               observation_fun: observation_fun,
               create_event_fun: create_event_fun,
               watermark_fun: watermark_fun
             )

    assert_receive {:event, "rule-1", "price:1", ~U[2026-07-14 10:00:00Z],
                    "price_threshold rule matched", %{price: 101}}

    assert_receive {:watermark, "rule-1", ~U[2026-07-14 11:00:00Z]}
  end
end
