import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Scale, TrendingUp } from "lucide-react";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function ScenarioBasketPage() {
  const locale = useLocale();
  const params = useParams({ strict: false }) as { basketKey?: string };
  const basketKey = params.basketKey ?? "ai-infra-capex";
  const query = useQuery({
    queryKey: ["snapshot", "scenario", basketKey, locale],
    queryFn: () => snapshotQueries.scenarioBasket(basketKey, locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const data = query.data.data;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <TrendingUp className="h-4 w-4" />
          Scenario basket
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{data.name}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{data.thesis}</p>
      </section>
      <section className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
        <div className="panel p-4">
          <h2 className="text-xl font-bold">Illustrative methodology</h2>
          <p className="safe-text mt-3 text-sm leading-6 text-muted">{data.methodology}</p>
          <div className="mt-4 grid gap-2 md:hidden">
            {data.included_objects.map((object) => (
              <article key={object.object_key} className="rounded-md border border-line bg-panelAlt p-3">
                <div className="safe-text text-sm font-semibold">{object.name}</div>
                <p className="safe-text mt-2 text-xs leading-5 text-muted">{object.reason}</p>
                <div className="mt-2 text-xs font-semibold uppercase text-accent">{object.illustrative_weight}</div>
              </article>
            ))}
          </div>
          <div className="mt-4 hidden overflow-x-auto md:block" data-allow-horizontal-scroll aria-label="Scenario basket included objects table">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-panelAlt text-xs uppercase text-muted">
                <tr>
                  <th className="px-3 py-2">Object</th>
                  <th className="px-3 py-2">Reason</th>
                  <th className="px-3 py-2">Illustrative weight</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.included_objects.map((object) => (
                  <tr key={object.object_key}>
                    <td className="px-3 py-3 font-semibold">{object.name}</td>
                    <td className="px-3 py-3 text-muted">{object.reason}</td>
                    <td className="px-3 py-3">{object.illustrative_weight}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <aside className="grid gap-4">
          <div className="panel p-4">
            <h2 className="font-semibold">Risk summary</h2>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">{data.risk_summary}</p>
          </div>
          <div className="signal-warning safe-text p-4 text-sm leading-6">
            <div className="mb-2 flex items-center gap-2 font-semibold">
              <Scale className="h-4 w-4" />
              Research boundary
            </div>
            {data.disclaimer}
          </div>
          <div className="panel safe-text p-4 text-sm text-muted">{data.data_delay_warning}</div>
        </aside>
      </section>
    </div>
  );
}
