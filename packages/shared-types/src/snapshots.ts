export type Locale = "en" | "ko";

export type Freshness = "fresh" | "watch" | "stale" | "unsupported";
export type Severity = "low" | "medium" | "high" | "critical";

export interface SnapshotEnvelope<T> {
  schema_version: string;
  snapshot_version: number;
  locale: Locale;
  generated_at: string;
  stale_after: string;
  hard_expires_at: string;
  object_type: string;
  object_key: string;
  content_hash: string;
  source_policy_versions: SourcePolicyVersion[];
  data: T;
  warnings: SnapshotWarning[];
  corrections: CorrectionEntry[];
}

export interface SourcePolicyVersion {
  source_key: string;
  policy_version: number;
}

export interface SnapshotWarning {
  code: string;
  message: string;
  severity: "info" | "warning" | "critical";
}

export interface CorrectionEntry {
  id: string;
  title: string;
  status: "correction" | "retraction" | "clarification";
  published_at: string;
  summary: string;
}

export interface ManifestObjectPaths {
  [locale: string]: string;
}

export interface SnapshotManifest {
  current_version: number;
  generated_at: string;
  locales: Locale[];
  objects: Record<string, ManifestObjectPaths>;
}

export interface PublicEvent {
  id: string;
  title: string;
  summary: string;
  why_it_matters: string;
  occurred_at: string;
  published_at: string;
  country_region_keys: string[];
  sector_keys: string[];
  event_type: string;
  severity: Severity;
  confidence: number;
  source_strength: string;
  freshness: Freshness;
  evidence_count: number;
  latitude: number;
  longitude: number;
  affected_objects: string[];
  source_links: SourceLink[];
  correction_status: string;
}

export interface SourceLink {
  label: string;
  url: string;
  source_key: string;
  policy_version: number;
}

export type NewsTrustTier =
  | "T0_OFFICIAL"
  | "T1_REGULATED_FILING"
  | "T2_REPUTABLE_MEDIA"
  | "T3_REVIEWED_PUBLIC_SOURCE"
  | "T4_WEAK_SIGNAL"
  | "T5_UNREVIEWED"
  | "T6_BLOCKED";

export type NewsMarketDirection = "bullish" | "bearish" | "mixed" | "unclear";
export type BreakingMarketLabel = "breaking" | "developing" | "latest" | "stale" | "unmappable";
export type NewsMapPointRelation = "event_location" | "chokepoint" | "affected_market" | "source_region";

export type NewsRegionRelation =
  | "source_region"
  | "event_region"
  | "company_region"
  | "affected_region"
  | "market_region"
  | "mentioned_region";

export interface NewsFacet {
  key: string;
  label: string;
  count: number;
}

export interface NewsTickerRef {
  symbol: string;
  name: string;
  exchange?: string;
  relationship: "direct_subject" | "affected_company" | "competitor" | "supplier" | "customer" | "mentioned_only";
  confidence: number;
}

export interface NewsRegionRef {
  key: string;
  name: string;
  relation: NewsRegionRelation;
  confidence: number;
}

export interface NewsTopicRef {
  key: string;
  label: string;
  confidence: number;
}

export interface NewsSourceRef extends SourceLink {
  title: string;
  published_at: string;
  trust_tier: NewsTrustTier;
  is_primary: boolean;
}

export interface NewsEventListItem {
  id: string;
  title: string;
  summary: string;
  event_type: string;
  first_seen_at: string;
  last_seen_at: string;
  published_at: string;
  source_published_at?: string;
  observed_at?: string;
  freshness: Freshness;
  severity: Severity;
  confidence: number;
  breaking_score: number;
  trust_score: number;
  source_count: number;
  tickers: NewsTickerRef[];
  regions: NewsRegionRef[];
  topics: NewsTopicRef[];
  market_direction: NewsMarketDirection;
  source_links: NewsSourceRef[];
}

