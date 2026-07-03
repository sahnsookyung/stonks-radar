defmodule StonksBackend.NewsPipelineTest do
  use ExUnit.Case, async: true

  alias StonksBackend.News.Pipeline

  test "classify_document tags tracked tickers, regions, and topics from metadata-only text" do
    result =
      Pipeline.classify_document(%{
        "source_key" => "google_news_NVDA",
        "title" => "Nvidia faces China export-control pressure on AI accelerator supply chain",
        "snippet" => "Semiconductor restrictions could affect shipments into Beijing.",
        "url" => "https://example.com/story",
        "published_at" => "2026-06-30T12:00:00Z"
      })

    assert Enum.any?(result.entities, &(&1.symbol == "NVDA"))
    assert Enum.any?(result.regions, &(&1.key == "CHN"))
    assert Enum.any?(result.topics, &(&1.key == "semiconductors"))
    assert Enum.any?(result.topics, &(&1.key == "trade_policy"))
  end

  test "classify_document marks Rocket Lab acquisition headlines as direct ticker matches" do
    result =
      Pipeline.classify_document(%{
        "source_key" => "gdelt",
        "title" => "Rocket Lab announces acquisition of satellite communications provider",
        "snippet" => "RKLB said the deal expands its space systems backlog.",
        "url" => "https://example.com/rocket-lab-acquisition",
        "published_at" => "2026-07-01T12:00:00Z"
      })

    assert Enum.any?(result.entities, fn entity ->
             entity.symbol == "RKLB" and entity.relationship == "direct_subject" and
               entity.confidence >= 0.75
           end)
  end

  test "cluster_documents groups related event metadata by entity region topic and date" do
    documents = [
      %{
        "title" => "Nvidia China export controls pressure AI chips",
        "canonical_url" => "https://example.com/a",
        "published_at" => "2026-06-30T12:00:00Z",
        "event_type" => "geopolitical",
        "event_region" => "CHN",
        "entities" => [%{symbol: "NVDA"}]
      },
      %{
        "title" => "AI chips face China export control pressure at Nvidia",
        "canonical_url" => "https://example.com/b",
        "published_at" => "2026-06-30T14:30:00Z",
        "event_type" => "geopolitical",
        "event_region" => "CHN",
        "entities" => [%{symbol: "NVDA"}]
      }
    ]

    [cluster] = Pipeline.cluster_documents(documents)

    assert String.starts_with?(cluster.id, "news_")
    assert cluster.document_count == 2
    assert cluster.first_seen_at == "2026-06-30T12:00:00Z"
    assert cluster.last_seen_at == "2026-06-30T14:30:00Z"
  end

  test "score helpers keep weak discovery lower than official or regulated sources" do
    assert Pipeline.trust_score(["T0_OFFICIAL"]) > Pipeline.trust_score(["T4_WEAK_SIGNAL"])

    assert Pipeline.breaking_score(%{
             recency_score: 75,
             source_trust_score: 88,
             source_velocity_score: 40,
             novelty_score: 55,
             affected_entity_importance_score: 70,
             topic_severity_score: 70,
             cross_region_impact_score: 30
           }) in 0..100
  end
end
