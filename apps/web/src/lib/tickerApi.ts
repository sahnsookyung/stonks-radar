import { syncCsrfTokenFromCookie } from "./api";
import type { AlertDraft } from "./tickerWorkspace";

export class TickerApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly responseStatus?: string
  ) {
    super(detail);
    this.name = "TickerApiError";
  }
}

export type FundamentalMetrics = {
  revenue: number | null;
  revenue_growth: number | null;
  operating_margin: number | null;
  net_margin: number | null;
  net_income: number | null;
  free_cash_flow: number | null;
  cash: number | null;
  debt: number | null;
  shares: number | null;
  dilution: number | null;
  valuation_ratios: Record<string, number | null> | null;
  missing_reasons: Record<string, string>;
};

export type TickerFundamentals = {
  symbol: string;
  cik: string | null;
  status: "ready" | "stale" | "unavailable";
  coverage_reason: string | null;
  metrics: FundamentalMetrics;
  period_end: string | null;
  form: string | null;
  filing_url: string | null;
  source_filed_at: string | null;
  fetched_at: string | null;
  stale_after: string | null;
  provenance?: Record<string, unknown>;
};

export type PrivateOptionRow = {
  symbol: string | null;
  expiration: string | null;
  side: string | null;
  strike: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  volume: number | null;
  open_interest: number | null;
  implied_volatility: number | null;
  delta: number | null;
  underlying_price: number | null;
};

export type PrivateOptionsResponse = {
  status: "ready" | "empty";
  symbol: string;
  delay: string;
  as_of: string | number | null;
  chain: PrivateOptionRow[];
  cache?: "hit" | "miss";
};

export type PrivateHistoryResponse = {
  status: "ready" | "empty";
  symbol: string;
  delay: string;
  as_of: string | number | null;
  points: Array<{ time: string | number; open: number | null; high: number | null; low: number | null; close: number | null; volume: number | null }>;
  cache?: "hit" | "miss";
};

export type ProviderConnection = {
  provider: "marketdata_app";
  status: "not_connected" | "verified" | "verification_failed";
  verified_at?: string | null;
  last_verified_at?: string | null;
};

export type TickerAlertRule = AlertDraft & {
  id: string;
  active: boolean;
  created_at?: string;
  updated_at?: string;
};

export type TickerAlertEvent = {
  id: string;
  symbol: string;
  rule_type: string;
  reason: string;
  source_time: string | null;
  created_at: string;
  read_at: string | null;
};

export async function getTickerFundamentals(symbol: string, signal?: AbortSignal) {
  return requestJson<TickerFundamentals>(`/api/public/tickers/${encodeURIComponent(symbol)}/fundamentals`, { signal });
}

export async function getProviderConnection(signal?: AbortSignal) {
  return requestJson<ProviderConnection>("/api/member/provider-connections/marketdata-app", { signal });
}

export async function connectProvider(token: string, signal?: AbortSignal) {
  return memberWrite<ProviderConnection>("/api/member/provider-connections/marketdata-app", "POST", { token }, signal);
}

export async function deleteProviderConnection(signal?: AbortSignal) {
  return memberWrite<{ status: "deleted" }>("/api/member/provider-connections/marketdata-app", "DELETE", undefined, signal);
}

export async function getPrivateOptions(symbol: string, expiration?: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ symbol });
  if (expiration) params.set("expiration", expiration);
  return requestJson<PrivateOptionsResponse>(`/api/member/market/options?${params}`, { signal });
}

export async function getPrivateHistory(symbol: string, from: string, to: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ symbol, from, to });
  return requestJson<PrivateHistoryResponse>(`/api/member/market/history?${params}`, { signal });
}

export async function listTickerAlertRules(signal?: AbortSignal) {
  return requestJson<{ rules: TickerAlertRule[] }>("/api/member/ticker-alert-rules", { signal });
}

export async function createTickerAlertRule(draft: AlertDraft, signal?: AbortSignal) {
  return memberWrite<TickerAlertRule>("/api/member/ticker-alert-rules", "POST", draft, signal);
}

export async function updateNotificationPreferences(locale: "en" | "ko", emailOptIn: boolean, signal?: AbortSignal) {
  return memberWrite<{ locale: "en" | "ko"; email_opt_in: boolean; unsubscribed_at: string | null }>(
    "/api/member/notification-preferences",
    "PUT",
    { locale, email_opt_in: emailOptIn },
    signal
  );
}

export async function listTickerAlertEvents(signal?: AbortSignal) {
  return requestJson<{ events: TickerAlertEvent[] }>("/api/member/ticker-alert-events", { signal });
}

export function memberSignInUrl(redirectPath: string) {
  return `/api/auth/google/member/start?${new URLSearchParams({ redirect_to: redirectPath })}`;
}

async function memberWrite<T>(path: string, method: string, body?: unknown, signal?: AbortSignal) {
  const csrf = syncCsrfTokenFromCookie();
  if (!csrf) throw new TickerApiError(401, "Member sign-in is required");
  return requestJson<T>(path, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json", "x-csrf-token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal
  });
}

async function requestJson<T>(path: string, init: RequestInit) {
  const response = await fetch(path, {
    credentials: "include",
    headers: { Accept: "application/json", ...init.headers },
    ...init
  });
  const payload = (await response.json().catch(() => ({}))) as { detail?: unknown; status?: string };
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : `Request failed: ${response.status}`;
    throw new TickerApiError(response.status, detail, payload.status);
  }
  return payload as T;
}
