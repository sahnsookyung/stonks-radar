import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Clock3, Filter, MapPinned, RotateCcw } from "lucide-react";
import type { BreakingMarketEvent, NewsMapPoint, PublicEvent, Severity, WatchedRegionCoverage, WatchedRegionCoverageGap } from "@frw/shared-types";
import { EventMap } from "../components/EventMap";
import { EventList } from "../components/EventList";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

type MapTimeRange = "all" | "6h" | "24h" | "7d" | "custom";
type MinimumSourceCount = "all" | "2" | "3";
type MapControlState = Readonly<{
  severity: Severity | "all";
  sector: string;
  timeRange: MapTimeRange;
  customStartUtc: string;
  customEndUtc: string;
  minimumSourceCount: MinimumSourceCount;
  watchedRegionsOnly: boolean;
}>;
type EnrichedNewsMapPoint = NewsMapPoint & { trust_tier?: string };

const emptyEvents: PublicEvent[] = [];
const emptyMapPoints: NewsMapPoint[] = [];
const emptyWatchedRegions: WatchedRegionCoverage[] = [];
const emptyBreakingEvents: BreakingMarketEvent[] = [];
const emptyCoverageGaps: WatchedRegionCoverageGap[] = [];
const severityValues: Severity[] = ["low", "medium", "high", "critical"];

const mapTimeRangeOptions: Array<{ value: MapTimeRange; label: string }> = [
  { value: "all", label: "All UTC" },
  { value: "6h", label: "Last 6h UTC" },
  { value: "24h", label: "Last 24h UTC" },
  { value: "7d", label: "Last 7d UTC" },
  { value: "custom", label: "Custom UTC" }
];

