import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Landmark } from "lucide-react";
import { CalendarTable } from "../components/CalendarTable";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { LineChart } from "../components/LineChart";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function CountryRegionPage({ type }: { type: "country" | "region" }) {
  const locale = useLocale();
  const params = useParams({ strict: false }) as { objectKey?: string };
  const key = params.objectKey ?? "USA";
  const query = useQuery({
    queryKey: ["snapshot", type, key, locale],
    queryFn: () => (type === "country" ? snapshotQueries.country(key, locale) : snapshotQueries.region(key, locale))
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const data = query.data.data;

  return (
    <div className="grid gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section>
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Landmark className="h-4 w-4" />
          {data.type}
        </div>
        <h1 className="mt-2 text-4xl font-bold">{data.name}</h1>
        <p className="mt-3 max-w-4xl text-base leading-7 text-muted">{data.overview}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <FreshnessBadge value={data.freshness} />
          <SourceBadge label={data.source_strength} />
        </div>
      </section>
      <section className="grid gap-4 md:grid-cols-3">
        {data.indicators.map((tile) => (
          <article key={tile.key} className="panel p-4">
            <div className="text-sm text-muted">{tile.label}</div>
            <div className="mt-1 text-2xl font-bold">{tile.value}</div>
            <div className="mt-2 text-xs text-muted">{tile.source}</div>
            {tile.points ? <LineChart points={tile.points} label={tile.label} /> : null}
          </article>
        ))}
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Recent approved events</h2>
        <EventList events={data.recent_events} />
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Upcoming calendar items</h2>
        <CalendarTable items={data.calendar_items} />
      </section>
    </div>
  );
}
