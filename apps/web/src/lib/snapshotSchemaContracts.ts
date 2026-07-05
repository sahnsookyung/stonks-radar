import type {
  BreakingMarketEvent,
  BreakingMarketMapData,
  HomeSnapshotData,
  MapEventsData,
  NewsEventListItem,
  NewsIndexSnapshotData,
  NewsMapPoint,
  SnapshotEnvelope,
  WatchedRegionCoverageGap
} from "@frw/shared-types";

type RequiredFieldKeys<T> = {
  [Key in keyof T]-?: Record<string, never> extends Pick<T, Key> ? never : Key;
}[keyof T];

type AssertRequiredFields<T, Fields extends RequiredFieldKeys<T>> = T;

type SnapshotEnvelopeContract = AssertRequiredFields<
  SnapshotEnvelope<unknown>,
  | "schema_version"
  | "snapshot_version"
  | "locale"
  | "generated_at"
  | "stale_after"
  | "hard_expires_at"
  | "object_type"
  | "object_key"
  | "content_hash"
  | "source_policy_versions"
  | "data"
  | "warnings"
  | "corrections"
>;

type HomeSnapshotContract = AssertRequiredFields<
  HomeSnapshotData,
  | "headline"
  | "summary"
  | "generated_label"
  | "snapshot_health"
  | "top_events"
  | "breaking_market_events"
  | "breaking_market_map"
  | "macro_tiles"
  | "alternative_signals"
  | "sector_tiles"
  | "calendar_preview"
  | "scenario_baskets"
>;

type MapEventsContract = AssertRequiredFields<
  MapEventsData,
  "events" | "breaking_market_events" | "breaking_market_map" | "filters"
>;

type BreakingMarketMapContract = AssertRequiredFields<
  BreakingMarketMapData,
  | "events"
  | "map_points"
  | "watched_regions"
  | "coverage_gaps"
  | "regional_briefs"
  | "shown_count"
  | "total_count"
  | "ranking_cutoff"
  | "registry_version"
  | "scoring_version"
  | "thinning_version"
  | "generated_at"
>;

type BreakingMarketEventContract = AssertRequiredFields<
  BreakingMarketEvent,
  | "event_id"
  | "title"
  | "summary"
  | "source_published_at"
  | "observed_at"
  | "verified_at"
  | "freshness_confidence"
  | "urgency_score"
  | "severity"
  | "trust_tier"
  | "discovery_only"
  | "review_state"
  | "citation_ids"
  | "retention_class"
  | "geo_points"
  | "geo_confidence"
  | "score_reason_codes"
  | "dedupe_key"
  | "label"
  | "tickers"
  | "regions"
  | "topics"
  | "source_count"
>;

type NewsMapPointContract = AssertRequiredFields<
  NewsMapPoint,
  | "point_id"
  | "event_id"
  | "event_ids"
  | "title"
  | "summary"
  | "area_id"
  | "area_key"
  | "area_label"
  | "relation"
  | "latitude"
  | "longitude"
  | "severity"
  | "urgency_score"
  | "source_published_at"
  | "observed_at"
  | "source_count"
  | "geo_confidence"
  | "area_priority"
  | "score_reason_codes"
>;

type CoverageGapContract = AssertRequiredFields<
  WatchedRegionCoverageGap,
  "region_key" | "label" | "reason" | "coverage_window_days" | "newest_source_published_at"
>;

type NewsIndexContract = AssertRequiredFields<
  NewsIndexSnapshotData,
  "generated_label" | "filters" | "events"
>;

type NewsEventListItemContract = AssertRequiredFields<
  NewsEventListItem,
  | "id"
  | "title"
  | "summary"
  | "event_type"
  | "item_kind"
  | "claim_level"
  | "evidence_match_status"
  | "first_seen_at"
  | "last_seen_at"
  | "published_at"
  | "freshness"
  | "severity"
  | "confidence"
  | "breaking_score"
  | "trust_score"
  | "source_count"
  | "tickers"
  | "regions"
  | "topics"
  | "market_direction"
  | "source_links"
>;

export type SnapshotSchemaContracts =
  | SnapshotEnvelopeContract
  | HomeSnapshotContract
  | MapEventsContract
  | BreakingMarketMapContract
  | BreakingMarketEventContract
  | NewsMapPointContract
  | CoverageGapContract
  | NewsIndexContract
  | NewsEventListItemContract;