export function MapPage() {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "map", locale],
    queryFn: () => snapshotQueries.map(locale)
  });
  const [initialControls] = useState(readMapControlState);
  const [severity, setSeverity] = useState<Severity | "all">(initialControls.severity);
  const [sector, setSector] = useState(initialControls.sector);
  const [timeRange, setTimeRange] = useState<MapTimeRange>(initialControls.timeRange);
  const [customStartUtc, setCustomStartUtc] = useState(initialControls.customStartUtc);
  const [customEndUtc, setCustomEndUtc] = useState(initialControls.customEndUtc);
  const [minimumSourceCount, setMinimumSourceCount] = useState<MinimumSourceCount>(initialControls.minimumSourceCount);
  const [watchedRegionsOnly, setWatchedRegionsOnly] = useState(initialControls.watchedRegionsOnly);
  const [selectedMapPointId, setSelectedMapPointId] = useState<string | null>(null);

  const snapshot = query.data;
  const data = snapshot?.data;
  const allEvents = data?.events ?? emptyEvents;
  const breakingMarketMap = data?.breaking_market_map;
  const breakingMarketEvents = data?.breaking_market_events ?? breakingMarketMap?.events ?? emptyBreakingEvents;
  const allMapPoints = breakingMarketMap?.map_points ?? emptyMapPoints;
  const watchedRegions = breakingMarketMap?.watched_regions ?? emptyWatchedRegions;
  const coverageGaps = breakingMarketMap?.coverage_gaps ?? emptyCoverageGaps;
  const timeAnchor = breakingMarketMap?.generated_at ?? snapshot?.generated_at ?? "";
  const timeBounds = useMemo(
    () => resolveMapTimeBounds(timeRange, customStartUtc, customEndUtc, timeAnchor),
    [customEndUtc, customStartUtc, timeAnchor, timeRange]
  );
  const watchedRegionKeys = useMemo(() => watchedRegionKeySet(watchedRegions), [watchedRegions]);
  const eventDetailsById = useMemo(
    () => new Map(breakingMarketEvents.map((event) => [event.event_id, event])),
    [breakingMarketEvents]
  );
  const events = useMemo(
    () =>
      allEvents.filter(
        (event) =>
          (severity === "all" || event.severity === severity) &&
          (sector === "all" || event.sector_keys.includes(sector)) &&
          withinUtcBounds(eventTimestampMs(event), timeBounds)
      ),
    [allEvents, sector, severity, timeBounds]
  );
  const mapPoints = useMemo(
    () =>
      allMapPoints.filter(
        (point) =>
          (severity === "all" || point.severity === severity) &&
          withinUtcBounds(mapPointTimestampMs(point), timeBounds) &&
          (minimumSourceCount === "all" || point.source_count >= Number(minimumSourceCount)) &&
          (!watchedRegionsOnly || mapPointInWatchedRegion(point, watchedRegionKeys))
      ),
    [allMapPoints, minimumSourceCount, severity, timeBounds, watchedRegionKeys, watchedRegionsOnly]
  );
  const mapPointsForMap = useMemo(
    () => enrichMapPoints(mapPoints, eventDetailsById),
    [eventDetailsById, mapPoints]
  );
  const eventsForMap = allMapPoints.length > 0 ? [] : events;
  const activeFilterCount = [
    severity !== "all",
    sector !== "all",
    timeRange !== "all",
    minimumSourceCount !== "all",
    watchedRegionsOnly
  ].filter(Boolean).length;
  const hasCustomRange = timeRange === "custom" && (customStartUtc !== "" || customEndUtc !== "");
  const hasFilteredMapPointMiss = allMapPoints.length > 0 && mapPoints.length === 0;
  const hasFilteredEventMiss = allEvents.length > 0 && events.length === 0;
  const hasCustomUtcRangeMiss = hasCustomRange && hasFilteredMapPointMiss && hasFilteredEventMiss;

  useEffect(() => {
    if (!selectedMapPointId) return;
    const selectedPointVisible = mapPoints.some(
      (point) => point.event_id === selectedMapPointId || point.point_id === selectedMapPointId
    );
    if (!selectedPointVisible) setSelectedMapPointId(null);
  }, [mapPoints, selectedMapPointId]);

  useEffect(() => {
    const applyUrlControls = () => {
      const controls = readMapControlState();
      setSeverity(controls.severity);
      setSector(controls.sector);
      setTimeRange(controls.timeRange);
      setCustomStartUtc(controls.customStartUtc);
      setCustomEndUtc(controls.customEndUtc);
      setMinimumSourceCount(controls.minimumSourceCount);
      setWatchedRegionsOnly(controls.watchedRegionsOnly);
    };
    globalThis.window.addEventListener("popstate", applyUrlControls);
    return () => globalThis.window.removeEventListener("popstate", applyUrlControls);
  }, []);

  useEffect(() => {
    if (!data) return;
    if (severity !== "all" && !data.filters.severities.includes(severity)) {
      setSeverity("all");
    }
    if (sector !== "all" && !data.filters.sectors.includes(sector)) {
      setSector("all");
    }
  }, [data, sector, severity]);

  useEffect(() => {
    writeMapControlState({
      severity,
      sector,
      timeRange,
      customStartUtc,
      customEndUtc,
      minimumSourceCount,
      watchedRegionsOnly
    });
  }, [customEndUtc, customStartUtc, minimumSourceCount, sector, severity, timeRange, watchedRegionsOnly]);

  const resetFilters = () => {
    setSeverity("all");
    setSector("all");
    setTimeRange("all");
    setCustomStartUtc("");
    setCustomEndUtc("");
    setMinimumSourceCount("all");
    setWatchedRegionsOnly(false);
  };

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !snapshot || !data) return <ErrorState error={query.error} />;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={snapshot} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <MapPinned className="h-4 w-4" />
            MapLibre event layer
          </div>
          <h1 className="mt-2 text-3xl font-bold sm:text-4xl">Global Intelligence Map</h1>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="badge border-line bg-panelAlt text-muted">{mapPoints.length} / {allMapPoints.length} map points</span>
          <span className="badge border-line bg-panelAlt text-muted">{events.length} / {allEvents.length} events</span>
          <span className="badge border-line bg-panelAlt text-muted">
            {activeFilterCount ? `${activeFilterCount} filters` : "All filters"}
          </span>
        </div>
      </section>

      <section className="panel grid min-w-0 gap-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-h-11 items-center gap-2 text-sm font-semibold text-ink">
            <Filter className="h-4 w-4 text-accent" />
            Map controls
          </div>
          {activeFilterCount > 0 ? (
            <button type="button" className="secondary-action min-h-11 px-3 py-1.5 text-xs" onClick={resetFilters}>
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
          ) : null}
        </div>

        <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
            Severity
            <select
              className="input-control w-full"
              value={severity}
              onChange={(event) => setSeverity(event.target.value as Severity | "all")}
            >
              <option value="all">All severity</option>
              {data.filters.severities.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
            Sector
            <select
              className="input-control w-full"
              value={sector}
              onChange={(event) => setSector(event.target.value)}
            >
              <option value="all">All sectors</option>
              {data.filters.sectors.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
            Time
            <select
              className="input-control w-full"
              value={timeRange}
              onChange={(event) => setTimeRange(event.target.value as MapTimeRange)}
            >
              {mapTimeRangeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
            Sources
            <select
              className="input-control w-full"
              value={minimumSourceCount}
              onChange={(event) => setMinimumSourceCount(event.target.value as MinimumSourceCount)}
            >
              <option value="all">All sources</option>
              <option value="2">2+ sources</option>
              <option value="3">3+ sources</option>
            </select>
          </label>
          <label className="focus-within:ring-focus inline-flex min-h-11 items-center gap-2 self-end rounded-md border border-line bg-panelAlt px-3 text-sm font-semibold text-ink">
            <input
              type="checkbox"
              className="h-11 w-11 shrink-0 accent-cyan"
              checked={watchedRegionsOnly}
              onChange={(event) => setWatchedRegionsOnly(event.target.checked)}
            />
            Watched regions
          </label>
        </div>

        {timeRange === "custom" ? (
          <div className="grid min-w-0 gap-3 sm:grid-cols-2">
            <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
              Start UTC
              <input
                type="datetime-local"
                className="input-control w-full"
                value={customStartUtc}
                onChange={(event) => setCustomStartUtc(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
              End UTC
              <input
                type="datetime-local"
                className="input-control w-full"
                value={customEndUtc}
                onChange={(event) => setCustomEndUtc(event.target.value)}
              />
            </label>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs font-semibold text-muted">
          <Clock3 className="h-4 w-4 text-accent" />
          <span>{mapTimeRangeLabel(timeRange, timeBounds)}</span>
        </div>
        <CoverageGapSummary coverageGaps={coverageGaps} />
      </section>
      {hasCustomUtcRangeMiss ? (
        <MapEmptyState title="No matches in this custom UTC range" body="Widen the UTC start or end time, or reset the range to show all source publication times." />
      ) : null}
      {!hasCustomUtcRangeMiss && hasFilteredMapPointMiss ? (
        <MapEmptyState title="No map points match these controls" body="Try all severities, all sources, or include regions outside the watched list." />
      ) : null}
      <EventMap
        events={eventsForMap}
        mapPoints={mapPointsForMap}
        watchedRegions={watchedRegions}
        selectedMapPointId={selectedMapPointId}
        onMapPointSelect={setSelectedMapPointId}
        heightClass="h-[clamp(420px,60svh,640px)] md:h-[720px] xl:h-[calc(100vh-260px)]"
        loadStrategy="immediate"
      />
      {hasFilteredEventMiss ? (
        <MapEmptyState title="No event list items match these controls" body="The map may still show source-linked news points whose event metadata is independent of the public event list." />
      ) : (
        <EventList events={events} />
      )}
    </div>
  );
}

function CoverageGapSummary({ coverageGaps }: Readonly<{ coverageGaps: WatchedRegionCoverageGap[] }>) {
  if (coverageGaps.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-wrap gap-2 text-xs font-semibold text-muted">
      <span className="badge border-line bg-panelAlt text-muted">{coverageGaps.length} coverage gaps</span>
      {coverageGaps.slice(0, 3).map((gap) => (
        <span key={`${gap.region_key}-${gap.reason}`} className="badge border-line bg-panelAlt text-muted">
          {gap.label}: {gap.reason.replaceAll("_", " ")}
        </span>
      ))}
    </div>
  );
}

function MapEmptyState({ title, body }: Readonly<{ title: string; body: string }>) {
  return (
    <section className="panel border-dashed p-4 text-sm leading-6 text-muted" aria-live="polite">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      <p className="mt-1">{body}</p>
    </section>
  );
}

type UtcBounds = Readonly<{ fromMs: number | null; toMs: number | null }>;

function resolveMapTimeBounds(
  timeRange: MapTimeRange,
  customStartUtc: string,
  customEndUtc: string,
  anchorTimestamp: string
): UtcBounds {
  if (timeRange === "all") return { fromMs: null, toMs: null };
  if (timeRange === "custom") {
    return normalizeUtcBounds(utcInputMs(customStartUtc), utcInputMs(customEndUtc));
  }
  const anchorMs = timestampMs(anchorTimestamp) ?? Date.now();
  const rangeHours = timeRange === "6h" ? 6 : timeRange === "24h" ? 24 : 24 * 7;
  return { fromMs: anchorMs - rangeHours * 60 * 60 * 1000, toMs: anchorMs };
}

function normalizeUtcBounds(fromMs: number | null, toMs: number | null): UtcBounds {
  if (fromMs !== null && toMs !== null && fromMs > toMs) {
    return { fromMs: toMs, toMs: fromMs };
  }
  return { fromMs, toMs };
}

function mapTimeRangeLabel(timeRange: MapTimeRange, bounds: UtcBounds) {
  if (timeRange === "all") return "All source times";
  if (timeRange !== "custom") {
    const option = mapTimeRangeOptions.find((item) => item.value === timeRange);
    return option?.label ?? "UTC range";
  }
  if (bounds.fromMs === null && bounds.toMs === null) return "Custom UTC range";
  const from = bounds.fromMs === null ? "open" : new Date(bounds.fromMs).toISOString().slice(0, 16).replace("T", " ");
  const to = bounds.toMs === null ? "open" : new Date(bounds.toMs).toISOString().slice(0, 16).replace("T", " ");
  return `${from} UTC to ${to} UTC`;
}

function withinUtcBounds(timestamp: number | null, bounds: UtcBounds) {
  if (bounds.fromMs === null && bounds.toMs === null) return true;
  if (timestamp === null) return false;
  return (bounds.fromMs === null || timestamp >= bounds.fromMs) && (bounds.toMs === null || timestamp <= bounds.toMs);
}

function eventTimestampMs(event: PublicEvent) {
  return timestampMs(event.published_at) ?? timestampMs(event.occurred_at);
}

function mapPointTimestampMs(point: NewsMapPoint) {
  return timestampMs(point.source_published_at) ?? timestampMs(point.observed_at);
}

function timestampMs(value: string | null | undefined) {
  if (!value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

function utcInputMs(value: string) {
  if (!value) return null;
  const utcValue = value.endsWith("Z") ? value : `${value}${value.length === 16 ? ":00" : ""}Z`;
  return timestampMs(utcValue);
}

function watchedRegionKeySet(watchedRegions: WatchedRegionCoverage[]) {
  return new Set(watchedRegions.filter((region) => region.render_on_map).map((region) => region.key));
}

function mapPointInWatchedRegion(point: NewsMapPoint, watchedRegionKeys: ReadonlySet<string>) {
  return watchedRegionKeys.has(point.area_key) || watchedRegionKeys.has(point.area_id);
}

function enrichMapPoints(
  mapPoints: NewsMapPoint[],
  eventDetailsById: ReadonlyMap<string, BreakingMarketEvent>
): EnrichedNewsMapPoint[] {
  return mapPoints.map((point) => {
    const event = eventDetailsById.get(point.event_id) ?? point.event_ids.map((id) => eventDetailsById.get(id)).find(Boolean);
    if (!event) return point;
    return {
      ...point,
      trust_tier: event.trust_tier,
      geo_confidence: Math.max(point.geo_confidence, event.geo_confidence),
      score_reason_codes: Array.from(new Set([...point.score_reason_codes, ...event.score_reason_codes]))
    };
  });
}

function readMapControlState(): MapControlState {
  const params = new URLSearchParams(globalThis.window.location.search);
  const from = normalizeUtcInputValue(params.get("from"));
  const to = normalizeUtcInputValue(params.get("to"));
  return {
    severity: normalizeSeverityParam(params.get("severity")),
    sector: normalizeTextParam(params.get("sector")),
    timeRange: normalizeTimeRangeParam(params.get("time"), from, to),
    customStartUtc: from,
    customEndUtc: to,
    minimumSourceCount: normalizeSourceCountParam(params.get("sources")),
    watchedRegionsOnly: normalizeBooleanParam(params.get("watched"))
  };
}

function writeMapControlState(state: MapControlState) {
  const params = new URLSearchParams(globalThis.window.location.search);
  for (const key of ["severity", "sector", "time", "from", "to", "sources", "watched"]) {
    params.delete(key);
  }
  if (state.severity !== "all") params.set("severity", state.severity);
  if (state.sector !== "all") params.set("sector", state.sector);
  if (state.timeRange !== "all") params.set("time", state.timeRange);
  if (state.timeRange === "custom") {
    if (state.customStartUtc) params.set("from", state.customStartUtc);
    if (state.customEndUtc) params.set("to", state.customEndUtc);
  }
  if (state.minimumSourceCount !== "all") params.set("sources", state.minimumSourceCount);
  if (state.watchedRegionsOnly) params.set("watched", "1");
  const search = params.toString();
  const nextUrl = `${globalThis.window.location.pathname}${search ? `?${search}` : ""}${globalThis.window.location.hash}`;
  const currentUrl = `${globalThis.window.location.pathname}${globalThis.window.location.search}${globalThis.window.location.hash}`;
  if (nextUrl !== currentUrl) {
    globalThis.window.history.replaceState(null, "", nextUrl);
  }
}

function normalizeSeverityParam(value: string | null): Severity | "all" {
  return severityValues.includes(value as Severity) ? (value as Severity) : "all";
}

function normalizeSourceCountParam(value: string | null): MinimumSourceCount {
  return value === "2" || value === "3" ? value : "all";
}

function normalizeTimeRangeParam(value: string | null, from: string, to: string): MapTimeRange {
  if (value === "6h" || value === "24h" || value === "7d" || value === "custom") return value;
  if (from || to) return "custom";
  return "all";
}

function normalizeTextParam(value: string | null) {
  const normalized = (value ?? "").trim();
  if (!normalized || normalized.length > 80) return "all";
  return /^[A-Za-z0-9._:-]+$/.test(normalized) ? normalized : "all";
}

function normalizeUtcInputValue(value: string | null) {
  if (!value) return "";
  const normalized = value.trim().slice(0, 16);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(normalized)) return "";
  return utcInputMs(normalized) === null ? "" : normalized;
}

function normalizeBooleanParam(value: string | null) {
  return value === "1" || value === "true";
}
