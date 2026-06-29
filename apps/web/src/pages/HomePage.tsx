import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowRight,
  CalendarDays,
  DatabaseZap,
  ExternalLink,
  MapPinned,
  MapPin,
  Radar
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalLane, BreakingMarketEvent, BreakingMarketMapData, CalendarItem, ScenarioBasketSummary } from "@frw/shared-types";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "../components/Badge";
import { EventMap } from "../components/EventMap";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { MarketPulseTickerBar, sortMarketTiles } from "../components/MarketPulse";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

const dashboardSignalKeys = new Set(["breaking_market_news"]);

export function HomePage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const [selectedBreakingEventId, setSelectedBreakingEventId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["snapshot", "home", locale],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const snapshot = query.data;
  const data = snapshot.data;
  const marketTiles = sortMarketTiles(data.macro_tiles);
  const calendarPreview = sortCalendarItems(data.calendar_preview);
  const dashboardSignals = data.alternative_signals.filter((lane) => dashboardSignalKeys.has(lane.key));
  const breakingMarketMap = data.breaking_market_map;
  const breakingEvents = data.breaking_market_events ?? breakingMarketMap?.events ?? [];
  const newsMapPoints = breakingMarketMap?.map_points ?? [];
  const scenarioBaskets = data.scenario_baskets.filter((basket) => basket.evidence_count > 0);

  return (
    <div className="grid min-w-0 gap-7">
      <MarketPulseTickerBar tiles={marketTiles} />
      <SnapshotBanner snapshot={snapshot} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <DatabaseZap className="h-4 w-4" />
            {t("publicSnapshot")}
          </div>
          <h1 className="mt-3 max-w-4xl break-words text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">{data.headline}</h1>
          <p className="mt-3 max-w-4xl break-words text-base leading-7 text-muted md:text-lg md:leading-8">{data.summary}</p>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2.5">
          <FreshnessBadge value={data.snapshot_health.status} />
          <SourceBadge label={t("snapshotFirst")} />
          <SourceBadge label={t("sourceLinkedData")} />
        </div>
      </section>

      <section className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(340px,0.7fr)] 2xl:grid-cols-[minmax(0,1.7fr)_minmax(400px,0.62fr)]">
        <div className="min-w-0" aria-labelledby="event-geography-title">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 id="event-geography-title" className="flex items-center gap-2 text-sm font-semibold text-accent">
                <MapPinned className="h-4 w-4" />
                {t("eventGeography")}
              </h2>
              <Link to="/$locale/map" params={{ locale }} className="secondary-action min-h-11 py-2">
                {t("map")}
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <EventMap
              events={data.top_events}
              mapPoints={newsMapPoints}
              selectedMapPointId={selectedBreakingEventId}
              onMapPointSelect={setSelectedBreakingEventId}
              heightClass="h-[clamp(330px,48svh,500px)] md:h-[560px] xl:h-[610px]"
              footer={t("eventMapFooter")}
              loadStrategy="idle-visible"
            />
        </div>

        <BreakingMarketWatch
          events={breakingEvents}
          mapData={breakingMarketMap}
          fallbackLanes={dashboardSignals}
          selectedEventId={selectedBreakingEventId}
          onSelectEvent={setSelectedBreakingEventId}
        />
      </section>

      <section className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1fr)]">
        <div className="panel p-5">
          <div className="flex items-center gap-2 font-semibold">
            <CalendarDays className="h-4 w-4" />
            {t("calendar")}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {calendarPreview.slice(0, 6).map((item) => (
              <div key={item.id} className="rounded-md border border-line bg-panelAlt px-4 py-3">
                <div className="text-sm font-semibold leading-5">{item.title}</div>
                <div className="mt-1.5 text-xs leading-5 text-muted">
                  {item.scheduled_local_date} · {item.source} · {calendarExpectationLabel(item.expectation_type, locale)}
                </div>
                <a href={item.source_url} target={item.source_url.startsWith("http") ? "_blank" : undefined} rel="noreferrer" className="focus-ring mt-2 inline-flex min-h-8 items-center gap-1 rounded text-xs font-semibold text-accent hover:text-accentSoft">
                  {t("source")}
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              </div>
            ))}
          </div>
          <Link to="/$locale/calendar" params={{ locale }} className="primary-action mt-4">
            {t("calendar")}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        <ScenarioTrackerCards baskets={scenarioBaskets} locale={locale} />
      </section>
    </div>
  );
}

function sortCalendarItems(items: CalendarItem[]) {
  return [...items].sort((left, right) => calendarSortKey(left).localeCompare(calendarSortKey(right)));
}

