defmodule StonksBackend.News.PublicProjectionTest do
  use ExUnit.Case, async: true

  alias StonksBackend.News.PublicProjection

  test "projects stored cluster rows without static fallback content" do
    now = ~U[2026-07-15 00:00:00Z]

    row = %{
      "id" => "live-event-1",
      "canonical_title" => "Live source-linked event",
      "event_type" => "filing",
      "first_seen_at" => ~U[2026-07-14 20:00:00Z],
      "last_seen_at" => ~U[2026-07-14 23:00:00Z],
      "published_at" => ~U[2026-07-14 22:30:00Z],
      "earliest_source_published_at" => ~U[2026-07-14 22:30:00Z],
      "latest_source_published_at" => ~U[2026-07-14 22:30:00Z],
      "severity" => "high",
      "confidence" => Decimal.new("0.82"),
      "breaking_score" => 78,
      "trust_score" => 88,
      "source_count" => 2,
      "review_state" => "reviewed",
      "summary_json" => %{"summary" => "Reviewed public metadata summary."},
      "tickers" => [
        %{"symbol" => "AAPL", "relationship" => "direct_subject", "confidence" => 0.9}
      ],
      "regions" => [
        %{"key" => "USA", "relation" => "event_region", "confidence" => 0.8}
      ],
      "topics" => [%{"key" => "filings", "confidence" => 0.95}],
      "source_links" => [
        %{
          "label" => "SEC",
          "url" => "https://www.sec.gov/example",
          "source_key" => "sec",
          "policy_version" => 1,
          "title" => "Official filing",
          "published_at" => ~U[2026-07-14 22:30:00Z],
          "trust_tier" => "T0_OFFICIAL",
          "is_primary" => true
        }
      ]
    }

    query_fun = fn sql, [locale, limit] ->
      assert sql =~ "from news_event_cluster"
      assert sql =~ "d.source_published_at is not null"
      assert locale == "en"
      assert limit == 500
      [row]
    end

    assert [event] = PublicProjection.events("en", query_fun: query_fun, now: now)
    assert event["id"] == "live-event-1"
    assert event["summary"] == "Reviewed public metadata summary."
    assert event["claim_level"] == "reviewed"
    assert event["review_state"] == "reviewed"
    assert event["freshness"] == "fresh"
    assert event["source_links"] |> hd() |> Map.get("url") == "https://www.sec.gov/example"
  end

  test "returns no events when the authoritative query fails" do
    assert PublicProjection.events("en", query_fun: fn _sql, _params -> raise "database down" end) ==
             []
  end

  test "filters projected lists by their stored relationships" do
    row = %{
      "id" => "live-event-2",
      "canonical_title" => "Regional ticker event",
      "event_type" => "company_event",
      "first_seen_at" => ~U[2026-07-14 20:00:00Z],
      "last_seen_at" => ~U[2026-07-14 21:00:00Z],
      "published_at" => ~U[2026-07-14 21:00:00Z],
      "earliest_source_published_at" => ~U[2026-07-14 21:00:00Z],
      "latest_source_published_at" => ~U[2026-07-14 21:00:00Z],
      "severity" => "medium",
      "confidence" => 0.7,
      "breaking_score" => 60,
      "trust_score" => 70,
      "source_count" => 1,
      "review_state" => "candidate",
      "summary_json" => %{},
      "tickers" => [
        %{"symbol" => "AAPL", "relationship" => "direct_subject", "confidence" => 0.8}
      ],
      "regions" => [
        %{"key" => "USA", "relation" => "event_region", "confidence" => 0.8}
      ],
      "topics" => [%{"key" => "earnings", "confidence" => 0.8}],
      "source_links" => [
        %{
          "label" => "Source",
          "url" => "https://example.com/event",
          "source_key" => "example",
          "policy_version" => 1,
          "title" => "Event",
          "published_at" => ~U[2026-07-14 21:00:00Z],
          "trust_tier" => "T4_WEAK_SIGNAL",
          "is_primary" => true
        }
      ]
    }

    opts = [
      query_fun: fn _sql, _params -> [row] end,
      now: ~U[2026-07-15 00:00:00Z]
    ]

    assert [%{"id" => "live-event-2"}] =
             PublicProjection.project_list(%{"key" => "USA"}, "news_region", "en", opts)[
               "events"
             ]

    assert [] ==
             PublicProjection.project_list(%{"key" => "JPN"}, "news_region", "en", opts)[
               "events"
             ]
  end

  test "rejects clusters without an authoritative source publication time" do
    row = %{
      "id" => "undated-page",
      "canonical_title" => "Evergreen product page",
      "last_seen_at" => ~U[2026-07-14 23:59:00Z],
      "published_at" => ~U[2026-07-14 23:59:00Z],
      "latest_source_published_at" => nil,
      "source_links" => [
        %{
          "url" => "https://example.com/product",
          "published_at" => nil
        }
      ]
    }

    assert PublicProjection.events("en",
             query_fun: fn _sql, _params -> [row] end,
             now: ~U[2026-07-15 00:00:00Z]
           ) == []
  end

  test "rejects future and navigation rows, deduplicates titles, and counts public links" do
    now = ~U[2026-07-15 00:00:00Z]
    published_at = DateTime.add(now, -60, :second)

    rows = [
      projection_row("kept", "Company reports material market update", published_at, "kept"),
      projection_row(
        "duplicate",
        "Company reports material market update",
        published_at,
        "duplicate"
      ),
      projection_row(
        "future",
        "Company reports future market update",
        DateTime.add(now, 10, :minute),
        "future"
      ),
      projection_row("navigation", "Log In", published_at, "navigation")
    ]

    assert [%{"id" => "kept", "review_state" => "candidate", "source_count" => 1}] =
             PublicProjection.events("en", query_fun: fn _sql, _params -> rows end, now: now)
  end

  defp projection_row(id, title, published_at, url_suffix) do
    %{
      "id" => id,
      "canonical_title" => title,
      "event_type" => "company_event",
      "earliest_source_published_at" => published_at,
      "latest_source_published_at" => published_at,
      "severity" => "medium",
      "confidence" => 0.7,
      "breaking_score" => 50,
      "trust_score" => 70,
      "source_count" => 99,
      "review_state" => "candidate",
      "summary_json" => %{},
      "tickers" => [],
      "regions" => [],
      "topics" => [],
      "source_links" => [
        %{
          "label" => "Source",
          "url" => "https://example.com/#{url_suffix}",
          "source_key" => "example",
          "policy_version" => 1,
          "title" => title,
          "published_at" => published_at,
          "trust_tier" => "T2_REPUTABLE_MEDIA",
          "is_primary" => true
        }
      ]
    }
  end
end
