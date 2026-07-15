import type { AssumptionSet, Instrument, Portfolio } from "./portfolioAtlas";
import { defaultAssumptions } from "./portfolioAtlas";
import { syncCsrfTokenFromCookie } from "./api";

export type ReviewRequestStatus = "queued" | "in-review" | "resolved" | "closed";

export type InstrumentReviewRequest = {
  requestId: string;
  userId: string;
  query: string;
  contextScreen: "HOLDING_ENTRY" | "BUILDER";
  optionalNotes?: string;
  createdAt: string;
  status: ReviewRequestStatus;
};

export type StoredPortfolioWorkspace = {
  version: number;
  portfolio: Portfolio;
  manualInstruments: Instrument[];
  reviewRequests: InstrumentReviewRequest[];
  assumptions: AssumptionSet;
};

export type ManualHoldingDraftFields = {
  symbolOrCode: string;
  name: string;
  currency: string;
  assetClass: string;
  quantityText: string;
  priceText: string;
  marketValueText: string;
};

type ServerPortfolioWorkspaceResponse = {
  portfolio_id?: string;
  workspace?: Partial<StoredPortfolioWorkspace>;
  updated_at?: string;
};

export const PORTFOLIO_WORKSPACE_STORAGE_VERSION = 1;
export const PORTFOLIO_WORKSPACE_STORAGE_PREFIX = "stonks-radar:portfolio-workspace:";
export const MANUAL_TEXT_MAX_LENGTH = 96;
export const MANUAL_MONEY_MAX = 1_000_000_000_000;
export const MANUAL_QUANTITY_MAX = 1_000_000_000;

export function toSafeId(value: string) {
  const safe = value.trim().toLowerCase().replace(/[^a-z0-9]/g, "-").replace(/-+/g, "-");
  return safe.replace(/^-|-$/g, "") || "holding";
}

export function workspaceStorageKey(portfolioId: string) {
  return `${PORTFOLIO_WORKSPACE_STORAGE_PREFIX}${toSafeId(portfolioId)}`;
}

export function canPersistWorkspace(portfolioId: string) {
  const normalized = portfolioId.trim();
  return normalized.length > 0 && normalized.length <= 100;
}

export function loadPortfolioWorkspace(portfolioId: string): StoredPortfolioWorkspace | null {
  if (!canPersistWorkspace(portfolioId)) return null;
  if (globalThis.window === undefined) return null;
  try {
    const raw = globalThis.window.localStorage.getItem(workspaceStorageKey(portfolioId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPortfolioWorkspace>;
    return normalizeStoredWorkspace(parsed);
  } catch {
    return null;
  }
}

export function savePortfolioWorkspace(
  portfolioId: string,
  workspace: Omit<StoredPortfolioWorkspace, "version">
) {
  if (!canPersistWorkspace(portfolioId)) return;
  if (globalThis.window === undefined) return;
  try {
    globalThis.window.localStorage.setItem(
      workspaceStorageKey(portfolioId),
      JSON.stringify({ version: PORTFOLIO_WORKSPACE_STORAGE_VERSION, ...workspace })
    );
  } catch {
    // Browser storage may be disabled or full; the workspace still functions as an in-memory session.
  }
}

export async function loadServerPortfolioWorkspace(
  portfolioId: string,
  signal?: AbortSignal
): Promise<StoredPortfolioWorkspace | null> {
  const response = await fetch(serverWorkspacePath(portfolioId), {
    credentials: "include",
    headers: { Accept: "application/json" },
    signal
  });
  if (response.status === 401 || response.status === 403 || response.status === 404) return null;
  if (!response.ok) return null;
  const payload = (await response.json()) as ServerPortfolioWorkspaceResponse;
  return normalizeStoredWorkspace(payload.workspace);
}

export async function saveServerPortfolioWorkspace(
  portfolioId: string,
  workspace: Omit<StoredPortfolioWorkspace, "version">,
  signal?: AbortSignal
): Promise<boolean> {
  const csrfToken = syncCsrfTokenFromCookie();
  if (!csrfToken) return false;
  try {
    const response = await fetch(serverWorkspacePath(portfolioId), {
      method: "PUT",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "x-csrf-token": csrfToken
      },
      body: JSON.stringify({
        workspace: {
          version: PORTFOLIO_WORKSPACE_STORAGE_VERSION,
          ...workspace
        }
      }),
      signal
    });
    return response.ok;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return false;
  }
}

export function clearSourceLinkedRecords(portfolio: Portfolio): Portfolio {
  if (!portfolio.transactions.length && !portfolio.taxLots.length) return portfolio;
  return { ...portfolio, transactions: [], taxLots: [] };
}

export function cleanManualText(value: string) {
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MANUAL_TEXT_MAX_LENGTH);
}

