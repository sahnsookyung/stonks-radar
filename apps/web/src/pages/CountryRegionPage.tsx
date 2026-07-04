import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Landmark, Newspaper } from "lucide-react";
import { CalendarTable } from "../components/CalendarTable";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { EventList } from "../components/EventList";
import { LineChart } from "../components/LineChart";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function CountryRegionPage({ type }: Readonly<{ type: "country" | "region" }>) {
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
  const newsRegionKey = key === "EUROZONE" ? "EU" : key;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Landmark className="h-4 w-4" />
          {data.type}
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{data.name}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{data.overview}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <FreshnessBadge value={data.freshness} />
          <SourceBadge label={data.source_strength} />
          <a
            href={`/${locale}/news?region=${encodeURIComponent(newsRegionKey)}`}
            className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-accent/40 bg-accentSoft px-3 text-sm font-semibold text-accent hover:border-accent"
          >
            <Newspaper className="h-4 w-4" />
            {locale === "ko" ? "지역 뉴스" : "Region news"}
          </a>
        </div>
      </section>
      <section className="grid gap-4 md:grid-cols-3">
        {data.indicators.map((tile) => (
          <article key={tile.key} className="panel min-w-0 p-4">
            <div className="safe-text text-sm text-muted">{tile.label}</div>
            <div className="safe-text mt-1 text-2xl font-bold">{tile.value}</div>
            <div className="safe-text mt-2 text-xs text-muted">{tile.source}</div>
            {tile.points ? <LineChart points={tile.points} label={tile.label} /> : null}
          </article>
        ))}
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">
          {locale === "ko" ? "최근 출처 연결 항목" : "Recent source-linked items"}
        </h2>
        <EventList events={data.recent_events} />
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Upcoming calendar items</h2>
        <CalendarTable items={data.calendar_items} />
      </section>
    </div>
  );
}
