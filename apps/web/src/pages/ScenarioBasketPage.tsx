import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import type { ScenarioTrackerMetricRow, ScenarioTrackerSection } from "@frw/shared-types";
import { ExternalLink, FileSearch, Scale, TrendingUp } from "lucide-react";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { NewsEventCard } from "../components/NewsEventCard";
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
          Scenario evidence
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{data.name}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{data.thesis}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <SourceBadge label={data.coverage_status.replace("_", " ")} />
          <SourceBadge label={`${data.evidence_count} evidence rows`} />
          <SourceBadge label={`observed ${data.last_observed_at.slice(0, 10)}`} />
        </div>
      </section>

      <section className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)]">
        <div className="grid min-w-0 gap-4">
          {data.tracker_sections.map((section) => (
            <TrackerSection key={section.key} section={section} />
          ))}
        </div>
        <aside className="grid content-start gap-4">
          <div className="panel p-4">
            <h2 className="font-semibold">Risk summary</h2>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">{data.risk_summary}</p>
          </div>
          <div className="panel p-4">
            <h2 className="font-semibold">Methodology</h2>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">{data.methodology}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a href={data.primary_source_url} target={data.primary_source_url.startsWith("http") ? "_blank" : undefined} rel="noreferrer" className="secondary-action">
                Primary source
                <ExternalLink className="h-4 w-4" />
              </a>
              {data.external_tracker_url ? (
                <a href={data.external_tracker_url} target="_blank" rel="noreferrer" className="secondary-action">
                  External tracker
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
            </div>
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

function TrackerSection({ section }: Readonly<{ section: ScenarioTrackerSection }>) {
  const locale = useLocale();
  return (
    <article className="panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="safe-text text-xl font-bold">{section.title}</h2>
          <p className="safe-text mt-2 text-sm leading-6 text-muted">{section.summary}</p>
        </div>
        <SourceBadge label={section.coverage_status.replace("_", " ")} />
      </div>
      <div className="mt-4 grid gap-3">
        {section.metric_rows.map((row) => <MetricRow key={row.key} row={row} />)}
      </div>
      {section.news_events.length ? (
        <div className="mt-5 grid gap-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-accent">
            <FileSearch className="h-4 w-4" />
            Recent source-linked news
          </h3>
          {section.news_events.slice(0, 4).map((event) => (
            <NewsEventCard key={event.id} event={event} locale={locale} compact />
          ))}
        </div>
      ) : null}
      <div className="mt-5 flex flex-wrap gap-2">
        {section.source_links.map((source) => (
          <a key={`${source.source_key}-${source.url}`} href={source.url} target="_blank" rel="noreferrer" className="secondary-action">
            {source.label}
            <ExternalLink className="h-4 w-4" />
          </a>
        ))}
      </div>
    </article>
  );
}

function MetricRow({ row }: Readonly<{ row: ScenarioTrackerMetricRow }>) {
  return (
    <a
      href={row.source_url}
      target={row.source_url.startsWith("http") ? "_blank" : undefined}
      rel="noreferrer"
      className="focus-ring block rounded-md border border-line bg-panelAlt p-3 hover:border-accent"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="safe-text text-sm font-semibold">{row.label}</div>
          <p className="safe-text mt-1 text-xs leading-5 text-muted">{row.detail}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <span className="text-sm font-bold text-accent">{row.value}</span>
          <FreshnessBadge value={row.freshness} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted">
        <SourceBadge label={row.source} />
        <SourceBadge label={row.coverage_status.replace("_", " ")} />
        <SourceBadge label={row.as_of_date.slice(0, 10)} />
      </div>
    </a>
  );
}
