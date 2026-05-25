import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Filter, MapPinned } from "lucide-react";
import type { Severity } from "@frw/shared-types";
import { EventMap } from "../components/EventMap";
import { EventList } from "../components/EventList";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function MapPage() {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "map", locale],
    queryFn: () => snapshotQueries.map(locale)
  });
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [sector, setSector] = useState("all");

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const events = query.data.data.events.filter(
    (event) =>
      (severity === "all" || event.severity === severity) &&
      (sector === "all" || event.sector_keys.includes(sector))
  );

  return (
    <div className="grid gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <MapPinned className="h-4 w-4" />
            MapLibre static event layer
          </div>
          <h1 className="mt-2 text-4xl font-bold">Global Intelligence Map</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="h-4 w-4 text-muted" />
          <select
            className="input-control"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity | "all")}
          >
            <option value="all">All severity</option>
            {query.data.data.filters.severities.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <select
            className="input-control"
            value={sector}
            onChange={(event) => setSector(event.target.value)}
          >
            <option value="all">All sectors</option>
            {query.data.data.filters.sectors.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
      </section>
      <EventMap
        events={events}
        heightClass="h-[560px] min-h-[560px] md:h-[720px] xl:h-[calc(100vh-260px)]"
        loadStrategy="idle-visible"
      />
      <EventList events={events} />
    </div>
  );
}