export interface NewsMapPoint {
  point_id: string;
  event_id: string;
  event_ids: string[];
  title: string;
  summary: string;
  area_id: string;
  area_key: string;
  area_label: string;
  relation: NewsMapPointRelation;
  latitude: number;
  longitude: number;
  severity: Severity;
  urgency_score: number;
  source_published_at: string;
  observed_at: string;
  source_url?: string;
  source_count: number;
  geo_confidence: number;
  area_priority: number;
  score_reason_codes: string[];
}

export interface BreakingMarketEvent {
  event_id: string;
  title: string;
  summary: string;
  source_url?: string;
  source_published_at: string;
  observed_at: string;
  verified_at: string;
  freshness_confidence: number;
  urgency_score: number;
  severity: Severity;
  trust_tier: NewsTrustTier;
  discovery_only: boolean;
  review_state: "approved" | "reviewed" | "published";
  citation_ids: string[];
  retention_class: "metadata_only" | "summary_only" | "full_text_reviewed";
  geo_points: NewsMapPoint[];
  geo_confidence: number;
  score_reason_codes: string[];
  dedupe_key: string;
  label: BreakingMarketLabel;
  tickers: NewsTickerRef[];
  regions: NewsRegionRef[];
  topics: NewsTopicRef[];
  source_count: number;
}

export interface BreakingMarketMapData {
  events: BreakingMarketEvent[];
  map_points: NewsMapPoint[];
  shown_count: number;
  total_count: number;
  ranking_cutoff: number | null;
  registry_version: number;
  scoring_version: string;
  thinning_version: string;
  generated_at: string;
}

export interface NewsIndexSnapshotData {
  generated_label: string;
  filters: {
    regions: NewsFacet[];
    topics: NewsFacet[];
    tickers: NewsFacet[];
    trust_tiers: NewsFacet[];
  };
  events: NewsEventListItem[];
}

export interface NewsEventSnapshotData extends NewsEventListItem {
  one_sentence_summary: string;
  what_happened: string[];
  why_it_matters: string[];
  ticker_implications: {
    symbol: string;
    implication: string;
    direction: NewsMarketDirection;
    confidence: "low" | "medium" | "high";
  }[];
  known_facts: string[];
  uncertainties: string[];
  conflicting_reports: string[];
  market_relevance: {
    direction: NewsMarketDirection;
    confidence: "low" | "medium" | "high";
    reasoning: string;
  };
  related_events: NewsEventListItem[];
  methodology: string;
  disclaimer: string;
}

export interface NewsTickerSnapshotData {
  symbol: string;
  name: string;
  generated_label: string;
  summary: string;
  events: NewsEventListItem[];
}

export interface NewsRegionSnapshotData {
  key: string;
  name: string;
  generated_label: string;
  regional_brief: string;
  events: NewsEventListItem[];
}

export interface NewsTopicSnapshotData {
  key: string;
  label: string;
  generated_label: string;
  topic_brief: string;
  events: NewsEventListItem[];
}

export interface HomeSnapshotData {
  headline: string;
  summary: string;
  generated_label: string;
  snapshot_health: {
    status: Freshness;
    age_minutes: number;
    stale_after: string;
    backend_dependency: "none_for_public_pages";
  };
  top_events: PublicEvent[];
  breaking_market_events: BreakingMarketEvent[];
  breaking_market_map: BreakingMarketMapData;
  macro_tiles: MetricTile[];
  alternative_signals: AlternativeSignalLane[];
  sector_tiles: SectorTile[];
  calendar_preview: CalendarItem[];
  scenario_baskets: ScenarioBasketSummary[];
}

export interface MetricTile {
  key: string;
  label: string;
  value: string;
  unit?: string;
  source: string;
  source_url?: string;
  freshness: Freshness;
  delay_label: string;
  updated_at: string;
  coverage_status?: "active" | "coverage_gap";
  refresh_seconds?: number;
  refresh_delta?: number;
  refresh_delta_percent?: number;
  next_event?: MetricTileEvent;
  points?: { date: string; value: number }[];
}

