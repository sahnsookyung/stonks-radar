import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { Factory, ShieldAlert } from "lucide-react";
import { CalendarTable } from "../components/CalendarTable";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function SectorPage() {
  const locale = useLocale();
  const params = useParams({ strict: false }) as { sectorKey?: string };
  const sectorKey = params.sectorKey ?? "semiconductors";
  const query = useQuery({
    queryKey: ["snapshot", "sector", sectorKey, locale],
    queryFn: () => snapshotQueries.sector(sectorKey, locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const data = query.data.data;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Factory className="h-4 w-4" />
          Sector module
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{data.name}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{data.overview}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <FreshnessBadge value={data.freshness} />
          <SourceBadge label={data.source_strength} />
        </div>
      </section>
      <section className="grid gap-4 lg:grid-cols-3">
        <InfoList title="Entities" items={data.monitored_entities} />
        <InfoList title="Instruments" items={data.monitored_instruments} />
        <InfoList title="Country/region exposure" items={data.country_region_exposure} />
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Recent approved events</h2>
        <EventList events={data.recent_events} />
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Upcoming calendar items</h2>
        <CalendarTable items={data.upcoming_calendar_items} />
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <InfoList title="Macro/geopolitical drivers" items={data.macro_geopolitical_drivers} />
        <div className="panel min-w-0 p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <ShieldAlert className="h-4 w-4" />
            Risks and caveats
          </div>
          <ul className="grid gap-2 text-sm leading-6 text-muted">
            {data.risks_and_caveats.map((item) => (
              <li key={item} className="safe-text">{item}</li>
            ))}
          </ul>
        </div>
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Scenario baskets</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {data.scenario_baskets.map((basket) => (
            <Link
              key={basket.key}
              to="/$locale/scenario-baskets/$basketKey"
              params={{ locale, basketKey: basket.key }}
              className="panel focus-ring block p-4 hover:border-accent"
            >
              <div className="safe-text font-semibold">{basket.name}</div>
              <p className="safe-text mt-2 text-sm leading-6 text-muted">{basket.thesis}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function InfoList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="panel min-w-0 p-4">
      <h2 className="font-semibold">{title}</h2>
      <ul className="mt-3 grid gap-2 text-sm text-muted">
        {items.map((item) => (
          <li key={item} className="safe-text">{item}</li>
        ))}
      </ul>
    </div>
  );
}
