defmodule StonksBackend.News.Scoring do
  @moduledoc "Pure scoring helpers for source trust, breaking-news priority, and source diversity."

  def trust_score(trust_tiers) do
    scores =
      trust_tiers
      |> List.wrap()
      |> Enum.map(fn
        tier when is_binary(tier) ->
          cond do
            String.starts_with?(tier, "T0_") -> 95
            String.starts_with?(tier, "T1_") -> 88
            String.starts_with?(tier, "T2_") -> 74
            String.starts_with?(tier, "T3_") -> 62
            String.starts_with?(tier, "T4_") -> 38
            true -> 50
          end

        _ ->
          50
      end)

    if scores == [], do: 50, else: round(Enum.sum(scores) / length(scores))
  end

  def breaking_score(parts) do
    round(
      parts.recency_score * 0.2 +
        parts.source_trust_score * 0.24 +
        parts.source_velocity_score * 0.16 +
        parts.novelty_score * 0.12 +
        parts.affected_entity_importance_score * 0.12 +
        parts.topic_severity_score * 0.1 +
        parts.cross_region_impact_score * 0.06
    )
  end

  def independent_source_count(rows) do
    rows
    |> List.wrap()
    |> Enum.map(&source_identity/1)
    |> Enum.reject(&(&1 == ""))
    |> MapSet.new()
    |> MapSet.size()
  end

  defp source_identity(row) do
    metadata = metadata(row)

    [
      row["publisher"] || row[:publisher],
      metadata["gdelt_domain"] || metadata[:gdelt_domain],
      host(
        row["canonical_url"] || row[:canonical_url] || row["original_url"] || row[:original_url]
      ),
      metadata["source_key"] || metadata[:source_key] || row["source_key"] || row[:source_key],
      row["id"] || row[:id]
    ]
    |> Enum.find_value("", fn value ->
      value
      |> to_string()
      |> String.downcase()
      |> String.trim()
      |> case do
        "" -> nil
        text -> text
      end
    end)
  end

  defp metadata(row) do
    case row["metadata"] || row[:metadata] do
      metadata when is_map(metadata) -> metadata
      metadata when is_binary(metadata) -> Jason.decode!(metadata)
      _ -> %{}
    end
  rescue
    _ -> %{}
  end

  defp host(url) do
    uri = URI.parse(to_string(url || ""))
    uri.host |> to_string() |> String.downcase() |> String.replace_prefix("www.", "")
  rescue
    _ -> ""
  end
end
