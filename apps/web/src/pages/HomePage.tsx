import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  CalendarDays,
  DatabaseZap,
  ExternalLink,
  Layers3,
  MapPinned,
  Radar,
  TrendingUp
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalLane, MetricTile, PublicEvent } from "@frw/shared-types";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { EventMap } from "../components/EventMap";
import { LineChart } from "../components/LineChart";
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

const marketGroups = [
  {
    title: "Equity / volatility",
    keys: ["nasdaq_composite", "nasdaq_100_futures", "kospi", "kodex_200", "kospi_200_futures", "vix"]
  },
  {
    title: "FX / commodities",
    keys: ["usd_krw", "usd_jpy", "wti_crude"]
  },
  {
    title: "Rates",
    keys: ["us_2y", "us_3y", "us_5y", "us_10y", "japan_policy_rate", "japan_2y", "japan_5y", "japan_10y"]
  }
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
  const priorityEvent = data.top_events[0];

  return (
    <div className="grid gap-7">
      <SnapshotBanner snapshot={snapshot} />
      <section className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <DatabaseZap className="h-4 w-4" />
            {t("publicSnapshot")}
          </div>
          <h1 className="mt-3 max-w-4xl text-4xl font-bold leading-tight md:text-5xl">{data.headline}</h1>
          <p className="mt-3 max-w-4xl text-base leading-7 text-muted md:text-lg md:leading-8">{data.summary}</p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <FreshnessBadge value={data.snapshot_health.status} />
          <SourceBadge label="snapshot-first" />
          <SourceBadge label="static approved public data" />
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(430px,0.95fr)_minmax(0,1.05fr)]">
        <section className="order-2 xl:order-1">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-accent">
              <MapPinned className="h-4 w-4" />
              Event geography
            </div>
            <Link to="/$locale/map" params={{ locale }} className="secondary-action py-1.5">
              Map
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <EventMap
            events={data.top_events}
            heightClass="h-[370px] md:h-[520px]"
            footer="Approved event geography. Boundaries are vendored locally; markers use reviewed public snapshot events."
            loadStrategy="idle-visible"
          />
        </section>

        <div className="order-1 xl:order-2">
          <MarketPulse tiles={marketTiles} />
        </div>
      </section>

      <AlternativeSignalRadar lanes={data.alternative_signals} />

      <section className="grid gap-5 lg:grid-cols-[1fr_0.6fr]">
        {priorityEvent ? <PriorityEvent event={priorityEvent} /> : null}
        <div className="panel p-5">
          <div className="flex items-center gap-2 font-semibold">
            <CalendarDays className="h-4 w-4" />
            {t("calendar")}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
            {data.calendar_preview.slice(0, 4).map((item) => (
              <div key={item.id} className="rounded-md border border-line bg-panelAlt px-4 py-3">
                <div className="text-sm font-semibold leading-5">{item.title}</div>
                <div className="mt-1.5 text-xs leading-5 text-muted">
                  {item.scheduled_local_date} · {item.expectation_type}
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

      <section className="grid gap-4 lg:grid-cols-[1fr_0.55fr]">
        <div>
          <h2 className="mb-3 text-xl font-bold">Approved Events</h2>
          <EventList events={data.top_events} />
        </div>
        <div>
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

function PriorityEvent({ event }: { event: PublicEvent }) {
  return (
    <section className="panel-raised p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-warning">
        <Activity className="h-4 w-4" />
        Priority event
      </div>
      <h2 className="mt-2 text-xl font-semibold leading-7">{event.title}</h2>
      <p className="mt-2 text-sm leading-6 text-muted">{event.why_it_matters}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <SourceBadge label={event.source_strength} />
        <SourceBadge label={`${event.evidence_count} evidence items`} />
      </div>
    </section>
  );
}

function MarketPulse({ tiles }: { tiles: MetricTile[] }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <TrendingUp className="h-4 w-4" />
            Market pulse
          </div>
          <p className="mt-1 text-sm leading-6 text-muted">
            Delayed/reference snapshot until licensed market-data redistribution is configured.
          </p>
        </div>
      </div>
      <div className="grid gap-5">
        {marketGroups.map((group) => {
          const groupTiles = tiles.filter((tile) => group.keys.includes(tile.key));
          if (groupTiles.length === 0) return null;
          const compact = group.title !== "Equity / volatility";
          return (
            <section key={group.title}>
              <h3 className="mb-2 text-xs font-semibold uppercase text-muted">{group.title}</h3>
              <div className={`grid gap-3 sm:grid-cols-2 ${compact ? "xl:grid-cols-3" : "xl:grid-cols-3"}`}>
                {groupTiles.map((tile) => (
                  <MarketTile key={tile.key} tile={tile} compact={compact} />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

function MarketTile({ tile, compact = false }: { tile: MetricTile; compact?: boolean }) {
  return (
    <article className={`panel p-4 ${compact ? "min-h-[116px]" : "min-h-[142px]"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm leading-5 text-muted">{tile.label}</div>
          <div className={`${compact ? "text-xl" : "text-2xl"} mt-1 font-bold leading-8 text-ink`}>
            {tile.value}
            {tile.unit ? <span className="ml-1 text-sm font-semibold text-muted">{tile.unit}</span> : null}
          </div>
        </div>
        <FreshnessBadge value={tile.freshness} />
      </div>
      <div className="mt-3 text-xs leading-5 text-muted">
        {tile.source} · {tile.delay_label}
      </div>
      {!compact && tile.points ? <LineChart points={tile.points} label={tile.label} /> : null}
    </article>
  );
}

function AlternativeSignalRadar({ lanes }: { lanes: AlternativeSignalLane[] }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-warning">
            <Radar className="h-4 w-4" />
            Alternative risk radar
          </div>
          <p className="mt-1 max-w-4xl text-sm leading-6 text-muted">
            Short-interest, short-volume, activist short research, weak OSINT, and filing monitors are collated here
            with explicit source strength.
          </p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {lanes.map((lane) => (
          <AlternativeSignalCard key={lane.key} lane={lane} />
        ))}
      </div>
    </section>
  );
}

function AlternativeSignalCard({ lane }: { lane: AlternativeSignalLane }) {
  const lead = lane.items[0];
  return (
    <article className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold leading-5">{lane.title}</h3>
          <div className="mt-1 text-lg font-bold leading-7">{lane.value}</div>
        </div>
        <SeverityBadge value={lane.severity} />
      </div>
      <p className="mt-2 min-h-12 text-xs leading-5 text-muted">{lane.summary}</p>
      {lead ? (
        <p className="mt-3 text-xs leading-5 text-muted">
          <span className="font-semibold text-ink">{lead.label}:</span> {lead.value}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs leading-5 text-muted">
        <span>{lane.cadence}</span>
        {lane.source_url ? (
          <a className="focus-ring inline-flex items-center gap-1 text-accent hover:underline" href={lane.source_url} target="_blank" rel="noreferrer">
            source
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        ) : null}
      </div>
    </article>
  );
}
