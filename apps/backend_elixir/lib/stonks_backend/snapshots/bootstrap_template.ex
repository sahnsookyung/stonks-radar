defmodule StonksBackend.Snapshots.BootstrapTemplate do
  @moduledoc """
  Builds the schema-only catalog used for a first publication.

  This module contains route structure and unavailable-state copy, never
  observational market data. Runtime producers remain the only source for
  events, prices, filings, holdings, calendars, and metrics.
  """

  alias StonksBackend.{TrackedTickers, WatchedRegions}

  @locales ["en", "ko"]
  @topics [
    {"central_banks", "Central banks", "중앙은행"},
    {"drones", "Drones", "드론"},
    {"energy", "Energy", "에너지"},
    {"geopolitics", "Geopolitics", "지정학"},
    {"public_health", "Public health", "공중보건"},
    {"quantum", "Quantum", "양자"},
    {"semiconductors", "Semiconductors", "반도체"},
    {"space", "Space", "우주"}
  ]
  @sectors [
    {"big-tech", "Big Tech", "빅테크"},
    {"drones", "Drones", "드론"},
    {"oil-energy", "Oil and energy", "석유 및 에너지"},
    {"quantum", "Quantum", "양자"},
    {"semiconductors", "Semiconductors", "반도체"},
    {"space", "Space", "우주"}
  ]
  @scenarios [
    {"ai-infra-capex", "AI infrastructure capex", "AI 인프라 자본 지출"},
    {"asia-semiconductor-risk", "Asia semiconductor risk", "아시아 반도체 위험"},
    {"energy-supply-shock", "Energy supply shock", "에너지 공급 충격"}
  ]

  def manifest do
    %{
      "current_version" => 0,
      "generated_at" => DateTime.utc_now() |> DateTime.to_iso8601(),
      "locales" => @locales,
      "objects" =>
        descriptors()
        |> Map.new(fn descriptor ->
          locale_paths =
            Map.new(@locales, fn locale ->
              {locale, "public/v0/#{locale}/#{descriptor.suffix}"}
            end)

          {descriptor.object_key, locale_paths}
        end)
    }
  end

  def snapshot(object_key, locale, version, generated_at) do
    case Enum.find(descriptors(), &(&1.object_key == object_key)) do
      nil ->
        {:error, "Bootstrap snapshot object #{object_key} is not registered"}

      descriptor ->
        {:ok,
         %{
           "schema_version" => "1.0",
           "min_reader_version" => "1.0",
           "snapshot_version" => version,
           "locale" => locale,
           "generated_at" => iso8601(generated_at),
           "stale_after" => generated_at |> DateTime.add(12, :hour) |> iso8601(),
           "hard_expires_at" => generated_at |> DateTime.add(7, :day) |> iso8601(),
           "object_type" => descriptor.object_type,
           "object_key" => descriptor.object_key,
           "content_hash" => "sha256:bootstrap",
           "source_policy_versions" => [],
           "warnings" => [],
           "corrections" => [],
           "data" => data(descriptor, locale, generated_at)
         }}
    end
  end

  defp descriptors do
    core_descriptors() ++
      country_descriptors() ++
      news_region_descriptors() ++
      ticker_descriptors() ++
      reference_entity_descriptors() ++
      topic_descriptors() ++
      sector_descriptors() ++
      scenario_descriptors() ++
      [
        descriptor(
          "fund_portfolio_situational-awareness",
          "fund_portfolio",
          "funds/situational-awareness.json",
          %{
            key: "situational-awareness",
            name_en: "Situational Awareness",
            name_ko: "Situational Awareness"
          }
        )
      ]
  end

  defp core_descriptors do
    [
      descriptor("home", "home", "home.json"),
      descriptor("calendar_upcoming", "calendar_upcoming", "calendar/upcoming.json"),
      descriptor("correction_log", "correction_log", "corrections.json"),
      descriptor("map_events", "map_events", "map/events.json"),
      descriptor("news_index", "news_index", "news/index.json")
    ]
  end

  defp country_descriptors do
    Enum.map(WatchedRegions.all(), fn region ->
      key = to_string(region["key"])
      prefix = if region["type"] == "country", do: "country", else: "region"

      descriptor("#{prefix}_#{key}", "country_region", "countries/#{key}.json", %{
        key: key,
        region_type: region["type"] || "region",
        name_en: get_in(region, ["display_names", "en"]) || key,
        name_ko: get_in(region, ["display_names", "ko"]) || key
      })
    end)
  end

  defp news_region_descriptors do
    WatchedRegions.gather_news()
    |> Enum.map(fn region ->
      key = to_string(region["key"])

      descriptor("news_region_#{key}", "news_region", "news/regions/#{key}.json", %{
        key: key,
        name_en: get_in(region, ["display_names", "en"]) || key,
        name_ko: get_in(region, ["display_names", "ko"]) || key
      })
    end)
  end

  defp ticker_descriptors do
    TrackedTickers.ticker_entities()
    |> Enum.map(fn entity ->
      key = to_string(entity["entity_id"] || entity["symbol"])

      descriptor("news_ticker_#{key}", "news_ticker", "news/tickers/#{key}.json", %{
        key: key,
        symbol: entity["symbol"] || key,
        name_en: entity["name_en"] || entity["legal_name"] || key,
        name_ko: entity["name_ko"] || entity["name_en"] || key
      })
    end)
  end

  defp reference_entity_descriptors do
    TrackedTickers.entities()
    |> Enum.filter(&(&1["route_kind"] == "reference_entity"))
    |> Enum.map(fn entity ->
      key = to_string(entity["entity_id"] || entity["symbol"])

      descriptor("entity_#{key}", "reference_entity", "entities/#{key}.json", %{
        key: key,
        symbol: entity["symbol"] || key,
        display_symbol: entity["display_symbol"] || entity["symbol"] || key,
        name_en: entity["name_en"] || entity["legal_name"] || key,
        name_ko: entity["name_ko"] || entity["name_en"] || key,
        sector_keys: List.wrap(entity["sector_keys"]),
        tags: List.wrap(entity["tags"])
      })
    end)
  end

  defp topic_descriptors do
    Enum.map(@topics, fn {key, name_en, name_ko} ->
      descriptor("news_topic_#{key}", "news_topic", "news/topics/#{key}.json", %{
        key: key,
        name_en: name_en,
        name_ko: name_ko
      })
    end)
  end

  defp sector_descriptors do
    Enum.map(@sectors, fn {key, name_en, name_ko} ->
      descriptor("sector_#{key}", "sector_page", "sectors/#{key}.json", %{
        key: key,
        name_en: name_en,
        name_ko: name_ko
      })
    end)
  end

  defp scenario_descriptors do
    Enum.map(@scenarios, fn {key, name_en, name_ko} ->
      descriptor("scenario_basket_#{key}", "scenario_basket", "scenario-baskets/#{key}.json", %{
        key: key,
        name_en: name_en,
        name_ko: name_ko
      })
    end)
  end

  defp descriptor(object_key, object_type, suffix, metadata \\ %{}) do
    %{object_key: object_key, object_type: object_type, suffix: suffix, metadata: metadata}
  end

  defp data(%{object_type: "home"}, locale, generated_at) do
    %{
      "headline" => unavailable_title(locale),
      "summary" => unavailable_summary(locale),
      "generated_label" => iso8601(generated_at),
      "snapshot_health" => %{"status" => "degraded", "reason" => "content_unavailable"},
      "top_events" => [],
      "breaking_market_events" => [],
      "breaking_market_map" => empty_breaking_map(generated_at),
      "macro_tiles" => [],
      "alternative_signals" => [],
      "sector_tiles" => [],
      "calendar_preview" => [],
      "scenario_baskets" => []
    }
  end

  defp data(%{object_type: "calendar_upcoming"}, locale, _generated_at),
    do: %{"items" => [], "central_banks" => [], "methodology" => unavailable_summary(locale)}

  defp data(%{object_type: "correction_log"}, _locale, _generated_at), do: %{"entries" => []}

  defp data(%{object_type: "map_events"}, _locale, generated_at) do
    %{
      "events" => [],
      "breaking_market_events" => [],
      "breaking_market_map" => empty_breaking_map(generated_at),
      "filters" => %{
        "countries_regions" => [],
        "sectors" => [],
        "severities" => ["low", "medium", "high", "critical"],
        "event_types" => []
      }
    }
  end

  defp data(%{object_type: "news_index"}, _locale, generated_at),
    do: %{
      "generated_label" => iso8601(generated_at),
      "filters" => empty_news_filters(),
      "events" => []
    }

  defp data(%{object_type: "news_region", metadata: metadata}, locale, generated_at),
    do: %{
      "key" => metadata.key,
      "name" => localized_name(metadata, locale),
      "generated_label" => iso8601(generated_at),
      "regional_brief" => unavailable_summary(locale),
      "events" => []
    }

  defp data(%{object_type: "news_ticker", metadata: metadata}, locale, generated_at),
    do: %{
      "symbol" => metadata.symbol,
      "name" => localized_name(metadata, locale),
      "generated_label" => iso8601(generated_at),
      "summary" => unavailable_summary(locale),
      "events" => []
    }

  defp data(%{object_type: "news_topic", metadata: metadata}, locale, generated_at),
    do: %{
      "key" => metadata.key,
      "label" => localized_name(metadata, locale),
      "generated_label" => iso8601(generated_at),
      "topic_brief" => unavailable_summary(locale),
      "events" => []
    }

  defp data(%{object_type: "country_region", metadata: metadata}, locale, _generated_at),
    do: %{
      "key" => metadata.key,
      "name" => localized_name(metadata, locale),
      "type" => metadata.region_type,
      "overview" => unavailable_summary(locale),
      "source_strength" => "unavailable",
      "freshness" => "unsupported",
      "monitored_sectors" => [],
      "recent_events" => [],
      "calendar_items" => [],
      "indicators" => []
    }

  defp data(%{object_type: "sector_page", metadata: metadata}, locale, _generated_at),
    do: %{
      "key" => metadata.key,
      "name" => localized_name(metadata, locale),
      "overview" => unavailable_summary(locale),
      "tracked_entities" => [],
      "monitored_entities" => [],
      "monitored_instruments" => [],
      "country_region_exposure" => [],
      "recent_events" => [],
      "upcoming_calendar_items" => [],
      "ticker_calendar_items" => [],
      "sector_news" => [],
      "sector_short_facts" => [],
      "macro_geopolitical_drivers" => [],
      "reference_indicators" => [],
      "scenario_baskets" => [],
      "risks_and_caveats" => [unavailable_summary(locale)],
      "freshness" => "unsupported",
      "source_strength" => "unavailable"
    }

  defp data(%{object_type: "scenario_basket", metadata: metadata}, locale, generated_at),
    do: %{
      "key" => metadata.key,
      "name" => localized_name(metadata, locale),
      "thesis" => unavailable_summary(locale),
      "methodology" => unavailable_summary(locale),
      "tracker_sections" => [
        %{
          "key" => "live-coverage",
          "title" => if(locale == "ko", do: "실시간 데이터 범위", else: "Live data coverage"),
          "summary" => unavailable_summary(locale),
          "coverage_status" => "coverage_gap",
          "evidence_count" => 0,
          "last_observed_at" => iso8601(generated_at),
          "metric_rows" => [],
          "news_events" => [],
          "source_links" => []
        }
      ],
      "risk_summary" => unavailable_summary(locale),
      "freshness_timestamp" => iso8601(generated_at),
      "data_delay_warning" => unavailable_summary(locale),
      "disclaimer" => if(locale == "ko", do: "투자 조언이 아닙니다.", else: "Not investment advice."),
      "coverage_status" => "coverage_gap",
      "evidence_count" => 0,
      "last_observed_at" => iso8601(generated_at),
      "primary_source_url" => ""
    }

  defp data(%{object_type: "reference_entity", metadata: metadata}, locale, _generated_at),
    do: %{
      "entity" => %{
        "entity_id" => metadata.key,
        "symbol" => metadata.symbol,
        "display_symbol" => metadata.display_symbol,
        "name" => localized_name(metadata, locale),
        "route_kind" => "reference_entity",
        "route_key" => metadata.key,
        "sector_keys" => metadata.sector_keys,
        "tags" => metadata.tags,
        "source_strength" => "unavailable",
        "freshness" => "unsupported"
      },
      "summary" => unavailable_summary(locale),
      "source_links" => [],
      "latest_news" => [],
      "ticker_calendar_items" => [],
      "related_entities" => [],
      "caveats" => [unavailable_summary(locale)],
      "freshness" => "unsupported"
    }

  defp data(%{object_type: "fund_portfolio", metadata: metadata}, locale, generated_at),
    do: %{
      "fund_key" => metadata.key,
      "display_name" => localized_name(metadata, locale),
      "manager_name" => "",
      "fund_name" => localized_name(metadata, locale),
      "cik" => "",
      "generated_label" => iso8601(generated_at),
      "source_url" => "",
      "filing" => nil,
      "summary_metrics" => %{
        "total_reported_value_usd" => 0,
        "long_equity_value_usd" => 0,
        "option_notional_value_usd" => 0,
        "holding_count" => 0,
        "equity_holding_count" => 0,
        "option_holding_count" => 0
      },
      "holdings" => [],
      "top_equity_holdings" => [],
      "option_holdings" => [],
      "caveats" => [unavailable_summary(locale)],
      "freshness" => "unsupported",
      "source_strength" => "unavailable"
    }

  defp empty_breaking_map(generated_at) do
    %{
      "events" => [],
      "map_points" => [],
      "watched_regions" => [],
      "coverage_gaps" => [],
      "regional_briefs" => [],
      "shown_count" => 0,
      "total_count" => 0,
      "ranking_cutoff" => nil,
      "registry_version" => WatchedRegions.version(),
      "scoring_version" => "live",
      "thinning_version" => "live",
      "generated_at" => iso8601(generated_at)
    }
  end

  defp empty_news_filters,
    do: %{"regions" => [], "topics" => [], "tickers" => [], "trust_tiers" => []}

  defp localized_name(metadata, "ko"), do: metadata.name_ko || metadata.name_en || metadata.key
  defp localized_name(metadata, _locale), do: metadata.name_en || metadata.key

  defp unavailable_title("ko"), do: "실시간 시장 데이터를 사용할 수 없습니다"
  defp unavailable_title(_locale), do: "Live market data unavailable"

  defp unavailable_summary("ko"),
    do: "현재 출처 기반 관측값을 게시할 수 없습니다. 정적 예시 데이터는 표시하지 않습니다."

  defp unavailable_summary(_locale),
    do:
      "No current source-backed observations are available. Static example data is not displayed."

  defp iso8601(%DateTime{} = datetime), do: DateTime.to_iso8601(datetime)
end
