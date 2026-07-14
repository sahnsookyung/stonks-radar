import type { InstrumentSearchResult } from "./portfolioAtlas";

export type InstrumentSearchApiResponse = {
  results: InstrumentSearchResult[];
  warnings?: string[];
  cache?: string;
  dataFreshness?: {
    instrumentIndexLastUpdatedAt?: string;
    observedAt?: string;
    status?: string;
    stalenessState?: string;
    ageSeconds?: number | null;
    staleAfter?: string | null;
    hardExpiresAt?: string | null;
    source?: string;
  };
};

export type InstrumentSearchContext = "HOLDING_ENTRY" | "TAX_LOT" | "BUILDER" | "IMPORT_RECONCILIATION" | "CSV_IMPORT";

export type InstrumentReviewApiResponse = {
  id?: string;
  status?: string;
  deduped?: boolean;
};

type SearchRequest = {
  query: string;
  limit?: number;
  includeAdvanced?: boolean;
  includeInactive?: boolean;
  context: InstrumentSearchContext;
};

type ReviewRequest = {
  query: string;
  contextScreen: InstrumentSearchContext;
  optionalNotes?: string;
};

export async function searchPortfolioInstruments(
  request: SearchRequest,
  signal?: AbortSignal
): Promise<InstrumentSearchApiResponse> {
  const params = new URLSearchParams({
    q: request.query,
    limit: String(request.limit ?? 10),
    include_advanced: String(request.includeAdvanced ?? false),
    include_inactive: String(request.includeInactive ?? false),
    context: request.context
  });
  return fetchJson<InstrumentSearchApiResponse>(`/api/instruments/search?${params.toString()}`, {
    method: "GET",
    signal
  });
}

export async function createPortfolioInstrumentReviewRequest(
  request: ReviewRequest,
  signal?: AbortSignal
): Promise<InstrumentReviewApiResponse> {
  return fetchJson<InstrumentReviewApiResponse>("/api/instruments/review-requests", {
    method: "POST",
    body: JSON.stringify({
      query: request.query,
      context_screen: request.contextScreen,
      optional_notes: request.optionalNotes
    }),
    headers: { "Content-Type": "application/json" },
    signal
  });
}

async function fetchJson<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/json", ...init.headers },
    ...init
  });
  if (!response.ok) throw new Error(`Instrument API failed: ${response.status}`);
  return (await response.json()) as T;
}