export interface MetricTileEvent {
  title: string;
  date: string;
  timezone: string;
  source: string;
}

export interface AlternativeSignalLane {
  key: string;
  title: string;
  summary: string;
  value: string;
  cadence: string;
  source: string;
  source_url?: string;
  freshness: Freshness;
  severity: Severity;
  refresh_seconds: number;
  items: AlternativeSignalItem[];
}

export interface AlternativeSignalItem {
  key: string;
  label: string;
  value: string;
  detail: string;
  source: string;
  source_url?: string;
  freshness: Freshness;
  severity: Severity;
  updated_at: string;
  symbols?: string[];
  dataset?: string;
  as_of_date?: string;
  provider_observation_key?: string;
}

export type EntityRouteKind = "ticker" | "reference_entity" | "unsupported";
export type SectorCatalystType =
  | "earnings"
  | "filing"
  | "investor_event"
  | "launch_window"
  | "mission_window"
  | "contract_milestone"
  | "company_event"
  | "lockup_warrant"
  | "source_review";
export type ShortFactType = "short_interest" | "short_volume" | "short_research";

export interface TrackedEntityRef {
  entity_id: string;
  symbol: string;
  display_symbol: string;
  name: string;
  route_kind: EntityRouteKind;
  route_key: string;
  sector_keys: string[];
  tags: string[];
  source_strength: string;
  freshness: Freshness;
}

export interface TickerCalendarItem {
  id: string;
  entity_id: string;
  symbol: string;
  title: string;
  catalyst_type: SectorCatalystType;
  scheduled_at: string | null;
  scheduled_local_date: string;
  timezone: string;
  source: string;
  source_url: string;
  freshness: Freshness;
  confidence: number;
}

export interface ShortFact {
  id: string;
  entity_id: string;
  symbol: string;
  fact_type: ShortFactType;
  dataset: string;
  as_of_date: string;
  retrieved_at: string;
  last_attempted_at: string;
  attempt_status: string;
  value: number | null;
  unit: string;
  source: string;
  source_url: string;
  provider_observation_key: string;
  freshness: Freshness;
  caveat: string;
}

export interface SectorTile {
  key: string;
  name: string;
  summary: string;
  source_strength: string;
  freshness: Freshness;
  monitored_count: number;
  event_count: number;
}

export interface CalendarItem {
  id: string;
  title: string;
  country_region_key: string;
  release_type: string;
  scheduled_at: string | null;
  scheduled_local_date: string;
  timezone: string;
  time_precision: "date_only" | "time_confirmed" | "time_estimated";
  status: string;
  expectation_type: string;
  expectation_value: string | null;
  actual_value: string | null;
  previous_value: string | null;
  surprise: string | null;
  source: string;
  source_url: string;
  freshness: Freshness;
}

export type ScenarioCoverageStatus = "active" | "partial" | "coverage_gap";

export interface ScenarioBasketSummary {
  key: string;
  name: string;
  thesis: string;
  risk_summary: string;
  freshness: Freshness;
  coverage_status: ScenarioCoverageStatus;
  evidence_count: number;
  last_observed_at: string;
  primary_source_url: string;
  external_tracker_url?: string;
}

export interface ScenarioTrackerMetricRow {
  key: string;
  label: string;
  value: string;
  detail: string;
  source: string;
  source_url: string;
  freshness: Freshness;
  as_of_date: string;
  coverage_status: ScenarioCoverageStatus;
}

export interface ScenarioTrackerSection {
  key: string;
  title: string;
  summary: string;
  coverage_status: ScenarioCoverageStatus;
  evidence_count: number;
  last_observed_at: string;
  metric_rows: ScenarioTrackerMetricRow[];
  news_events: NewsEventListItem[];
  source_links: SourceLink[];
}

