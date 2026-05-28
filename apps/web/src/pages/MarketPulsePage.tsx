import { useQuery } from "@tanstack/react-query";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { MarketPulseBoard } from "../components/MarketPulse";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function MarketPulsePage() {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "home", locale],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <MarketPulseBoard tiles={query.data.data.macro_tiles} />
    </div>
  );
}
