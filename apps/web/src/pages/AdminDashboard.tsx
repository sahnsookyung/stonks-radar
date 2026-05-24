import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, Database, RefreshCw } from "lucide-react";
import { useState } from "react";
import { apiGet, apiPost } from "../lib/api";

interface AdminDashboardPayload {
  user: { email: string; role: string };
  metrics: Record<string, string | number | boolean | null>;
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

export function AdminDashboard() {
  const csrf = sessionStorage.getItem("frw_csrf") ?? undefined;
  const [message, setMessage] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: () => apiGet<AdminDashboardPayload>("/api/admin/dashboard")
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
      await apiPost(`/api/admin/provider-budgets/${budgetId}/kill-switch`, { enabled }, csrf);
      setMessage(enabled ? "Provider kill switch enabled." : "Provider kill switch disabled.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to change kill switch");
    }
  }

  async function replayJob(jobId: string) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/jobs/${jobId}/replay`, {}, csrf);
      setMessage("Dead-letter job queued for replay.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to replay job");
    }
  }

  async function reviewFact(factId: string, decision: string, publicAllowed: boolean) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/source-facts/${factId}/review`, { decision, public_allowed: publicAllowed }, csrf);
      setMessage("Fact review saved.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to review fact");
    }
  }

  async function reviewEvent(eventId: string, decision: string, publicAllowed: boolean) {
    setMessage(null);
    try {
      await apiPost(`/api/admin/events/${eventId}/review`, { decision, public_allowed: publicAllowed }, csrf);
      setMessage("Event review saved.");
      await query.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to review event");
    }
  }

  return (
    <main className="min-h-screen bg-paper px-4 py-6 text-ink lg:px-6">
      <div className="mx-auto grid max-w-7xl gap-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Admin Console</h1>
            <p className="mt-1 text-sm text-muted">
              {query.data.user.email} · {query.data.user.role}
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
        <section className="grid gap-4 md:grid-cols-4">
          {Object.entries(query.data.metrics).map(([key, value]) => (
            <div key={key} className="panel p-4">
              <div className="text-xs uppercase text-muted">{key.replaceAll("_", " ")}</div>
              <div className="mt-2 text-2xl font-bold">{String(value ?? "n/a")}</div>
            </div>
          ))}
        </section>
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
        <section className="panel p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <Database className="h-4 w-4" />
            Source health
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <tbody className="divide-y divide-line">
                {query.data.source_health.length === 0 ? (
                  <tr>
                    <td className="py-3 text-muted">No source health checks recorded.</td>
                  </tr>
                ) : (
                  query.data.source_health.map((source) => (
                    <tr key={source.source_key}>
                      <td className="py-3 font-semibold">{source.source_key}</td>
                      <td className="py-3">{source.status}</td>
                      <td className="py-3">{source.status_code ?? "n/a"}</td>
                      <td className="py-3">{source.response_ms == null ? "n/a" : `${source.response_ms} ms`}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
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
                    <button onClick={() => reviewEvent(event.id, event.severity === "critical" ? "owner_approved" : event.severity === "high" ? "editor_approved" : "approved", true)} className="secondary-action mt-2 px-2 py-1 text-xs">Approve Public</button>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
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
      </div>
    </main>
  );
}
