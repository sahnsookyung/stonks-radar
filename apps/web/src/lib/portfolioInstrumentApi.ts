import type { Instrument, InstrumentSearchResult } from "./portfolioAtlas";

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

type InstrumentResolveResponse = {
  status: "MATCHED" | "MULTIPLE_MATCHES" | "NO_MATCH";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  matches: InstrumentSearchResult[];
};

type InstrumentDetailResponse = {
  instrumentId?: string;
  symbol?: string;
  name?: string;
  assetClass?: string;
  instrumentType?: string;
  country?: string;
  currency?: string;
  sector?: string;
  isActive?: boolean;
  dataQualityLevel?: InstrumentSearchResult["qualityLevel"];
  dataQualityMessage?: string;
  listings?: Array<{
    listingId?: string;
    displaySymbol?: string;
    exchangeCode?: string;
    country?: string;
    tradingCurrency?: string;
    isPrimaryListing?: boolean;
    isActive?: boolean;
  }>;
};

type SearchRequest = {
  query: string;
  limit?: number;
  includeAdvanced?: boolean;
  includeInactive?: boolean;
  context: InstrumentSearchContext;
};

type ResolveRequest = {
  symbol: string;
  name?: string;
  exchange?: string;
  currency?: string;
  context: InstrumentSearchContext;
};

type ReviewRequest = {
  query: string;
  contextScreen: InstrumentSearchContext;
  optionalNotes?: string;
};

const instrumentTypes: ReadonlySet<Instrument["instrumentType"]> = new Set([
  "stock",
  "etf",
  "bond",
  "cash",
  "crypto",
  "manual",
  "leveraged"
]);

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

export async function enrichPortfolioInstrumentSelection(
  result: InstrumentSearchResult,
  context: InstrumentSearchContext,
  signal?: AbortSignal
): Promise<InstrumentSearchResult> {
  const resolved = await resolvePortfolioInstrument(
    {
      symbol: result.displaySymbol,
      name: result.name,
      exchange: result.exchange,
      currency: result.currency,
      context
    },
    signal
  );
  const resolvedResult = bestResolvedMatch(result, resolved.matches) ?? result;
  const detail = await getPortfolioInstrumentDetail(resolvedResult.instrumentId, resolvedResult.listingId, signal);
  return detail ? mergeDetailIntoSearchResult(resolvedResult, detail) : resolvedResult;
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

async function resolvePortfolioInstrument(
  request: ResolveRequest,
  signal?: AbortSignal
): Promise<InstrumentResolveResponse> {
  return fetchJson<InstrumentResolveResponse>("/api/instruments/resolve", {
    method: "POST",
    body: JSON.stringify({
      symbol: request.symbol,
      name: request.name,
      exchange: request.exchange,
      currency: request.currency,
      context: request.context
    }),
    headers: { "Content-Type": "application/json" },
    signal
  });
}

async function getPortfolioInstrumentDetail(
  instrumentId: string,
  listingId: string,
  signal?: AbortSignal
): Promise<InstrumentDetailResponse | null> {
  const params = listingId ? `?listing_id=${encodeURIComponent(listingId)}` : "";
  const response = await fetch(`/api/instruments/${encodeURIComponent(instrumentId)}${params}`, {
    credentials: "include",
    headers: { Accept: "application/json" },
    signal
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Instrument detail failed: ${response.status}`);
  return (await response.json()) as InstrumentDetailResponse;
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

function bestResolvedMatch(
  requested: InstrumentSearchResult,
  matches: InstrumentSearchResult[]
): InstrumentSearchResult | null {
  return (
    matches.find((match) => match.listingId === requested.listingId) ??
    matches.find((match) => match.instrumentId === requested.instrumentId) ??
    matches[0] ??
    null
  );
}

function mergeDetailIntoSearchResult(
  result: InstrumentSearchResult,
  detail: InstrumentDetailResponse
): InstrumentSearchResult {
  const listing =
    detail.listings?.find((item) => item.listingId === result.listingId) ??
    detail.listings?.find((item) => item.isPrimaryListing) ??
    detail.listings?.[0];
  const instrumentType = normalizeInstrumentType(detail.instrumentType, result.instrumentType);
  const sourceProviders = Array.from(new Set([...result.sourceProviders, "phoenix_instruments_api"]));

  return {
    ...result,
    instrumentId: detail.instrumentId ?? result.instrumentId,
    listingId: listing?.listingId ?? result.listingId,
    displaySymbol: listing?.displaySymbol ?? detail.symbol ?? result.displaySymbol,
    name: detail.name ?? result.name,
    exchange: listing?.exchangeCode ?? result.exchange,
    country: listing?.country ?? detail.country ?? result.country,
    currency: listing?.tradingCurrency ?? detail.currency ?? result.currency,
    assetClass: detail.assetClass ?? result.assetClass,
    instrumentType,
    sector: detail.sector ?? result.sector,
    isPrimaryListing: listing?.isPrimaryListing ?? result.isPrimaryListing,
    isActive: listing?.isActive ?? detail.isActive ?? result.isActive,
    qualityLevel: detail.dataQualityLevel ?? result.qualityLevel,
    qualityMessage: detail.dataQualityMessage ?? result.qualityMessage,
    sourceProviders
  };
}

function normalizeInstrumentType(
  value: string | undefined,
  fallback: Instrument["instrumentType"]
): Instrument["instrumentType"] {
  return value && instrumentTypes.has(value as Instrument["instrumentType"])
    ? (value as Instrument["instrumentType"])
    : fallback;
}