export function cleanCurrency(value: string) {
  const normalized = value.trim().toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
  return /^[A-Z]{3}$/.test(normalized) ? normalized : "USD";
}

export function validateManualDraft(draft: ManualHoldingDraftFields): string[] {
  const errors: string[] = [];
  const symbol = cleanManualText(draft.symbolOrCode);
  const name = cleanManualText(draft.name);
  const currency = draft.currency.trim().toUpperCase();
  const quantity = Number(draft.quantityText);
  const price = draft.priceText.trim() ? Number(draft.priceText) : undefined;
  const marketValue = draft.marketValueText.trim() ? Number(draft.marketValueText) : undefined;
  if (!symbol) errors.push("Symbol or local code is required.");
  if (!name) errors.push("Instrument name is required.");
  if (!/^[A-Z]{3}$/.test(currency)) errors.push("Currency must be a 3-letter ISO-style code such as USD, KRW, or JPY.");
  if (!draft.assetClass) errors.push("Asset class is required.");
  if (!Number.isFinite(quantity) || quantity <= 0 || quantity > MANUAL_QUANTITY_MAX) {
    errors.push("Quantity must be a positive finite number.");
  }
  if (price !== undefined && (!Number.isFinite(price) || price < 0 || price > MANUAL_MONEY_MAX)) {
    errors.push("Price must be a non-negative finite number.");
  }
  if (marketValue !== undefined && (!Number.isFinite(marketValue) || marketValue < 0 || marketValue > MANUAL_MONEY_MAX)) {
    errors.push("Market value must be a non-negative finite number.");
  }
  if (price === undefined && marketValue === undefined) {
    errors.push("Enter either price or market value so the holding is visible in portfolio value.");
  }
  return errors;
}

export function manualNumberInvalid(value: string, numeric: number, required: boolean, min: number, max: number) {
  const hasInput = value.trim().length > 0;
  if (!required && !hasInput) return false;
  return !Number.isFinite(numeric) || numeric < min || numeric > max;
}

function normalizeStoredWorkspace(parsed: Partial<StoredPortfolioWorkspace> | null | undefined): StoredPortfolioWorkspace | null {
  if (parsed?.version !== PORTFOLIO_WORKSPACE_STORAGE_VERSION || !parsed.portfolio) return null;
  const portfolio = removeLegacySamplePortfolioData(parsed.portfolio);
  return {
    version: PORTFOLIO_WORKSPACE_STORAGE_VERSION,
    portfolio,
    manualInstruments: parsed.manualInstruments ?? [],
    reviewRequests: parsed.reviewRequests ?? [],
    assumptions: parsed.assumptions ?? defaultAssumptions
  };
}

const legacySampleTransactionIds = new Set([
  "t-deposit-1",
  "t-aapl-1",
  "t-msft-1",
  "t-vxus-1",
  "t-tlt-1",
  "t-gld-1",
  "t-btc-1"
]);

const legacySampleTaxLotIds = new Set([
  "lot-aapl-1",
  "lot-aapl-2",
  "lot-msft-1",
  "lot-vxus-1",
  "lot-tlt-1",
  "lot-gld-1",
  "lot-btc-1"
]);

function removeLegacySamplePortfolioData(portfolio: Portfolio): Portfolio {
  const hasLegacySamples = portfolio.holdings.some((holding) => holding.source === "sample");
  if (!hasLegacySamples) return portfolio;

  return {
    ...portfolio,
    cashBalance: portfolio.cashBalance === 6_500 ? 0 : portfolio.cashBalance,
    holdings: portfolio.holdings.filter((holding) => holding.source !== "sample"),
    transactions: portfolio.transactions.filter(
      (transaction) => !legacySampleTransactionIds.has(transaction.transactionId)
    ),
    taxLots: portfolio.taxLots.filter((lot) => !legacySampleTaxLotIds.has(lot.lotId))
  };
}

function serverWorkspacePath(portfolioId: string) {
  return `/api/portfolio-workspaces/${encodeURIComponent(toSafeId(portfolioId))}`;
}
