import { useQuery } from "@tanstack/react-query";
import { ServerCog } from "lucide-react";
import { FreshnessBadge } from "../components/Badge";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function SourceStatusPage() {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "status", locale],
    queryFn: () => snapshotQueries.status(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const data = query.data.data;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <ServerCog className="h-4 w-4" />
          Data freshness and operations
        </div>
        <h1 className="mt-2 text-3xl font-bold sm:text-4xl">Status</h1>
        <p className="safe-text mt-3 text-sm leading-6 text-muted">
          Public pages are snapshot-first and do not require live backend reads. Admin ingestion, publication,
          and provider verification require the backend.
        </p>
      </section>
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatusTile label="Snapshot age" value={`${data.snapshot_age_minutes} min`} />
        <StatusTile label="Degraded mode" value={data.degraded_mode ? "yes" : "no"} />
        <StatusTile label="Disk watermark" value={data.operations.disk_watermark} />
        <StatusTile label="Snapshot storage" value={data.operations.snapshot_storage_status} />
        <StatusTile label="Backup" value={data.operations.backup_status} />
      </section>
      <section className="grid gap-3 md:hidden" aria-label="Provider status cards">
        {data.providers.map((provider) => (
          <article key={provider.provider_key} className="panel min-w-0 p-4">
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="safe-text text-sm font-semibold leading-5">{provider.provider_key}</h2>
                <p className="mt-1 text-xs leading-5 text-muted">
                  {provider.provider_type} · {provider.mode}
                </p>
              </div>
              <FreshnessBadge
                value={provider.status === "ready" ? "fresh" : provider.status === "missing_credentials" ? "unsupported" : "watch"}
              />
            </div>
            {provider.warning ? <p className="safe-text mt-3 text-xs leading-5 text-muted">{provider.warning}</p> : null}
          </article>
        ))}
      </section>
      <section className="table-surface hidden md:block" data-allow-horizontal-scroll aria-label="Provider status table">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-panelAlt text-xs uppercase text-muted">
            <tr>
              <th className="px-3 py-3">Provider</th>
              <th className="px-3 py-3">Type</th>
              <th className="px-3 py-3">Mode</th>
              <th className="px-3 py-3">Status</th>
              <th className="px-3 py-3">Warning</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data.providers.map((provider) => (
              <tr key={provider.provider_key}>
                <td className="px-3 py-3 font-semibold">{provider.provider_key}</td>
                <td className="px-3 py-3">{provider.provider_type}</td>
                <td className="px-3 py-3">{provider.mode}</td>
                <td className="px-3 py-3">
                  <FreshnessBadge
                    value={provider.status === "ready" ? "fresh" : provider.status === "missing_credentials" ? "unsupported" : "watch"}
                  />
                </td>
                <td className="px-3 py-3 text-muted">{provider.warning ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel min-w-0 p-4">
      <div className="text-xs uppercase text-muted">{label}</div>
      <div className="safe-text mt-2 text-xl font-bold sm:text-2xl">{value}</div>
    </div>
  );
}
