import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { AlertTriangle, Database, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { apiGet, apiPost, syncCsrfTokenFromCookie } from "../lib/api";
import { featureGates, usageQuotas } from "../lib/portfolioAtlas";

interface AdminDashboardPayload {
  user: { email: string; role: string };
  metrics: Record<string, string | number | boolean | null>;
  release_controls?: {
    release_id: string;
    payload_version: number;
    runtime_switches: {
      key: string;
      enabled: boolean;
      rollback_value: string;
    }[];
    canary: {
      status: string;
      checks: {
        key: string;
        status: string;
        value: string | number | boolean | null;
        threshold: string | number | boolean | null;
        summary: string;
      }[];
    };
    source_funnel: {
      totals: Record<string, number>;
      sources: {
        source_key: string;
        status: string;
        counters: Record<string, number>;
      }[];
    };
    provenance: {
      release_id: string;
      source_documents: number;
      source_facts: number;
      market_bars: number;
      quarantine_available: boolean;
    };
    rollback_controls: {
      scheduler_pause_keys: string[];
      unsafe_job_states: string[];
      rollback_actions: string[];
      payload_versions: { current: number; accepted: number[] };
    };
  };
  news_v2?: {
    totals: {
      clusters: number;
      source_documents: number;
      source_facts: number;
      quarantined_documents: number;
      quarantined_facts: number;
    };
    clusters: {
      id: string;
      canonical_title: string;
      review_state: string;
      status: string;
      source_count: number;
      trust_score: number;
      breaking_score: number;
      last_seen_at: string | null;
    }[];
    source_documents: {
      id: string;
      title: string;
      source_key: string | null;
      publisher: string | null;
      status: string;
      public_allowed: boolean;
      observed_at: string | null;
    }[];
    source_fact_counts: {
      fact_type: string;
      review_status: string;
      public_allowed: boolean;
      row_count: number;
    }[];
    ingestion_runs: {
      ingestion_run_id: string;
      row_count: number;
      newest_at: string | null;
    }[];
  };
  provider_budgets: {
    id: string;
    provider_key: string;
    provider_type: string;
    routing_mode: string;
    kill_switch_enabled: boolean;
    current_period_usage: number;
    hard_limit: number | null;
  }[];
  dead_letter_jobs: {
    id: string;
    job_type: string;
    last_error_message: string | null;
    created_at: string;
  }[];
  source_health: {
    source_key: string;
    status: string;
    status_code: string | null;
    response_ms: number | null;
    last_checked_at: string;
    last_error: string | null;
  }[];
  candidate_facts: {
    id: string;
    fact_type: string;
    predicate: string;
    confidence: number;
    extraction_source: string;
    created_at: string;
  }[];
  candidate_events: {
    id: string;
    event_key: string;
    event_type: string;
    severity: string;
    source_strength: string;
    review_status: string;
    discovered_at: string;
  }[];
  snapshot_candidates: {
    snapshot_version: number;
    publication_status: string;
    generated_at: string;
    published_at: string | null;
    byte_size: number;
    content_hash: string;
  }[];
}

interface AdminInstrumentSearchPayload {
  results: {
    instrumentId: string;
    listingId: string;
    displaySymbol: string;
    name: string;
    exchange: string;
    country: string;
    currency: string;
    assetClass: string;
    instrumentType: string;
    qualityLevel: string;
  }[];
  dataFreshness?: { instrumentIndexLastUpdatedAt?: string; status?: string };
}

interface AdminInstrumentReviewPayload {
  items: {
    id: string;
    query: string;
    context_screen: string;
    optional_notes: string | null;
    status: string;
    admin_notes: string | null;
    created_at: string;
  }[];
}

export function AdminDashboard() {
  const csrf = syncCsrfTokenFromCookie() ?? undefined;
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const section = adminSectionFromPath(pathname);
  const [message, setMessage] = useState<string | null>(null);
  const [instrumentQuery, setInstrumentQuery] = useState("AAPL");
  useEffect(() => {
    syncCsrfTokenFromCookie();
  }, []);
  const query = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: () => apiGet<AdminDashboardPayload>("/api/admin/dashboard")
  });
  const instrumentSearch = useQuery({
    queryKey: ["admin-instruments-search", instrumentQuery],
    queryFn: () => apiGet<AdminInstrumentSearchPayload>(`/api/admin/instruments/search?q=${encodeURIComponent(instrumentQuery || "A")}`),
    enabled: section === "instruments" && Boolean(query.data)
  });
  const instrumentReviews = useQuery({
    queryKey: ["admin-instrument-review-requests"],
    queryFn: () => apiGet<AdminInstrumentReviewPayload>("/api/admin/instruments/review-requests"),
    enabled: section === "instruments" && Boolean(query.data)
  });

  if (query.isLoading) {
    return <main className="grid min-h-screen place-items-center bg-paper text-ink">Loading admin dashboard</main>;
  }
  if (query.isError || !query.data) {
    return (
      <main className="grid min-h-screen place-items-center bg-paper px-4 text-ink">
        <div className="panel max-w-md p-5">
          <h1 className="text-xl font-bold">Admin session required</h1>
          <p className="mt-2 text-sm text-muted">Log in with owner/admin/editor credentials.</p>
          <Link className="primary-action mt-4" to="/admin/login">
            Login
          </Link>
        </div>
      </main>
    );
  }

  async function buildSnapshot() {
    setMessage(null);
    try {
      await apiPost("/api/admin/snapshots/build", {}, csrf);
      setMessage("Snapshot build job queued.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to queue snapshot build");
    }
  }

  async function buildCandidateNow() {
    setMessage(null);
    try {
      const result = await apiPost<{ snapshot_version: number }>("/api/admin/snapshots/build-now-local", {}, csrf);
      setMessage(`Snapshot candidate v${result.snapshot_version} built.`);
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to build candidate");
    }
  }

  async function publishSnapshot(snapshotVersion: number) {
    setMessage(null);
    try {
      await apiPost("/api/admin/snapshots/publish", { snapshot_version: snapshotVersion }, csrf);
      setMessage(`Snapshot v${snapshotVersion} published.`);
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to publish snapshot");
    }
  }

  async function rollbackSnapshot(snapshotVersion: number) {
    setMessage(null);
    try {
      await apiPost("/api/admin/snapshots/rollback", { snapshot_version: snapshotVersion }, csrf);
      setMessage(`Snapshot pointer rolled back to v${snapshotVersion}.`);
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to rollback snapshot");
    }
  }

  async function toggleKillSwitch(budgetId: string, enabled: boolean) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/provider-budgets/${encodeURIComponent(budgetId)}/kill-switch`, { enabled }, csrf);
      setMessage(enabled ? "Provider kill switch enabled." : "Provider kill switch disabled.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to change kill switch");
    }
  }

  async function replayJob(jobId: string) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/jobs/${encodeURIComponent(jobId)}/replay`, {}, csrf);
      setMessage("Dead-letter job queued for replay.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to replay job");
    }
  }

  async function reviewFact(factId: string, decision: string, publicAllowed: boolean) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/source-facts/${encodeURIComponent(factId)}/review`, { decision, public_allowed: publicAllowed }, csrf);
      setMessage("Fact review saved.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to review fact");
    }
  }

  async function reviewEvent(eventId: string, decision: string, publicAllowed: boolean) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/events/${encodeURIComponent(eventId)}/review`, { decision, public_allowed: publicAllowed }, csrf);
      setMessage("Event review saved.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to review event");
    }
  }

  async function updateInstrumentReview(requestId: string, status: string) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/instruments/review-requests/${encodeURIComponent(requestId)}`, { status }, csrf);
      setMessage("Instrument review request updated.");
      await instrumentReviews.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to update instrument review request");
    }
  }

  async function refreshInstrumentIndex() {
    setMessage(null);
    try {
      const result = await apiPost<{ job_id: string; refresh?: { instrument_count?: number; listing_count?: number } }>(
        "/api/admin/instruments/refresh",
        { source: "CONFIGURED_INDEX", mode: "INCREMENTAL", priority: "HIGH" },
        csrf
      );
      setMessage(`Instrument index cache refreshed (${result.refresh?.instrument_count ?? "?"} instruments); worker sync queued: ${result.job_id}`);
      await instrumentSearch.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to queue instrument refresh");
    }
  }

  async function quarantineRelease(releaseId: string) {
    setMessage(null);
    try {
      const result = await apiPost<{ source_documents: number; source_facts: number; market_bars: number }>(
        "/api/admin/release-controls/quarantine",
        { release_id: releaseId },
        csrf
      );
      setMessage(
        `Quarantined release rows: ${result.source_documents} documents, ${result.source_facts} facts, ${result.market_bars} market bars.`
      );
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to quarantine release rows");
    }
  }

  return (
    <main className="min-h-screen bg-paper px-4 py-6 text-ink lg:px-6">
      <div className="mx-auto grid max-w-7xl gap-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Admin Console</h1>
            <p className="mt-1 text-sm text-muted">
              {query.data.user.email} · {query.data.user.role} · {adminSectionTitle(section)}
            </p>
          </div>
          <button
            onClick={buildSnapshot}
            className="primary-action h-10 px-4 py-0"
          >
            <RefreshCw className="h-4 w-4" />
            Build Snapshot
          </button>
          <button
            onClick={buildCandidateNow}
            className="secondary-action h-10 px-4 py-0"
          >
            <RefreshCw className="h-4 w-4" />
            Build Candidate Now
          </button>
        </header>
        {message ? <div className="signal-warning p-3 text-sm">{message}</div> : null}
        <nav className="scroll-fade-x flex gap-2 overflow-x-auto pb-2" data-allow-horizontal-scroll aria-label="Admin sections">
          {adminSections.map(([key, label, href]) => (
            <Link
              key={key}
              to={href}
              className={`focus-ring inline-flex min-h-11 shrink-0 items-center rounded-md border px-3 text-sm font-semibold ${
                section === key ? "border-accent bg-accentSoft text-accent" : "border-line bg-panel text-muted hover:border-accent hover:text-ink"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
        {(section === "overview" || section === "usage" || section === "system-config") && (
          <section className="grid gap-4 md:grid-cols-4">
            {Object.entries(query.data.metrics).map(([key, value]) => (
              <div key={key} className="panel p-4">
                <div className="text-xs uppercase text-muted">{key.replaceAll("_", " ")}</div>
                <div className="mt-2 text-2xl font-bold">{String(value ?? "n/a")}</div>
              </div>
            ))}
          </section>
        )}
        {(section === "overview" || section === "system-config") && query.data.release_controls ? (
          <ReleaseControlsPanel releaseControls={query.data.release_controls} quarantineRelease={quarantineRelease} />
        ) : null}
        {section === "feature-gates" ? <FeatureGateAdminPanel /> : null}
        {section === "instruments" && (
          <InstrumentAdminPanel
            query={instrumentQuery}
            setQuery={setInstrumentQuery}
            search={instrumentSearch.data}
            reviews={instrumentReviews.data}
            loading={instrumentSearch.isLoading || instrumentReviews.isLoading}
            updateReview={updateInstrumentReview}
            refreshIndex={refreshInstrumentIndex}
          />
        )}
        {section === "users" || section === "usage" ? <UsageAdminPanel currentUser={query.data.user} /> : null}
        {(section === "jobs" || section === "queues" || section === "overview") && (
          <section className="grid gap-4 lg:grid-cols-2">
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold">
              <Database className="h-4 w-4" />
              Provider budgets
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <tbody className="divide-y divide-line">
                  {query.data.provider_budgets.map((budget) => (
                    <tr key={budget.id}>
                      <td className="py-3 font-semibold">{budget.provider_key}</td>
                      <td className="py-3">{budget.routing_mode}</td>
                      <td className="py-3">{budget.kill_switch_enabled ? "kill switch on" : "enabled"}</td>
                      <td className="py-3 text-right">
                        <button
                          onClick={() => toggleKillSwitch(budget.id, !budget.kill_switch_enabled)}
                          className="secondary-action px-2 py-1 text-xs"
                        >
                          {budget.kill_switch_enabled ? "Enable" : "Kill"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 flex items-center gap-2 font-semibold">
              <AlertTriangle className="h-4 w-4" />
              Dead-letter jobs
            </div>
            <div className="grid gap-2 text-sm">
              {query.data.dead_letter_jobs.length === 0 ? (
                <div className="text-muted">No dead-letter jobs.</div>
              ) : (
                query.data.dead_letter_jobs.map((job) => (
                  <div key={job.id} className="rounded-md border border-line p-3">
                    <div className="font-semibold">{job.job_type}</div>
                    <div className="text-muted">{job.last_error_message}</div>
                    <button
                      onClick={() => replayJob(job.id)}
                      className="secondary-action mt-2 px-2 py-1 text-xs"
                    >
                      Replay
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
          </section>
        )}
        {(section === "data-sources" || section === "overview" || section === "system-config") && (
          <section className="panel p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <Database className="h-4 w-4" />
            Source health
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <tbody className="divide-y divide-line">
                <SourceHealthRows sources={query.data.source_health} />
              </tbody>
            </table>
          </div>
          </section>
        )}
        {(section === "data-sources" || section === "overview") && query.data.news_v2 ? (
          <NewsV2Panel news={query.data.news_v2} />
        ) : null}
        {section === "overview" && (
          <section className="grid gap-4 lg:grid-cols-2">
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Fact review</div>
            <div className="grid gap-2 text-sm">
              {query.data.candidate_facts.length === 0 ? (
                <div className="text-muted">No candidate facts.</div>
              ) : (
                query.data.candidate_facts.map((fact) => (
                  <div key={fact.id} className="rounded-md border border-line p-3">
                    <div className="font-semibold">{fact.fact_type}</div>
                    <div className="text-muted">{fact.predicate} · {fact.extraction_source}</div>
                    <button onClick={() => reviewFact(fact.id, "approved", false)} className="secondary-action mt-2 mr-2 px-2 py-1 text-xs">Approve Private</button>
                    <button onClick={() => reviewFact(fact.id, "approved", true)} className="secondary-action mt-2 px-2 py-1 text-xs">Approve Public</button>
                  </div>
                ))
              )}
            </div>
          </div>
          <div className="panel p-4">
            <div className="mb-3 font-semibold">Event review</div>
            <div className="grid gap-2 text-sm">
              {query.data.candidate_events.length === 0 ? (
                <div className="text-muted">No candidate events.</div>
              ) : (
                query.data.candidate_events.map((event) => (
                  <div key={event.id} className="rounded-md border border-line p-3">
                    <div className="font-semibold">{event.event_key}</div>
                    <div className="text-muted">{event.severity} · {event.source_strength}</div>
                    <button onClick={() => reviewEvent(event.id, "approved", false)} className="secondary-action mt-2 mr-2 px-2 py-1 text-xs">Approve Private</button>
                    <button onClick={() => reviewEvent(event.id, approvalDecisionForSeverity(event.severity), true)} className="secondary-action mt-2 px-2 py-1 text-xs">Approve Public</button>
                  </div>
                ))
              )}
            </div>
          </div>
          </section>
        )}
        {(section === "overview" || section === "jobs" || section === "queues") && (
          <section className="panel p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <RefreshCw className="h-4 w-4" />
            Snapshot candidates
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <tbody className="divide-y divide-line">
                {query.data.snapshot_candidates.length === 0 ? (
                  <tr>
                    <td className="py-3 text-muted">No snapshot candidates yet.</td>
                  </tr>
                ) : (
                  query.data.snapshot_candidates.map((candidate) => (
                    <tr key={candidate.snapshot_version}>
                      <td className="py-3 font-semibold">v{candidate.snapshot_version}</td>
                      <td className="py-3">{candidate.publication_status}</td>
                      <td className="py-3">{new Date(candidate.generated_at).toLocaleString()}</td>
                      <td className="py-3 text-right">
                        <button
                          onClick={() => publishSnapshot(candidate.snapshot_version)}
                          className="secondary-action mr-2 px-2 py-1 text-xs"
                        >
                          Publish
                        </button>
                        <button
                          onClick={() => rollbackSnapshot(candidate.snapshot_version)}
                          className="secondary-action px-2 py-1 text-xs"
                        >
                          Rollback
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          </section>
        )}
      </div>
    </main>
  );
}

type AdminSection = "overview" | "feature-gates" | "users" | "usage" | "jobs" | "queues" | "data-sources" | "instruments" | "system-config";

const adminSections: readonly (readonly [AdminSection, string, string])[] = [
  ["overview", "Overview", "/admin"],
  ["feature-gates", "Feature gates", "/admin/feature-gates"],
  ["users", "Users", "/admin/users"],
  ["usage", "Usage", "/admin/usage"],
  ["jobs", "Jobs", "/admin/jobs"],
  ["queues", "Queues", "/admin/queues"],
  ["data-sources", "Data sources", "/admin/data-sources"],
  ["instruments", "Instruments", "/admin/instruments"],
  ["system-config", "System config", "/admin/system-config"]
];

function adminSectionFromPath(pathname: string): AdminSection {
  if (pathname.endsWith("/feature-gates")) return "feature-gates";
  if (pathname.endsWith("/users")) return "users";
  if (pathname.endsWith("/usage")) return "usage";
  if (pathname.endsWith("/jobs")) return "jobs";
  if (pathname.endsWith("/queues")) return "queues";
  if (pathname.endsWith("/data-sources")) return "data-sources";
  if (pathname.endsWith("/instruments")) return "instruments";
  if (pathname.endsWith("/system-config")) return "system-config";
  return "overview";
}

function adminSectionTitle(section: AdminSection) {
  return adminSections.find(([key]) => key === section)?.[1] ?? "Overview";
}

function approvalDecisionForSeverity(severity: string) {
  if (severity === "critical") return "owner_approved";
  if (severity === "high") return "editor_approved";
  return "approved";
}

function responseTimeLabel(responseMs: number | null) {
  if (responseMs == null) return "n/a";
  return `${responseMs} ms`;
}

function NewsV2Panel({ news }: Readonly<{ news: NonNullable<AdminDashboardPayload["news_v2"]> }>) {
  const totals = news.totals;

  return (
    <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="panel p-4">
        <div className="mb-3 flex items-center gap-2 font-semibold">
          <Database className="h-4 w-4" />
          News V2 pipeline
        </div>
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
          <MetricChip label="Clusters" value={totals.clusters} />
          <MetricChip label="Documents" value={totals.source_documents} />
          <MetricChip label="Facts" value={totals.source_facts} />
          <MetricChip label="Quarantined docs" value={totals.quarantined_documents} />
          <MetricChip label="Quarantined facts" value={totals.quarantined_facts} />
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="py-2 pr-4">Cluster</th>
                <th className="py-2 pr-4">State</th>
                <th className="py-2 pr-4">Sources</th>
                <th className="py-2">Last seen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {news.clusters.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-3 text-muted">
                    No News V2 clusters yet.
                  </td>
                </tr>
              ) : (
                news.clusters.map((cluster) => (
                  <tr key={cluster.id}>
                    <td className="safe-text py-3 pr-4 font-semibold">{cluster.canonical_title}</td>
                    <td className="py-3 pr-4">
                      {cluster.review_state} · {cluster.status}
                    </td>
                    <td className="py-3 pr-4">{cluster.source_count}</td>
                    <td className="py-3 text-muted">{formatOptionalDate(cluster.last_seen_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid gap-4">
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Recent source documents</div>
          <div className="grid gap-2 text-sm">
            {news.source_documents.length === 0 ? (
              <div className="text-muted">No source documents yet.</div>
            ) : (
              news.source_documents.map((document) => (
                <div key={document.id} className="rounded-md border border-line bg-panelAlt p-3">
                  <div className="safe-text font-semibold">{document.title || "Untitled source document"}</div>
                  <div className="safe-text text-xs text-muted">
                    {document.source_key ?? "unknown source"} · {document.publisher ?? "unknown publisher"} · {document.status} ·{" "}
                    {document.public_allowed ? "public allowed" : "private/admin only"}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Ingestion runs</div>
          <div className="grid gap-2 text-sm">
            {news.ingestion_runs.length === 0 ? (
              <div className="text-muted">No ingestion run provenance recorded.</div>
            ) : (
              news.ingestion_runs.map((run) => (
                <div key={run.ingestion_run_id} className="grid grid-cols-[1fr_auto] gap-3 rounded-md border border-line bg-panelAlt p-3">
                  <span className="safe-text font-semibold">{run.ingestion_run_id}</span>
                  <span>{run.row_count}</span>
                  <span className="text-muted">Newest row</span>
                  <span className="text-muted">{formatOptionalDate(run.newest_at)}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function MetricChip({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <div className="rounded-md border border-line bg-panelAlt p-3">
      <div className="text-xs uppercase text-muted">{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}

function formatOptionalDate(value: string | null) {
  if (!value) return "n/a";
  return new Date(value).toLocaleString();
}

function ReleaseControlsPanel({
  releaseControls,
  quarantineRelease
}: Readonly<{
  releaseControls: NonNullable<AdminDashboardPayload["release_controls"]>;
  quarantineRelease: (releaseId: string) => void;
}>) {
  const funnelTotals = releaseControls.source_funnel.totals;

  return (
    <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="panel p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Release readiness</div>
            <p className="mt-1 text-sm text-muted">
              Release {releaseControls.release_id} · payload v{releaseControls.payload_version} · canary {releaseControls.canary.status}
            </p>
          </div>
          <span className={`rounded-md border px-3 py-1 text-sm font-semibold ${statusClass(releaseControls.canary.status)}`}>
            {releaseControls.canary.status}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <tbody className="divide-y divide-line">
              {releaseControls.canary.checks.map((check) => (
                <tr key={check.key}>
                  <td className="py-3 font-semibold">{check.key.replaceAll("_", " ")}</td>
                  <td className="py-3">{String(check.value ?? "n/a")}</td>
                  <td className="py-3 text-muted">{String(check.threshold ?? "n/a")}</td>
                  <td className={`py-3 font-semibold ${statusTextClass(check.status)}`}>{check.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid gap-4">
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Runtime rollback switches</div>
          <div className="flex flex-wrap gap-2">
            {releaseControls.runtime_switches.map((item) => (
              <span key={item.key} className="rounded-md border border-line bg-panelSoft px-2 py-1 text-xs">
                {item.key}: {item.enabled ? "on" : "off"}
              </span>
            ))}
          </div>
        </div>
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Source funnel totals</div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {Object.entries(funnelTotals).map(([key, value]) => (
              <div key={key} className="rounded-md border border-line p-2">
                <div className="text-xs uppercase text-muted">{key.replaceAll("_", " ")}</div>
                <div className="font-bold">{value}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="panel p-4">
          <div className="mb-3 font-semibold">Provenance cleanup estimate</div>
          <p className="text-sm text-muted">
            Documents {releaseControls.provenance.source_documents} · facts {releaseControls.provenance.source_facts} · market bars{" "}
            {releaseControls.provenance.market_bars}
          </p>
          <p className="mt-2 text-xs text-muted">
            Rollback cleanup is {releaseControls.provenance.quarantine_available ? "available" : "disabled for local/unknown releases"}.
          </p>
          <button
            type="button"
            className="secondary-action mt-3 h-10 px-3 py-0"
            disabled={!releaseControls.provenance.quarantine_available}
            onClick={() => quarantineRelease(releaseControls.provenance.release_id)}
          >
            Quarantine release rows
          </button>
        </div>
      </div>
    </section>
  );
}

function statusClass(status: string) {
  if (status === "ready" || status === "pass") return "border-success text-success";
  if (status === "blocked") return "border-danger text-danger";
  return "border-warning text-warning";
}

function statusTextClass(status: string) {
  if (status === "pass") return "text-success";
  if (status === "blocked") return "text-danger";
  return "text-warning";
}

function SourceHealthRows({ sources }: Readonly<{ sources: AdminDashboardPayload["source_health"] }>) {
  if (sources.length === 0) {
    return (
      <tr>
        <td className="py-3 text-muted">No source health checks recorded.</td>
      </tr>
    );
  }

  return sources.map((source) => (
    <tr key={source.source_key}>
      <td className="py-3 font-semibold">{source.source_key}</td>
      <td className="py-3">{source.status}</td>
      <td className="py-3">{source.status_code ?? "n/a"}</td>
      <td className="py-3">{responseTimeLabel(source.response_ms)}</td>
    </tr>
  ));
}

function InstrumentAdminPanel({
  query,
  setQuery,
  search,
  reviews,
  loading,
  updateReview,
  refreshIndex
}: Readonly<{
  query: string;
  setQuery: (value: string) => void;
  search?: AdminInstrumentSearchPayload;
  reviews?: AdminInstrumentReviewPayload;
  loading: boolean;
  updateReview: (requestId: string, status: string) => void;
  refreshIndex: () => void;
}>) {
  return (
    <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Instrument search</div>
            <p className="mt-1 text-sm text-muted">Local autocomplete index; no external provider calls are made from keystrokes.</p>
          </div>
          <button type="button" className="secondary-action h-10 px-3 py-0" onClick={refreshIndex}>
            <RefreshCw className="h-4 w-4" />
            Refresh cache
          </button>
        </div>
        <input
          className="input-control mt-4 w-full"
          maxLength={64}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search ticker, company, ISIN, FIGI, or local code"
        />
        <div className="mt-3 text-xs text-muted">
          Index {search?.dataFreshness?.status?.toLowerCase() ?? "status unknown"} · updated{" "}
          {search?.dataFreshness?.instrumentIndexLastUpdatedAt ?? "n/a"}
        </div>
        <div className="mt-4 grid gap-2">
          {loading ? <div className="rounded-md border border-line bg-panelAlt p-3 text-sm text-muted">Loading instruments...</div> : null}
          {(search?.results ?? []).map((item) => (
            <div key={`${item.instrumentId}:${item.listingId}`} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-semibold">{item.displaySymbol}</div>
                  <div className="text-sm text-muted">{item.name}</div>
                </div>
                <div className="text-right text-xs text-muted">
                  <div>{item.exchange} · {item.country} · {item.currency}</div>
                  <div>{item.assetClass} · {item.instrumentType} · {item.qualityLevel}</div>
                </div>
              </div>
            </div>
          ))}
          {!loading && !(search?.results ?? []).length ? (
            <div className="rounded-md border border-line bg-panelAlt p-3 text-sm text-muted">No instruments found.</div>
          ) : null}
        </div>
      </div>
      <div className="panel p-4">
        <div className="font-semibold">Missing instrument review queue</div>
        <p className="mt-1 text-sm text-muted">Requests created by no-result searches. Resolve after adding or confirming metadata.</p>
        <div className="mt-4 grid gap-2">
          {(reviews?.items ?? []).map((item) => (
            <div key={item.id} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="safe-text font-semibold">{item.query}</div>
                  <div className="safe-text text-xs text-muted">{item.context_screen} · {item.status} · {new Date(item.created_at).toLocaleString()}</div>
                  {item.optional_notes ? <p className="safe-text mt-2 text-xs text-muted">{item.optional_notes}</p> : null}
                </div>
                <div className="flex shrink-0 gap-2">
                  <button className="secondary-action px-2 py-1 text-xs" onClick={() => updateReview(item.id, "in_review")}>Review</button>
                  <button className="secondary-action px-2 py-1 text-xs" onClick={() => updateReview(item.id, "resolved")}>Resolve</button>
                </div>
              </div>
            </div>
          ))}
          {!loading && !(reviews?.items ?? []).length ? (
            <div className="rounded-md border border-line bg-panelAlt p-3 text-sm text-muted">No pending review requests.</div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function FeatureGateAdminPanel() {
  return (
    <section className="panel p-4">
      <div className="mb-3 font-semibold">Feature gates</div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <tbody className="divide-y divide-line">
            {featureGates.map((gate) => (
              <tr key={gate.key}>
                <td className="py-3 font-semibold">{gate.displayName}</td>
                <td className="py-3">{gate.enabledGlobally ? "global on" : "global off"}</td>
                <td className="py-3">{gate.enabledForFreeUsers ? "free allowed" : "free blocked"}</td>
                <td className="py-3">{gate.rolloutPercentage}% rollout</td>
                <td className="py-3 text-muted">{gate.enabledForAdmins ? "admin eligible" : "admin blocked"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UsageAdminPanel({ currentUser }: Readonly<{ currentUser: { email: string; role: string } }>) {
  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="panel p-4">
        <div className="mb-3 font-semibold">Users</div>
        <div className="rounded-md border border-line bg-panelAlt p-3 text-sm">
          <div className="font-semibold">{currentUser.email}</div>
          <div className="text-muted">{currentUser.role} · authenticated server session</div>
        </div>
      </div>
      <div className="panel p-4">
        <div className="mb-3 font-semibold">Usage quotas</div>
        <div className="grid gap-2 text-sm">
          {usageQuotas.map((quota) => (
            <div key={quota.resource} className="grid grid-cols-[1fr_auto] gap-3 rounded-md border border-line bg-panelAlt p-3">
              <span className="font-semibold">{quota.resource}</span>
              <span>{quota.used} / {quota.freeUserDefault}</span>
              <span className="text-muted">Admin limit</span>
              <span className="text-muted">{quota.adminDefault}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
