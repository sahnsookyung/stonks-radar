import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  CalendarDays,
  DatabaseZap,
  MapPinned,
  Radar
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalLane, CalendarItem, PublicEvent } from "@frw/shared-types";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { EventMap } from "../components/EventMap";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { MarketPulseTickerBar, sortMarketTiles } from "../components/MarketPulse";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

const dashboardSignalKeys = new Set(["breaking_market_news"]);
const chokepointNewsPattern = /hormuz|strait of hormuz|iran|red sea/i;

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
  const marketTiles = sortMarketTiles(data.macro_tiles);
  const policyCalendar = sortCalendarItems(
    data.calendar_preview.filter((item) => item.release_type === "central_bank")
  );
  const dashboardSignals = data.alternative_signals.filter((lane) => dashboardSignalKeys.has(lane.key));
  const priorityEvent = data.top_events[0];

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
          <SourceBadge label={t("approvedPublicData")} />
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
              heightClass="h-[clamp(330px,48svh,500px)] md:h-[560px] xl:h-[610px]"
              footer={t("eventMapFooter")}
              loadStrategy="idle-visible"
            />
        </div>

        <DashboardSignalRadar lanes={dashboardSignals} />
      </section>

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

function sortCalendarItems(items: CalendarItem[]) {
  return [...items].sort((left, right) => left.scheduled_local_date.localeCompare(right.scheduled_local_date));
}

function calendarExpectationLabel(expectationType: string, locale: "en" | "ko") {
  if (expectationType === "official_projection") return locale === "ko" ? "공식 전망" : "official projections";
  if (expectationType === "official_calendar") return locale === "ko" ? "공식 일정" : "official calendar";
  if (expectationType === "manual_estimate") return locale === "ko" ? "수동 추정" : "manual estimate";
  return locale === "ko" ? "감시" : "watch";
}

function PriorityEvent({ event }: Readonly<{ event: PublicEvent }>) {
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
  if (lane.key !== "breaking_market_news") return lane.items.slice(0, 4);
  return [...lane.items]
    .sort((left, right) => {
      const leftMatches = chokepointNewsPattern.test(`${left.label} ${left.detail}`) ? 0 : 1;
      const rightMatches = chokepointNewsPattern.test(`${right.label} ${right.detail}`) ? 0 : 1;
      return leftMatches - rightMatches;
    })
    .slice(0, 4);
}