function calendarSortKey(item: CalendarItem) {
  const dateText = item.scheduled_local_date || item.scheduled_at?.slice(0, 10) || "9999-12-31";
  const timeText = item.scheduled_at?.includes("T") ? item.scheduled_at.slice(11, 19) : "23:59:59";
  return `${dateText}T${timeText}:${item.id}`;
}

function calendarExpectationLabel(expectationType: string, locale: "en" | "ko") {
  if (expectationType === "official_projection") return locale === "ko" ? "공식 전망" : "official projections";
  if (expectationType === "official_calendar") return locale === "ko" ? "공식 일정" : "official calendar";
  if (expectationType === "manual_estimate") return locale === "ko" ? "수동 추정" : "manual estimate";
  if (expectationType === "provider_calendar") return locale === "ko" ? "제공사 일정" : "provider calendar";
  if (expectationType === "manual_watch") return locale === "ko" ? "수동 감시" : "manual watch";
  return locale === "ko" ? "감시" : "watch";
}

function ScenarioTrackerCards({ baskets, locale }: Readonly<{ baskets: ScenarioBasketSummary[]; locale: "en" | "ko" }>) {
  const { t } = useTranslation();
  if (baskets.length === 0) return null;
  return (
    <div className="min-w-0">
      <h2 className="mb-3 text-xl font-bold">{t("scenarioTrackers")}</h2>
      <div className="grid gap-3">
        {baskets.map((basket) => (
          <article key={basket.key} className="panel p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="safe-text font-semibold">{basket.name}</h3>
                <p className="mt-1 text-xs font-semibold uppercase text-accent">
                  {basket.evidence_count} {locale === "ko" ? "근거 행" : "evidence rows"}
                </p>
              </div>
              <FreshnessBadge value={basket.freshness} />
            </div>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">{basket.thesis}</p>
            <p className="safe-text mt-2 text-xs leading-5 text-muted">{basket.risk_summary}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <SourceBadge label={basket.coverage_status.replace("_", " ")} />
              <SourceBadge label={`${locale === "ko" ? "관측" : "observed"} ${basket.last_observed_at.slice(0, 10)}`} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                to="/$locale/scenario-baskets/$basketKey"
                params={{ locale, basketKey: basket.key }}
                className="primary-action"
              >
                {t("openScenarioEvidence")}
                <ArrowRight className="h-4 w-4" />
              </Link>
              {basket.external_tracker_url ? (
                <a href={basket.external_tracker_url} target="_blank" rel="noreferrer" className="secondary-action">
                  {t("openExternalTracker")}
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function BreakingMarketWatch({
  events,
  mapData,
  fallbackLanes,
  selectedEventId,
  onSelectEvent
}: Readonly<{
  events: BreakingMarketEvent[];
  mapData?: BreakingMarketMapData;
  fallbackLanes: AlternativeSignalLane[];
  selectedEventId: string | null;
  onSelectEvent: (eventId: string) => void;
}>) {
  const { t } = useTranslation();
  if (events.length === 0) return <DashboardSignalRadar lanes={fallbackLanes} />;
  return (
    <section className="min-w-0" aria-labelledby="breaking-news-title">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="breaking-news-title" className="flex items-center gap-2 text-sm font-semibold text-warning">
            <Radar className="h-4 w-4" />
            {t("breakingMarketWatch", { defaultValue: "Breaking Market Watch" })}
          </h2>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-muted">
            {t("breakingMarketWatchSummary", {
              defaultValue: "Fresh source-linked geopolitical market events projected onto the map."
            })}
          </p>
        </div>
        {mapData ? (
          <div className="rounded-md border border-line bg-panelAlt px-3 py-2 text-xs font-semibold text-muted">
            {mapData.shown_count}/{mapData.total_count} mapped
          </div>
        ) : null}
      </div>
      <div className="grid gap-3 xl:max-h-[610px] xl:overflow-y-auto xl:pr-1">
        {events.slice(0, 10).map((event) => (
          <BreakingMarketCard
            key={event.event_id}
            event={event}
            selected={event.event_id === selectedEventId}
            onSelect={() => onSelectEvent(event.event_id)}
          />
        ))}
      </div>
      {mapData?.ranking_cutoff !== null && mapData?.ranking_cutoff !== undefined ? (
        <p className="mt-3 text-xs leading-5 text-muted">
          {t("breakingMarketWatchCapped", {
            defaultValue: "Map is thinned by urgency after the displayed cutoff."
          })}
        </p>
      ) : null}
    </section>
  );
}

function BreakingMarketCard({
  event,
  selected,
  onSelect
}: Readonly<{
  event: BreakingMarketEvent;
  selected: boolean;
  onSelect: () => void;
}>) {
  const locale = useLocale();
  const areaLabels = Array.from(new Set(event.geo_points.map((point) => point.area_label))).slice(0, 3);
  return (
    <article className={`panel min-w-0 p-4 ${selected ? "border-accent shadow-[0_0_0_1px_rgba(83,216,245,0.35)]" : ""}`}>
      <button
        type="button"
        className="focus-ring block w-full rounded-md text-left"
        onClick={onSelect}
        aria-pressed={selected}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] font-bold uppercase text-warning">
              {event.label}
            </span>
            <span className="text-xs font-semibold text-muted">{formatEventAge(event.source_published_at, locale)}</span>
          </div>
          <SeverityBadge value={event.severity} />
        </div>
        <h3 className="safe-text mt-3 text-sm font-semibold leading-5 text-ink">{event.title}</h3>
        <p className="safe-text mt-2 text-xs leading-5 text-muted">{event.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-semibold text-accent">
          {areaLabels.map((label) => (
            <span key={label} className="inline-flex min-h-8 items-center gap-1 rounded border border-line bg-panelAlt px-2">
              <MapPin className="h-3.5 w-3.5" />
              {label}
            </span>
          ))}
        </div>
      </button>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-xs leading-5 text-muted">
        <span>{event.source_count} source{event.source_count === 1 ? "" : "s"} · urgency {event.urgency_score}</span>
        {event.source_url ? (
          <a href={event.source_url} target="_blank" rel="noopener noreferrer" className="focus-ring inline-flex min-h-11 items-center gap-1 rounded px-3 font-semibold text-accent hover:text-accentSoft">
            Source
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </div>
    </article>
  );
}

function DashboardSignalRadar({ lanes }: Readonly<{ lanes: AlternativeSignalLane[] }>) {
  const { t } = useTranslation();
  if (lanes.length === 0) return null;
  return (
    <section className="min-w-0" aria-labelledby="breaking-news-title">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="breaking-news-title" className="flex items-center gap-2 text-sm font-semibold text-warning">
            <Radar className="h-4 w-4" />
            {t("breakingNewsRadar")}
          </h2>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-muted">{t("breakingNewsRadarSummary")}</p>
        </div>
      </div>
      <div className="grid gap-3 xl:max-h-[610px] xl:overflow-y-auto xl:pr-1">
        {lanes.map((lane) => (
          <AlternativeSignalCard key={lane.key} lane={lane} />
        ))}
      </div>
    </section>
  );
}

function AlternativeSignalCard({ lane }: Readonly<{ lane: AlternativeSignalLane }>) {
  const { t } = useTranslation();
  const visibleItems = visibleAlternativeSignalItems(lane);
  return (
    <article className="panel flex min-h-[220px] min-w-0 flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold leading-5">{lane.title}</h3>
          <div className="mt-1 text-lg font-bold leading-7">{lane.value}</div>
        </div>
        <SeverityBadge value={lane.severity} />
      </div>
      <p className="mt-2 text-xs leading-5 text-muted">{lane.summary}</p>
      {visibleItems.length ? (
        <div className="mt-3 grid gap-2">
          {visibleItems.map((item) => {
            const content = (
              <>
                <div className="flex items-start justify-between gap-2">
                  <div className="safe-text min-w-0 text-xs font-semibold leading-5 text-ink">{item.label}</div>
                  <div className="safe-text max-w-[45%] shrink-0 text-right text-xs font-semibold leading-5 text-accent">
                    {item.value}
                  </div>
                </div>
                <p className="safe-text mt-1 text-xs leading-5 text-muted">{item.detail}</p>
              </>
            );
            const itemClass = "focus-ring min-h-11 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent";
            if (item.source_url) {
              return (
                <a key={item.key} className={itemClass} href={item.source_url} target="_blank" rel="noreferrer">
                  {content}
                </a>
              );
            }
            return (
              <div key={item.key} className={itemClass}>
                {content}
              </div>
            );
          })}
        </div>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-3 text-xs leading-5 text-muted">
        <span>{lane.cadence}</span>
        <span>{t("sourceLinksOnCards")}</span>
      </div>
    </article>
  );
}

function visibleAlternativeSignalItems(lane: AlternativeSignalLane) {
  return lane.items.slice(0, 4);
}

function formatEventAge(timestamp: string, locale: "en" | "ko") {
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return locale === "ko" ? "시간 미확인" : "time unknown";
  const ageMinutes = Math.max(0, Math.round((Date.now() - parsed) / 60_000));
  if (ageMinutes < 60) return locale === "ko" ? `${ageMinutes}분 전` : `${ageMinutes}m ago`;
  const ageHours = Math.round(ageMinutes / 60);
  return locale === "ko" ? `${ageHours}시간 전` : `${ageHours}h ago`;
}