export interface MapEventsData {
  events: PublicEvent[];
  breaking_market_events: BreakingMarketEvent[];
  breaking_market_map: BreakingMarketMapData;
  filters: {
    countries_regions: string[];
    sectors: string[];
    severities: Severity[];
    event_types: string[];
  };
}

export interface CalendarSnapshotData {
  items: CalendarItem[];
  central_banks: CalendarItem[];
  methodology: string;
}

export interface CountryRegionSnapshotData {
  key: string;
  name: string;
  type: "country" | "region";
  overview: string;
  source_strength: string;
  freshness: Freshness;
  monitored_sectors: SectorTile[];
  recent_events: PublicEvent[];
  calendar_items: CalendarItem[];
  indicators: MetricTile[];
}

export interface SectorSnapshotData {
  key: string;
  name: string;
  overview: string;
  tracked_entities: TrackedEntityRef[];
  monitored_entities: string[];
  monitored_instruments: string[];
  country_region_exposure: string[];
  recent_events: PublicEvent[];
  upcoming_calendar_items: CalendarItem[];
  ticker_calendar_items: TickerCalendarItem[];
  sector_news: NewsEventListItem[];
  sector_short_facts: ShortFact[];
  macro_geopolitical_drivers: string[];
  reference_indicators: MetricTile[];
  scenario_baskets: ScenarioBasketSummary[];
  risks_and_caveats: string[];
  freshness: Freshness;
  source_strength: string;
}

export interface ReferenceEntitySnapshotData {
  entity: TrackedEntityRef;
  summary: string;
  source_links: SourceLink[];
  latest_news: NewsEventListItem[];
  ticker_calendar_items: TickerCalendarItem[];
  related_entities: TrackedEntityRef[];
  caveats: string[];
  freshness: Freshness;
}

export type FundHoldingKind = "stock" | "call" | "put" | "other";

export interface FundPortfolioHolding {
  id: string;
  symbol: string | null;
  issuer_name: string;
  title_of_class: string;
  cusip: string;
  value_usd: number;
  shares: number | null;
  share_type: string | null;
  put_call: "Call" | "Put" | null;
  holding_kind: FundHoldingKind;
  portfolio_weight: number;
  source_url: string;
  source_lineage: string;
}

export interface FundPortfolioFiling {
  source: "SEC_EDGAR_13F";
  form_type: string;
  accession_number: string;
  report_date: string;
  filed_at: string;
  primary_document_url: string;
  information_table_url: string;
}

export interface FundPortfolioSnapshotData {
  fund_key: string;
  display_name: string;
  manager_name: string;
  fund_name: string;
  cik: string;
  generated_label: string;
  source_url: string;
  filing: FundPortfolioFiling | null;
  summary_metrics: {
    total_reported_value_usd: number;
    long_equity_value_usd: number;
    option_notional_value_usd: number;
    holding_count: number;
    equity_holding_count: number;
    option_holding_count: number;
  };
  holdings: FundPortfolioHolding[];
  top_equity_holdings: FundPortfolioHolding[];
  option_holdings: FundPortfolioHolding[];
  caveats: string[];
  freshness: Freshness;
  source_strength: string;
}

export interface ScenarioBasketSnapshotData {
  key: string;
  name: string;
  thesis: string;
  methodology: string;
  tracker_sections: ScenarioTrackerSection[];
  risk_summary: string;
  freshness_timestamp: string;
  data_delay_warning: string;
  disclaimer: string;
  coverage_status: ScenarioCoverageStatus;
  evidence_count: number;
  last_observed_at: string;
  primary_source_url: string;
  external_tracker_url?: string;
}

export interface SourceStatusSnapshotData {
  snapshot_age_minutes: number;
  degraded_mode: boolean;
  backend_required_for_public_pages: false;
  providers: {
    provider_key: string;
    provider_type: string;
    status: string;
    mode: string;
    last_verified_at: string | null;
    warning: string | null;
  }[];
  operations: {
    disk_watermark: string;
    snapshot_storage_status: string;
    backup_status: string;
    restore_drill_at: string | null;
  };
}
