import { useQuery } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { CalendarTable } from "../components/CalendarTable";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function CalendarPage({ centralBanksOnly = false }: Readonly<{ centralBanksOnly?: boolean }>) {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "calendar", locale],
    queryFn: () => snapshotQueries.calendar(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const items = centralBanksOnly ? query.data.data.central_banks : query.data.data.items;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <CalendarClock className="h-4 w-4" />
          Expectations are labeled by taxonomy
        </div>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">
          {centralBanksOnly ? "Central-bank Calendar" : "Economic Calendar"}
        </h1>
        <p className="safe-text mt-3 max-w-3xl text-sm leading-6 text-muted">{query.data.data.methodology}</p>
      </section>
      <CalendarTable items={items} />
    </div>
  );
}
