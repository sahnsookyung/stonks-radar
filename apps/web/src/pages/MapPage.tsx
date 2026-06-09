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
  const [selectedMapPointId, setSelectedMapPointId] = useState<string | null>(null);

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const events = query.data.data.events.filter(
    (event) =>
      (severity === "all" || event.severity === severity) &&
      (sector === "all" || event.sector_keys.includes(sector))
  );
  const mapPoints = (query.data.data.breaking_market_map?.map_points ?? []).filter(
    (point) => severity === "all" || point.severity === severity
  );

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <MapPinned className="h-4 w-4" />
            MapLibre static event layer
          </div>
          <h1 className="mt-2 text-3xl font-bold sm:text-4xl">Global Intelligence Map</h1>
        </div>
        <div className="grid w-full grid-cols-1 gap-2 sm:flex sm:w-auto sm:flex-wrap sm:items-center">
          <Filter className="h-4 w-4 text-muted" />
          <select
            className="input-control w-full sm:w-auto"
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
            className="input-control w-full sm:w-auto"
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
        mapPoints={mapPoints}
        selectedMapPointId={selectedMapPointId}
        onMapPointSelect={setSelectedMapPointId}
        heightClass="h-[clamp(420px,60svh,640px)] md:h-[720px] xl:h-[calc(100vh-260px)]"
        loadStrategy="idle-visible"
      />
      <EventList events={events} />
    </div>
  );
}
