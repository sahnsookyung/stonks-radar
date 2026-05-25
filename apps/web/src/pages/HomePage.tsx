import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  DatabaseZap,
  ExternalLink,
  Layers3,
  MapPinned,
  Radar,
  TrendingUp
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalLane, CalendarItem, MetricTile, PublicEvent } from "@frw/shared-types";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { EventMap } from "../components/EventMap";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

const marketOrder = [
  "nasdaq_composite",
  "nasdaq_100_futures",
  "kospi",
  "kodex_200",
  "kospi_200_futures",
  "wti_crude",
  "vix",
  "usd_krw",
  "usd_jpy",
  "us_2y",
  "us_3y",
  "us_5y",
  "us_10y",
  "japan_policy_rate",
  "japan_2y",
  "japan_5y",
  "japan_10y"
];

export function HomePage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["snapshot", "home", locale],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const snapshot = query.data;
  const data = snapshot.data;
  const marketTiles = [...data.macro_tiles].sort(
    (left, right) => marketRank(left.key) - marketRank(right.key)
  );
  const policyCalendar = sortCalendarItems(
    data.calendar_preview.filter((item) => item.release_type === "central_bank")
  );
  const priorityEvent = data.top_events[0];

  return (
    <div className="grid min-w-0 gap-7">
      <SnapshotBanner snapshot={snapshot} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <DatabaseZap className="h-4 w-4" />
            {t("publicSnapshot")}
          </div>
          <h1 className="mt-3 max-w-4xl break-words text-4xl font-bold leading-tight md:text-5xl">{data.headline}</h1>
          <p className="mt-3 max-w-4xl break-words text-base leading-7 text-muted md:text-lg md:leading-8">{data.summary}</p>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2.5">
          <FreshnessBadge value={data.snapshot_health.status} />
          <SourceBadge label={t("snapshotFirst")} />
          <SourceBadge label={t("approvedPublicData")} />
        </div>
      </section>

      <MarketPulse tiles={marketTiles} />

      <section className="min-w-0" aria-labelledby="event-geography-title">
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
            heightClass="h-[540px] md:h-[720px] xl:h-[760px]"
            footer={t("eventMapFooter")}
            loadStrategy="idle-visible"
          />
      </section>

      <AlternativeSignalRadar lanes={data.alternative_signals} />

      <section className="grid min-w-0 gap-5 lg:grid-cols-[1fr_0.6fr]">
        {priorityEvent ? <PriorityEvent event={priorityEvent} /> : null}
        <div className="panel p-5">
          <div className="flex items-center gap-2 font-semibold">
            <CalendarDays className="h-4 w-4" />
            {t("calendar")}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {policyCalendar.slice(0, 4).map((item) => (
              <div key={item.id} className="rounded-md border border-line bg-panelAlt px-4 py-3">
                <div className="text-sm font-semibold leading-5">{item.title}</div>
                <div className="mt-1.5 text-xs leading-5 text-muted">
                  {item.scheduled_local_date} · {item.source} · {calendarExpectationLabel(item.expectation_type, locale)}
                </div>
              </div>
            ))}
          </div>
          <Link to="/$locale/calendar" params={{ locale }} className="primary-action mt-4">
            {t("calendar")}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-center gap-2 text-muted">
          <Layers3 className="h-5 w-5" />
          <h2 className="text-xl font-bold text-ink">{t("sectors")}</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {data.sector_tiles.map((sector) => (
            <Link
              key={sector.key}
              to="/$locale/sectors/$sectorKey"
              params={{ locale, sectorKey: sector.key }}
              className="panel focus-ring block p-5 hover:border-accent"
            >
              <div className="text-lg font-semibold">{sector.name}</div>
              <p className="mt-2 min-h-20 text-sm leading-6 text-muted">{sector.summary}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <FreshnessBadge value={sector.freshness} />
                <SourceBadge label={sector.source_strength} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section className="grid min-w-0 gap-4 lg:grid-cols-[1fr_0.55fr]">
        <div className="min-w-0">
          <h2 className="mb-3 text-xl font-bold">{t("approvedEvents")}</h2>
          <EventList events={data.top_events} />
        </div>
        <div className="min-w-0">
          <h2 className="mb-3 text-xl font-bold">{t("scenarioBaskets")}</h2>
          <div className="grid gap-3">
            {data.scenario_baskets.map((basket) => (
              <Link
                key={basket.key}
                to="/$locale/scenario-baskets/$basketKey"
                params={{ locale, basketKey: basket.key }}
                className="panel focus-ring block p-5 hover:border-accent"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-semibold">{basket.name}</h3>
                  <FreshnessBadge value={basket.freshness} />
                </div>
                <p className="mt-2 text-sm leading-6 text-muted">{basket.thesis}</p>
                <p className="mt-2 text-xs text-muted">{basket.risk_summary}</p>
              </Link>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function marketRank(key: string) {
  const index = marketOrder.indexOf(key);
  return index === -1 ? marketOrder.length : index;
}

function sortCalendarItems(items: CalendarItem[]) {
  return [...items].sort((left, right) => left.scheduled_local_date.localeCompare(right.scheduled_local_date));
}

function calendarExpectationLabel(expectationType: string, locale: "en" | "ko") {
  if (expectationType === "official_projection") return locale === "ko" ? "공식 전망" : "official projections";
  if (expectationType === "official_calendar") return locale === "ko" ? "공식 일정" : "official calendar";
  if (expectationType === "manual_estimate") return locale === "ko" ? "수동 추정" : "manual estimate";
  return locale === "ko" ? "감시" : "watch";
}

function PriorityEvent({ event }: { event: PublicEvent }) {
  const { t } = useTranslation();
  return (
    <section className="panel-raised p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-warning">
        <Activity className="h-4 w-4" />
        {t("priorityEvent")}
      </div>
      <h2 className="mt-2 text-xl font-semibold leading-7">{event.title}</h2>
      <p className="mt-2 text-sm leading-6 text-muted">{event.why_it_matters}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <SourceBadge label={event.source_strength} />
        <SourceBadge label={t("evidenceItems", { count: event.evidence_count })} />
      </div>
    </section>
  );
}

function MarketPulse({ tiles }: { tiles: MetricTile[] }) {
  const unavailableTiles = tiles.filter(isUnavailableTile);
  const activeTiles = tiles.filter((tile) => !isUnavailableTile(tile));
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const locale = useLocale();
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const visibleTiles = [...activeTiles, ...unavailableTiles];
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const scroll = (direction: -1 | 1) => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollBy({
      left: direction * Math.max(320, container.clientWidth * 0.75),
      behavior: "smooth"
    });
  };

  return (
    <section className="panel min-w-0 overflow-hidden p-4" aria-labelledby="market-pulse-title">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="market-pulse-title" className="flex items-center gap-2 text-sm font-semibold text-accent">
            <TrendingUp className="h-4 w-4" />
            {t("marketPulse")}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted">{t("marketPulseSummary")}</p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="secondary-action h-10 min-h-10 w-10 p-0" onClick={() => scroll(-1)} aria-label={t("scrollLeft")}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button type="button" className="secondary-action h-10 min-h-10 w-10 p-0" onClick={() => scroll(1)} aria-label={t("scrollRight")}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div
        ref={scrollRef}
        className="-mx-1 flex max-w-full snap-x gap-3 overflow-x-auto px-1 pb-2"
        data-testid="market-pulse-strip"
      >
        {visibleTiles.map((tile) => (
          <MarketTile key={tile.key} tile={tile} locale={locale} now={now} />
        ))}
      </div>
    </section>
  );
}

function MarketTile({ tile, locale, now }: { tile: MetricTile; locale: "en" | "ko"; now: number }) {
  const unavailable = isUnavailableTile(tile);
  const className =
    "panel focus-ring flex min-h-[164px] w-[220px] shrink-0 snap-start flex-col p-4 transition-colors hover:border-accent md:w-[240px]";
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm leading-5 text-muted">{tile.label}</div>
          <div className="mt-1 text-2xl font-bold leading-8 text-ink">
            {tile.value}
            {tile.unit ? <span className="ml-1 text-sm font-semibold text-muted">{tile.unit}</span> : null}
          </div>
        </div>
        {unavailable ? (
          <span className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] font-semibold uppercase leading-4 text-warning">
            {locale === "ko" ? "공백" : "gap"}
          </span>
        ) : null}
      </div>
      <div className="mt-3 text-xs font-semibold leading-5 text-accent">{formatMetricUpdate(tile.updated_at, locale, now)}</div>
      {tile.next_event ? (
        <div className="mt-auto flex items-start gap-2 pt-3 text-xs leading-5 text-muted">
          <CalendarDays className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="min-w-0">
            <span className="font-semibold text-ink">{locale === "ko" ? "다음:" : "Next:"}</span> {tile.next_event.title} ·{" "}
            {tile.next_event.date}
          </span>
        </div>
      ) : null}
    </>
  );

  if (tile.source_url) {
    return (
      <a className={className} href={tile.source_url} target="_blank" rel="noreferrer" aria-label={`${tile.label} source`}>
        {body}
      </a>
    );
  }

  return <article className={className}>{body}</article>;
}

function isUnavailableTile(tile: MetricTile) {
  return (
    tile.coverage_status === "coverage_gap" ||
    tile.value.trim().toLowerCase() === "not connected" ||
    tile.freshness === "unsupported"
  );
}

function formatMetricUpdate(value: string, locale: "en" | "ko", now: number) {
  const updatedAt = Date.parse(value);
  if (!Number.isFinite(updatedAt)) return locale === "ko" ? "갱신 시각 불명" : "Updated time unknown";
  const elapsedMinutes = Math.max(0, Math.floor((now - updatedAt) / 60_000));
  if (elapsedMinutes < 1) return locale === "ko" ? "방금 갱신" : "Updated just now";
  if (elapsedMinutes < 60) return locale === "ko" ? `${elapsedMinutes}분 전 갱신` : `Updated ${elapsedMinutes}m ago`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 48) return locale === "ko" ? `${elapsedHours}시간 전 갱신` : `Updated ${elapsedHours}h ago`;
  const elapsedDays = Math.floor(elapsedHours / 24);
  return locale === "ko" ? `${elapsedDays}일 전 갱신` : `Updated ${elapsedDays}d ago`;
}

function AlternativeSignalRadar({ lanes }: { lanes: AlternativeSignalLane[] }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="shorts-risk-title">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="shorts-risk-title" className="flex items-center gap-2 text-sm font-semibold text-warning">
            <Radar className="h-4 w-4" />
            {t("shortsEventRadar")}
          </h2>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-muted">{t("shortsEventRadarSummary")}</p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {lanes.map((lane) => (
          <AlternativeSignalCard key={lane.key} lane={lane} />
        ))}
      </div>
    </section>
  );
}

function AlternativeSignalCard({ lane }: { lane: AlternativeSignalLane }) {
  const { t } = useTranslation();
  const visibleItems = lane.items.slice(0, 4);
  return (
    <article className="panel flex min-h-[280px] flex-col p-4">
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
                  <div className="min-w-0 text-xs font-semibold leading-5 text-ink">{item.label}</div>
                  <div className="max-w-[45%] shrink-0 text-right text-xs font-semibold leading-5 text-accent">
                    {item.value}
                  </div>
                </div>
                <p className="mt-1 text-xs leading-5 text-muted">{item.detail}</p>
              </>
            );
            const itemClass = "focus-ring rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent";
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
        {lane.source_url ? (
          <a
            className="focus-ring inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-accent hover:underline"
            href={lane.source_url}
            target="_blank"
            rel="noreferrer"
          >
            {t("source")}
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </div>
    </article>
  );
}
