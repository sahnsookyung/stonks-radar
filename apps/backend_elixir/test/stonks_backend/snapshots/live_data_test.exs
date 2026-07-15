defmodule StonksBackend.Snapshots.LiveDataTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Snapshots.LiveData

  test "removes seeded home observations and marks the result unavailable" do
    snapshot = %{
      "object_type" => "home",
      "locale" => "en",
      "generated_at" => "2026-07-15T00:00:00Z",
      "warnings" => [],
      "data" => %{
        "headline" => "Seed headline",
        "summary" => "Seed summary",
        "top_events" => [%{"id" => "seed"}],
        "breaking_market_events" => [%{"event_id" => "seed"}],
        "breaking_market_map" => %{"events" => [%{}], "map_points" => [%{}]},
        "macro_tiles" => [
          %{
            "key" => "nasdaq",
            "label" => "Nasdaq",
            "value" => "20,000",
            "freshness" => "fresh",
            "delay_label" => "live",
            "updated_at" => "2026-07-01T00:00:00Z"
          }
        ],
        "alternative_signals" => [
          %{
            "key" => "breaking_market_news",
            "value" => "45 headlines",
            "summary" => "Seed signal",
            "freshness" => "fresh",
            "items" => [%{"key" => "seed"}]
          }
        ],
        "sector_tiles" => [],
        "calendar_preview" => [%{"id" => "seed"}],
        "scenario_baskets" => []
      }
    }

    stripped = LiveData.strip_seed_payload(snapshot)
    assert stripped["data"]["top_events"] == []
    assert stripped["data"]["breaking_market_events"] == []
    assert stripped["data"]["calendar_preview"] == []
    assert hd(stripped["data"]["macro_tiles"])["value"] == "unavailable"
    assert hd(stripped["data"]["alternative_signals"])["items"] == []

    annotated = LiveData.annotate_availability(stripped)

    assert [%{"code" => "live_data_unavailable", "severity" => "warning"}] =
             annotated["warnings"]
  end

  test "removes the unavailable warning after a real materializer supplies data" do
    snapshot = %{
      "object_type" => "news_index",
      "locale" => "en",
      "warnings" => [%{"code" => "live_data_unavailable", "message" => "old"}],
      "data" => %{"events" => [%{"id" => "db-event"}]}
    }

    assert LiveData.annotate_availability(snapshot)["warnings"] == []
  end
end
