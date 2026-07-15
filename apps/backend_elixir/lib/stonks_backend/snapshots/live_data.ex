defmodule StonksBackend.Snapshots.LiveData do
  @moduledoc """
  Removes observational seed content before a snapshot is materialized.

  The checked-in snapshot tree is a compatibility template only. Taxonomy,
  labels, and source descriptions may be retained, but prices, events, dates,
  counts, filings, holdings, and other observations must come from runtime
  producers. When a producer has no data, the public snapshot stays visibly
  unavailable instead of recycling a previous observation.
  """

  @unavailable_warning %{
    "code" => "live_data_unavailable",
    "message" => "No current source-backed data is available for this view.",
    "severity" => "warning"
  }

  def strip_seed_payload(%{"data" => data, "object_type" => object_type} = snapshot)
      when is_map(data) do
    snapshot
    |> Map.put("source_policy_versions", [])
    |> Map.put("warnings", [])
    |> Map.put("data", strip_data(object_type, data, snapshot))
  end

  def strip_seed_payload(snapshot), do: snapshot

  def annotate_availability(%{"data" => data, "object_type" => object_type} = snapshot)
      when is_map(data) do
    if live_data_available?(object_type, data) do
      remove_unavailable_warning(snapshot)
    else
      Map.update(snapshot, "warnings", [@unavailable_warning], fn warnings ->
        warnings
        |> List.wrap()
        |> Enum.reject(&(&1["code"] == @unavailable_warning["code"]))
        |> Kernel.++([localized_warning(snapshot)])
      end)
    end
  end

  def annotate_availability(snapshot), do: snapshot

  defp strip_data("home", data, snapshot) do
    data
    |> Map.put("headline", unavailable_title(snapshot))
    |> Map.put("summary", unavailable_summary(snapshot))
    |> Map.put("top_events", [])
    |> Map.put("breaking_market_events", [])
    |> Map.update(
      "breaking_market_map",
      empty_breaking_map(snapshot),
      &strip_breaking_map(&1, snapshot)
    )
    |> Map.update(
      "macro_tiles",
      [],
      &Enum.map(List.wrap(&1), fn tile -> strip_metric_tile(tile, snapshot) end)
    )
    |> Map.update(
      "alternative_signals",
      [],
      &Enum.map(List.wrap(&1), fn lane -> strip_signal_lane(lane, snapshot) end)
    )
    |> Map.update("sector_tiles", [], fn tiles ->
      Enum.map(List.wrap(tiles), &strip_sector_tile/1)
    end)
    |> Map.put("calendar_preview", [])
    |> Map.update(
      "scenario_baskets",
      [],
      fn summaries ->
        Enum.map(List.wrap(summaries), &strip_scenario_summary(&1, snapshot))
      end
    )
  end

  defp strip_data("map_events", data, snapshot) do
    data
    |> Map.put("events", [])
    |> Map.put("breaking_market_events", [])
    |> Map.update(
      "breaking_market_map",
      empty_breaking_map(snapshot),
      &strip_breaking_map(&1, snapshot)
    )
    |> Map.update("filters", empty_filters(), fn filters ->
      filters
      |> ensure_map()
      |> Map.put("countries_regions", [])
      |> Map.put("sectors", [])
      |> Map.put("event_types", [])
      |> Map.put_new("severities", ["low", "medium", "high", "critical"])
    end)
  end

  defp strip_data("calendar_upcoming", data, _snapshot) do
    data
    |> Map.put("items", [])
    |> Map.put("central_banks", [])
  end

  defp strip_data("correction_log", data, _snapshot), do: Map.put(data, "entries", [])

  defp strip_data("news_index", data, snapshot) do
    data
    |> Map.put("events", [])
    |> Map.put("generated_label", snapshot["generated_at"] || "")
    |> Map.update("filters", empty_news_filters(), fn _ -> empty_news_filters() end)
  end

  defp strip_data(object_type, data, snapshot)
       when object_type in ["news_region", "news_ticker", "news_topic"] do
    data
    |> Map.put("events", [])
    |> Map.put("generated_label", snapshot["generated_at"] || "")
    |> maybe_strip_brief("regional_brief", snapshot)
    |> maybe_strip_brief("topic_brief", snapshot)
  end

  defp strip_data("country_region", data, snapshot) do
    data
    |> Map.put("overview", unavailable_summary(snapshot))
    |> Map.put("freshness", "unsupported")
    |> Map.put("source_strength", "unavailable")
    |> Map.put("monitored_sectors", [])
    |> Map.put("recent_events", [])
    |> Map.put("calendar_items", [])
    |> Map.put("indicators", [])
  end

  defp strip_data("sector_page", data, snapshot) do
    data
    |> Map.put("overview", unavailable_summary(snapshot))
    |> Map.put("freshness", "unsupported")
    |> Map.put("source_strength", "unavailable")
    |> Map.put("recent_events", [])
    |> Map.put("upcoming_calendar_items", [])
    |> Map.put("ticker_calendar_items", [])
    |> Map.put("sector_news", [])
    |> Map.put("sector_short_facts", [])
    |> Map.put("macro_geopolitical_drivers", [])
    |> Map.put("reference_indicators", [])
    |> Map.put("scenario_baskets", [])
  end

  defp strip_data("scenario_basket", data, snapshot) do
    data
    |> Map.put("coverage_status", "coverage_gap")
    |> Map.put("evidence_count", 0)
    |> Map.put("last_observed_at", snapshot["generated_at"] || "")
    |> Map.put("freshness_timestamp", snapshot["generated_at"] || "")
    |> Map.put("data_delay_warning", unavailable_summary(snapshot))
    |> Map.update("tracker_sections", [], fn sections ->
      Enum.map(List.wrap(sections), &strip_tracker_section(&1, snapshot))
    end)
  end

  defp strip_data("reference_entity", data, _snapshot) do
    data
    |> Map.put("freshness", "unsupported")
    |> Map.put("latest_news", [])
    |> Map.put("ticker_calendar_items", [])
  end

  defp strip_data("fund_portfolio", data, snapshot) do
    data
    |> Map.put("filing", nil)
    |> Map.put("holdings", [])
    |> Map.put("top_equity_holdings", [])
    |> Map.put("option_holdings", [])
    |> Map.put("summary_metrics", empty_fund_metrics())
    |> Map.put("generated_label", snapshot["generated_at"] || "")
    |> Map.put("freshness", "unsupported")
    |> Map.put("source_strength", "unavailable")
  end

  defp strip_data(_object_type, data, _snapshot), do: data

  defp strip_metric_tile(tile, snapshot) when is_map(tile) do
    tile
    |> Map.put("value", "unavailable")
    |> Map.put("freshness", "unsupported")
    |> Map.put("delay_label", unavailable_short(snapshot))
    |> Map.put("updated_at", snapshot["generated_at"] || "")
    |> Map.put("coverage_status", "coverage_gap")
    |> Map.put("points", [])
    |> Map.drop(["refresh_delta", "refresh_delta_percent", "next_event"])
  end

  defp strip_metric_tile(_tile, _snapshot), do: %{}

  defp strip_signal_lane(lane, snapshot) when is_map(lane) do
    lane
    |> Map.put("value", "unavailable")
    |> Map.put("summary", unavailable_summary(snapshot))
    |> Map.put("freshness", "unsupported")
    |> Map.put("items", [])
  end

  defp strip_signal_lane(_lane, _snapshot), do: %{}

  defp strip_sector_tile(tile) when is_map(tile) do
    tile
    |> Map.put("summary", "")
    |> Map.put("freshness", "unsupported")
    |> Map.put("monitored_count", 0)
    |> Map.put("event_count", 0)
  end

  defp strip_sector_tile(_tile), do: %{}

  defp strip_scenario_summary(summary, snapshot) when is_map(summary) do
    summary
    |> Map.put("freshness", "unsupported")
    |> Map.put("coverage_status", "coverage_gap")
    |> Map.put("evidence_count", 0)
    |> Map.put("last_observed_at", snapshot["generated_at"] || "")
  end

  defp strip_scenario_summary(_summary, _snapshot), do: %{}

  defp strip_tracker_section(section, snapshot) when is_map(section) do
    section
    |> Map.put("summary", unavailable_summary(snapshot))
    |> Map.put("coverage_status", "coverage_gap")
    |> Map.put("evidence_count", 0)
    |> Map.put("last_observed_at", snapshot["generated_at"] || "")
    |> Map.put("metric_rows", [])
    |> Map.put("news_events", [])
    |> Map.put("source_links", [])
  end

  defp strip_tracker_section(_section, _snapshot), do: %{}

  defp strip_breaking_map(map, snapshot) do
    map
    |> ensure_map()
    |> Map.put("events", [])
    |> Map.put("map_points", [])
    |> Map.put("watched_regions", [])
    |> Map.put("coverage_gaps", [])
    |> Map.put("regional_briefs", [])
    |> Map.put("shown_count", 0)
    |> Map.put("total_count", 0)
    |> Map.put("ranking_cutoff", nil)
    |> Map.put("generated_at", snapshot["generated_at"] || "")
  end

  defp maybe_strip_brief(data, key, snapshot) do
    if Map.has_key?(data, key) do
      Map.put(data, key, unavailable_summary(snapshot))
    else
      data
    end
  end

  defp live_data_available?("correction_log", _data), do: true

  defp live_data_available?("home", data) do
    populated?(data["top_events"]) or populated?(data["breaking_market_events"]) or
      populated?(data["calendar_preview"]) or live_metric?(data["macro_tiles"]) or
      live_signal?(data["alternative_signals"])
  end

  defp live_data_available?("map_events", data) do
    populated?(data["events"]) or populated?(data["breaking_market_events"]) or
      populated?(get_in(data, ["breaking_market_map", "map_points"]))
  end

  defp live_data_available?("calendar_upcoming", data),
    do: populated?(data["items"]) or populated?(data["central_banks"])

  defp live_data_available?(object_type, data)
       when object_type in ["news_index", "news_region", "news_ticker", "news_topic"],
       do: populated?(data["events"])

  defp live_data_available?("country_region", data),
    do:
      populated?(data["recent_events"]) or populated?(data["calendar_items"]) or
        live_metric?(data["indicators"])

  defp live_data_available?("sector_page", data),
    do:
      populated?(data["recent_events"]) or populated?(data["sector_news"]) or
        populated?(data["ticker_calendar_items"]) or populated?(data["sector_short_facts"]) or
        live_metric?(data["reference_indicators"])

  defp live_data_available?("scenario_basket", data), do: to_int(data["evidence_count"]) > 0

  defp live_data_available?("reference_entity", data),
    do: populated?(data["latest_news"]) or populated?(data["ticker_calendar_items"])

  defp live_data_available?("fund_portfolio", data),
    do: is_map(data["filing"]) or populated?(data["holdings"])

  defp live_data_available?("news_event", data), do: populated?(data["source_links"])
  defp live_data_available?(_object_type, _data), do: false

  defp live_metric?(items) do
    Enum.any?(List.wrap(items), fn
      %{"freshness" => freshness, "value" => value} ->
        freshness != "unsupported" and value not in [nil, "", "unavailable"]

      _ ->
        false
    end)
  end

  defp live_signal?(items) do
    Enum.any?(List.wrap(items), fn
      %{"items" => observations} -> populated?(observations)
      _ -> false
    end)
  end

  defp populated?(items), do: is_list(items) and items != []

  defp remove_unavailable_warning(snapshot) do
    Map.update(snapshot, "warnings", [], fn warnings ->
      Enum.reject(List.wrap(warnings), &(&1["code"] == @unavailable_warning["code"]))
    end)
  end

  defp localized_warning(%{"locale" => "ko"}) do
    %{@unavailable_warning | "message" => "이 화면에 사용할 수 있는 최신 출처 기반 데이터가 없습니다."}
  end

  defp localized_warning(_snapshot), do: @unavailable_warning

  defp unavailable_title(%{"locale" => "ko"}), do: "실시간 시장 데이터를 사용할 수 없습니다"
  defp unavailable_title(_snapshot), do: "Live market data unavailable"

  defp unavailable_summary(%{"locale" => "ko"}),
    do: "현재 출처 기반 관측값을 게시할 수 없습니다. 정적 예시 데이터는 표시하지 않습니다."

  defp unavailable_summary(_snapshot),
    do:
      "No current source-backed observations are available. Static example data is not displayed."

  defp unavailable_short(%{"locale" => "ko"}), do: "최신 데이터 없음"
  defp unavailable_short(_snapshot), do: "No current data"

  defp empty_breaking_map(snapshot) do
    %{
      "events" => [],
      "map_points" => [],
      "watched_regions" => [],
      "coverage_gaps" => [],
      "regional_briefs" => [],
      "shown_count" => 0,
      "total_count" => 0,
      "ranking_cutoff" => nil,
      "registry_version" => 1,
      "scoring_version" => "live",
      "thinning_version" => "live",
      "generated_at" => snapshot["generated_at"] || ""
    }
  end

  defp empty_filters do
    %{
      "countries_regions" => [],
      "sectors" => [],
      "severities" => ["low", "medium", "high", "critical"],
      "event_types" => []
    }
  end

  defp empty_news_filters,
    do: %{"regions" => [], "topics" => [], "tickers" => [], "trust_tiers" => []}

  defp empty_fund_metrics do
    %{
      "total_reported_value_usd" => 0,
      "long_equity_value_usd" => 0,
      "option_notional_value_usd" => 0,
      "holding_count" => 0,
      "equity_holding_count" => 0,
      "option_holding_count" => 0
    }
  end

  defp ensure_map(value) when is_map(value), do: value
  defp ensure_map(_value), do: %{}

  defp to_int(value) when is_integer(value), do: value

  defp to_int(value) do
    case Integer.parse(to_string(value)) do
      {integer, _} -> integer
      _ -> 0
    end
  end
end
