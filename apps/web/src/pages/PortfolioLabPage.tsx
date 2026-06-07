import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BriefcaseBusiness,
  Calculator,
  DatabaseZap,
  FileSpreadsheet,
  Globe2,
  Layers3,
  LineChart,
  Lock,
  PieChart,
  Search,
  Loader2,
  Plus,
  RefreshCcw,
  ShieldCheck,
  Target,
  Trash2,
  Upload,
  WalletCards
} from "lucide-react";
import {
  type Dispatch,
  type KeyboardEvent,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useId,
  useMemo,
  useState
} from "react";
import { TermTooltip } from "../components/TermTooltip";
import {
  type AssumptionSet,
  type ExposureRow,
  type Instrument,
  type AssetClass,
  type Portfolio,
  type TaxLotImpact,
  type InstrumentSearchResult,
  analyzePortfolio,
  calculateFundOverlap,
  createDemoPortfolio,
  defaultAssumptions,
  demoInstruments,
  INSTRUMENT_SEARCH_QUERY_MAX_LENGTH,
  instrumentFromSearchResult,
  instrumentReferenceKeys,
  resolveInstrumentReference,
  resolveInstrumentSearchResult,
  searchInstruments,
  estimateTaxLotImpact,
  generateContributionRebalancePlan,
  runBacktest,
  runMonteCarlo,
  validateHoldingsCsv
} from "../lib/portfolioAtlas";
import { useLocale } from "../lib/locale";
import { portfolioTerms } from "../lib/portfolioTerms";

type PortfolioSection =
  | "onboarding"
  | "dashboard"
  | "portfolios"
  | "overview"
  | "xray"
  | "atlas"
  | "builder"
  | "backtest"
  | "monte-carlo"
  | "rebalance"
  | "fees"
  | "tax-lots"
  | "holdings"
  | "transactions"
  | "settings-profile"
  | "settings-assumptions"
  | "settings-data-sources"
  | "settings-security"
  | "glossary";

const sectionLabels: Record<PortfolioSection, string> = {
  onboarding: "Onboarding",
  dashboard: "Cockpit",
  portfolios: "Portfolios",
  overview: "Overview",
  xray: "X-ray",
  atlas: "Exposure map",
  builder: "Portfolio builder",
  backtest: "Backtest",
  "monte-carlo": "Monte Carlo",
  rebalance: "Rebalance",
  fees: "Fees",
  "tax-lots": "Tax lots",
  holdings: "Holdings",
  transactions: "Transactions",
  "settings-profile": "Profile",
  "settings-assumptions": "Assumptions",
  "settings-data-sources": "Data sources",
  "settings-security": "Security",
  glossary: "Glossary"
};

type ReviewRequestStatus = "queued" | "in-review" | "resolved" | "closed";
type ManualEditorContext = "HOLDING_ENTRY" | "BUILDER";
type ManualInstrumentType = "" | Instrument["instrumentType"];

type ManualHoldingPayload = {
  symbolOrCode: string;
  name: string;
  currency: string;
  assetClass: AssetClass;
  instrumentType?: ManualInstrumentType;
  exchange?: string;
  country?: string;
  quantity: number;
  price?: number;
  marketValue?: number;
};

type AddHoldingPayload = {
  instrumentId: string;
  listingId?: string;
  searchResult?: InstrumentSearchResult;
  manual?: ManualHoldingPayload;
};

type ManualHoldingDraft = {
  symbolOrCode: string;
  name: string;
  currency: string;
  assetClass: AssetClass;
  instrumentType: ManualInstrumentType;
  exchange: string;
  country: string;
  quantityText: string;
  priceText: string;
  marketValueText: string;
};

type InstrumentReviewRequest = {
  requestId: string;
  userId: string;
  query: string;
  contextScreen: ManualEditorContext;
  optionalNotes?: string;
  createdAt: string;
  status: ReviewRequestStatus;
};

type InstrumentSearchApiResponse = {
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

type MarketHistoryCoverageStatus = "idle" | "loading" | "ready" | "partial" | "limited" | "error";

type MarketHistoryCoverageState = {
  status: MarketHistoryCoverageStatus;
  requestedSymbols: string[];
  coveredSymbols: string[];
  missingSymbols: string[];
  queuedSymbols: string[];
  latestPricesBySymbol: Record<string, StoredMarketHistoryPrice>;
  provider?: string;
  cache?: string;
  completeThrough?: string | null;
  stalenessState?: string | null;
  calculationEligible?: boolean;
  sourcePolicy?: string;
  message: string;
  warnings: string[];
};

type StoredMarketHistoryPrice = {
  close: number;
  date: string;
  provider: string;
  currency?: string;
  exchange?: string;
  timezone?: string;
  calculationEligible: boolean;
  stalenessState?: string | null;
};

type MarketHistoryCoverageResponse = {
  status: string;
  provider?: string;
  cache?: string;
  display_status?: string;
  data_freshness?: {
    complete_through?: string | null;
    staleness_state?: string | null;
    calculation_eligible?: boolean;
    staleness_reason?: string;
  };
  symbols?: string[];
  series?: Array<{
    symbol: string;
    providers?: string[];
    points?: Array<{ date?: string; close?: number; adjusted_close?: number; currency?: string; exchange?: string; timezone?: string }>;
  }>;
  warnings?: string[];
};

type AdminAuthState =
  | { status: "checking" }
  | { status: "signed_out" }
  | { status: "signed_in"; email: string; role: string };

const PORTFOLIO_WORKSPACE_STORAGE_VERSION = 1;
const PORTFOLIO_WORKSPACE_STORAGE_PREFIX = "stonks-radar:portfolio-workspace:";
const MANUAL_TEXT_MAX_LENGTH = 96;
const MANUAL_MONEY_MAX = 1_000_000_000_000;
const MANUAL_QUANTITY_MAX = 1_000_000_000;

const ASSET_CLASS_OPTIONS: AssetClass[] = [
  "Cash & Cash Equivalents",
  "Fixed Income",
  "Equity",
  "Real Assets",
  "Alternatives",
  "Crypto / Digital Assets",
  "Derivatives / Leveraged Products",
  "Other Assets",
  "Liabilities"
];

const MANUAL_INSTRUMENT_TYPE_OPTIONS: ManualInstrumentType[] = ["", "stock", "etf", "bond", "cash", "crypto", "manual", "leveraged"];

interface PortfolioBuildControls {
  updateCashBalance: (value: number) => void;
  updateHoldingQuantity: (holdingId: string, quantity: number) => void;
  updateHoldingManualPrice: (holdingId: string, price?: number) => void;
  updateHoldingManualMarketValue: (holdingId: string, marketValue?: number) => void;
  removeHolding: (holdingId: string) => void;
  addHolding: (holding: AddHoldingPayload) => void;
  resetPortfolio: () => void;
}

type PortfolioEditorControls = PortfolioBuildControls & {
  assumptions?: AssumptionSet;
  updateGoal?: <K extends keyof Portfolio["goal"]>(key: K, value: Portfolio["goal"][K]) => void;
  setAssumptions?: Dispatch<SetStateAction<AssumptionSet>>;
};

export function PortfolioLabPage() {
  const locale = useLocale();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const section = sectionFromPath(pathname);
  const workspacePortfolioId = portfolioIdFromPath(pathname) ?? "demo-growth-income";
  const initialWorkspace = loadPortfolioWorkspace(workspacePortfolioId);
  const [loadedWorkspaceId, setLoadedWorkspaceId] = useState(workspacePortfolioId);
  const [portfolio, setPortfolio] = useState<Portfolio>(() => initialWorkspace?.portfolio ?? createPortfolioForWorkspace(workspacePortfolioId));
  const [manualInstruments, setManualInstruments] = useState<Instrument[]>(() => initialWorkspace?.manualInstruments ?? []);
  const [reviewRequests, setReviewRequests] = useState<InstrumentReviewRequest[]>(() => initialWorkspace?.reviewRequests ?? []);
  const [assumptions, setAssumptions] = useState<AssumptionSet>(() => initialWorkspace?.assumptions ?? defaultAssumptions);
  const [csvText, setCsvText] = useState("symbol,quantity,price\nAAPL,10,195.40\nVXUS,30,62.10");
  const [csvErrors, setCsvErrors] = useState<string[]>([]);
  const instrumentsCatalog = useMemo(() => [...demoInstruments, ...manualInstruments], [manualInstruments]);
  const marketHistorySymbols = useMemo(
    () => marketHistorySymbolsForPortfolio(portfolio, instrumentsCatalog),
    [instrumentsCatalog, portfolio]
  );
  const [marketHistoryCoverage, setMarketHistoryCoverage] = useState<MarketHistoryCoverageState>(() =>
    emptyMarketHistoryCoverage(marketHistorySymbols)
  );
  const [adminAuthState, setAdminAuthState] = useState<AdminAuthState>({ status: "checking" });
  const calculationInstruments = useMemo(
    () => applyStoredMarketHistoryPrices(instrumentsCatalog, marketHistoryCoverage),
    [instrumentsCatalog, marketHistoryCoverage]
  );
  const analysis = useMemo(() => analyzePortfolio(portfolio, calculationInstruments, assumptions), [portfolio, assumptions, calculationInstruments]);
  const shouldRunBacktest = section === "backtest";
  const monteCarloPathCount = section === "monte-carlo" ? 5000 : section === "dashboard" || section === "overview" ? 1000 : 0;
  const backtest = useMemo<ReturnType<typeof runBacktest> | null>(
    () => {
      if (!shouldRunBacktest) return null;
      return runBacktest({
        portfolio,
        instruments: calculationInstruments,
        assumptions,
        analysis,
        years: 10,
        monthlyContribution: portfolio.goal.monthlyContribution
      });
    },
    [analysis, assumptions, calculationInstruments, portfolio, shouldRunBacktest]
  );
  const monteCarlo = useMemo<ReturnType<typeof runMonteCarlo> | null>(
    () => {
      if (!monteCarloPathCount) return null;
      return runMonteCarlo({ portfolio, instruments: calculationInstruments, assumptions, analysis, pathCount: monteCarloPathCount, seed: 20260531 });
    },
    [analysis, assumptions, calculationInstruments, monteCarloPathCount, portfolio]
  );
  const rebalancePlan = useMemo(
    () => generateContributionRebalancePlan(analysis, portfolio.targetAllocation, portfolio.goal.monthlyContribution, assumptions),
    [analysis, assumptions, portfolio.goal.monthlyContribution, portfolio.targetAllocation]
  );
  const taxImpact = useMemo(
    () => estimateTaxLotImpact(portfolio.taxLots, calculationInstruments, "AAPL", 10, "LOWEST_GAIN_FIRST"),
    [calculationInstruments, portfolio.taxLots]
  );

  useEffect(() => {
    const saved = loadPortfolioWorkspace(workspacePortfolioId);
    setPortfolio(saved?.portfolio ?? createPortfolioForWorkspace(workspacePortfolioId));
    setManualInstruments(saved?.manualInstruments ?? []);
    setReviewRequests(saved?.reviewRequests ?? []);
    setAssumptions(saved?.assumptions ?? defaultAssumptions);
    setLoadedWorkspaceId(workspacePortfolioId);
  }, [workspacePortfolioId]);

  useEffect(() => {
    if (loadedWorkspaceId !== workspacePortfolioId) return;
    savePortfolioWorkspace(workspacePortfolioId, { portfolio, manualInstruments, reviewRequests, assumptions });
  }, [assumptions, loadedWorkspaceId, manualInstruments, portfolio, reviewRequests, workspacePortfolioId]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch("/api/auth/me", {
          credentials: "include",
          headers: { Accept: "application/json" },
          signal: controller.signal
        });
        if (!response.ok) {
          setAdminAuthState({ status: "signed_out" });
          return;
        }
        const payload = (await response.json()) as { email?: string; role?: string };
        if (!payload.email) {
          setAdminAuthState({ status: "signed_out" });
          return;
        }
        setAdminAuthState({
          status: "signed_in",
          email: payload.email,
          role: payload.role ?? "admin"
        });
      } catch (_error) {
        if (!controller.signal.aborted) {
          setAdminAuthState({ status: "signed_out" });
        }
      }
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const symbols = marketHistorySymbols;
    if (!symbols.length) {
      setMarketHistoryCoverage(emptyMarketHistoryCoverage(symbols));
      return;
    }
    const controller = new AbortController();
    const { start, end } = rollingThreeYearHistoryWindow();
    setMarketHistoryCoverage({
      status: "loading",
      requestedSymbols: symbols,
      coveredSymbols: [],
      missingSymbols: symbols,
      queuedSymbols: symbols,
      latestPricesBySymbol: {},
      message: "Checking stored public daily-history snapshots...",
      warnings: []
    });
    void (async () => {
      try {
        const batches = chunkMarketHistorySymbols(symbols);
        const payloads: MarketHistoryCoverageResponse[] = [];
        for (const batch of batches) {
          const response = await fetch(
            `/api/public/market/history?symbols=${encodeURIComponent(batch.join(","))}&start=${start}&end=${end}`,
            {
              credentials: "include",
              headers: { Accept: "application/json" },
              signal: controller.signal
            }
          );
          if (!response.ok) throw new Error(`coverage request failed: ${response.status}`);
          payloads.push((await response.json()) as MarketHistoryCoverageResponse);
        }
        if (!controller.signal.aborted) {
          setMarketHistoryCoverage(mergeMarketHistoryCoverage(payloads, symbols));
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setMarketHistoryCoverage({
          status: "error",
          requestedSymbols: symbols,
          coveredSymbols: [],
          missingSymbols: symbols,
          queuedSymbols: symbols,
          latestPricesBySymbol: {},
          message: "Stored market-history coverage is temporarily unavailable.",
          warnings: [
            "Calculations remain limited to the editable portfolio's current/manual prices until stored daily bars are available.",
            "The public page does not fetch live provider data or spend quota during this check."
          ]
        });
      }
    })();
    return () => controller.abort();
  }, [marketHistorySymbols]);

  function updateGoal<K extends keyof Portfolio["goal"]>(key: K, value: Portfolio["goal"][K]) {
    setPortfolio((current) => ({ ...current, goal: { ...current.goal, [key]: value } }));
  }

  function updateTarget(assetClass: string, value: number) {
    setPortfolio((current) => ({
      ...current,
      targetAllocation: { ...current.targetAllocation, [assetClass]: Math.max(0, value) / 100 }
    }));
  }

  function updateCashBalance(value: number) {
    setPortfolio((current) => ({ ...current, cashBalance: Math.max(0, value) }));
  }

  function updateHoldingQuantity(holdingId: string, quantity: number) {
    setPortfolio((current) => ({
      ...clearSourceLinkedRecords(current),
      holdings: current.holdings.map((holding) =>
        holding.holdingId === holdingId ? { ...holding, quantity: Math.max(0, quantity), source: "manual" } : holding
      )
    }));
  }

  function updateHoldingManualPrice(holdingId: string, price?: number) {
    setPortfolio((current) => ({
      ...clearSourceLinkedRecords(current),
      holdings: current.holdings.map((holding) =>
        holding.holdingId === holdingId
          ? { ...holding, manualPrice: price, manualMarketValue: undefined, source: "manual" }
          : holding
      )
    }));
  }

  function updateHoldingManualMarketValue(holdingId: string, marketValue?: number) {
    setPortfolio((current) => ({
      ...clearSourceLinkedRecords(current),
      holdings: current.holdings.map((holding) =>
        holding.holdingId === holdingId
          ? { ...holding, manualMarketValue: marketValue, manualPrice: undefined, source: "manual" }
          : holding
      )
    }));
  }

  function removeHolding(holdingId: string) {
    setPortfolio((current) => ({
      ...clearSourceLinkedRecords(current),
      holdings: current.holdings.filter((holding) => holding.holdingId !== holdingId)
    }));
  }

  function addHolding({ instrumentId, listingId, searchResult, manual }: AddHoldingPayload) {
    const normalizedInput = instrumentId.trim().toUpperCase();
    if (!normalizedInput) return;
    const manualInstrumentId = manual ? `manual:${normalizedInstrumentId(normalizedInput)}` : normalizedInput;
    const instrument = manual ? undefined : resolveInstrumentReference(normalizedInput, instrumentsCatalog);
    const sourceBackedInstrument = !manual && !instrument && searchResult ? instrumentFromSearchResult(searchResult) : undefined;
    const effectiveInstrument = instrument ?? sourceBackedInstrument;
    const canonicalInstrumentId = manual ? manualInstrumentId : effectiveInstrument?.instrumentId ?? normalizedInput;
    if (currentHoldingAlreadyExists(portfolio, canonicalInstrumentId, listingId)) return;
    if (manual) {
      setManualInstruments((current) => [
        ...current.filter((item) => item.instrumentId !== manualInstrumentId),
        createManualInstrumentFromInput(manual, manualInstrumentId)
      ]);
    } else if (sourceBackedInstrument) {
      setManualInstruments((current) => [
        ...current.filter((item) => item.instrumentId !== sourceBackedInstrument.instrumentId),
        sourceBackedInstrument
      ]);
    }
    setPortfolio((current) => {
      if (currentHoldingAlreadyExists(current, canonicalInstrumentId, listingId)) return current;
      const quantity = manual
        ? manual.quantity
        : effectiveInstrument?.instrumentType === "crypto"
          ? 0.05
          : effectiveInstrument
            ? effectiveInstrument.currentPrice >= 500
              ? 1
              : effectiveInstrument.currentPrice > 0
                ? 10
                : 1
            : 1;
      const normalizedHoldingId = toSafeId(`${canonicalInstrumentId}`);
      return {
        ...clearSourceLinkedRecords(current),
        holdings: [
          ...current.holdings,
          {
            holdingId: `manual-${normalizedHoldingId}`,
            portfolioId: current.portfolioId,
            accountId: "taxable",
            instrumentId: canonicalInstrumentId,
            listingId: listingId ?? canonicalInstrumentId,
            quantity,
            currency: manual?.currency?.toUpperCase() ?? effectiveInstrument?.currency ?? "USD",
            manualPrice: manual?.price,
            manualMarketValue: manual?.marketValue,
            source: "manual"
          }
        ]
      };
    });
  }

  function createManualInstrumentFromInput(manual: ManualHoldingPayload, instrumentId: string): Instrument {
    const symbol = cleanManualText(manual.symbolOrCode).toUpperCase() || "MANUAL";
    const currency = cleanCurrency(manual.currency);
    const country = cleanManualText(manual.country || "Unknown") || "Unknown";
    const exchange = cleanManualText(manual.exchange || "Manual") || "Manual";
    const hasManualPrice = manual.marketValue !== undefined || manual.price !== undefined;
    const marketPrice = manual.marketValue !== undefined && manual.quantity > 0 ? manual.marketValue / manual.quantity : manual.price ?? 0;
    const listingId = `${exchange}:${symbol}`;
    return {
      instrumentId,
      symbol,
      name: cleanManualText(manual.name) || symbol,
      exchange,
      instrumentType: manual.instrumentType || "manual",
      assetClass: manual.assetClass,
      subAssetClass: "User-provided",
      country,
      domicileCountry: country,
      currency,
      sector: "Unclassified",
      industry: "Unclassified",
      theme: ["User-provided"],
      expenseRatio: 0,
      dataQualityScore: hasManualPrice ? 0.4 : 0.2,
      currentPrice: marketPrice,
      previousClose: marketPrice,
      priceAsOf: new Date().toISOString().slice(0, 10),
      priceQuality: hasManualPrice ? "USER_PROVIDED" : "UNAVAILABLE",
      identifiers: [{ type: "LOCAL_CODE", value: symbol }],
      aliases: [cleanManualText(manual.name)].filter(Boolean),
      listings: [{ listingId, symbol, exchange, country, currency, localCode: symbol, isPrimary: true, isActive: true }],
      primaryListingId: listingId,
      isActive: true
    };
  }

  function currentHoldingAlreadyExists(currentPortfolio: Portfolio, instrumentIdentifier: string, listingId?: string) {
    return currentPortfolio.holdings.some((holding) =>
      listingId ? holding.listingId === listingId : holding.instrumentId === instrumentIdentifier
    );
  }

  function requestInstrumentReview(query: string, contextScreen: ManualEditorContext) {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) return;
    const requestId = `review-${toSafeId(normalizedQuery)}-${Date.now()}`;
    setReviewRequests((current) => {
      if (
        current.some(
          (item) => item.query.toLowerCase() === normalizedQuery.toLowerCase() && item.contextScreen === contextScreen && item.status === "queued"
        )
      ) {
        return current;
      }
      return [
        ...current,
        {
          requestId,
          userId: "demo-user",
          query: normalizedQuery,
          contextScreen,
          createdAt: new Date().toISOString(),
          status: "queued"
        }
      ];
    });
    void fetch("/api/instruments/review-requests", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: normalizedQuery, context_screen: contextScreen })
    }).catch(() => {
      // Local review state is retained when the API is unavailable in static/demo mode.
    });
  }

  function resetPortfolio() {
    setPortfolio(createPortfolioForWorkspace(workspacePortfolioId));
    setManualInstruments([]);
    setReviewRequests([]);
    setCsvErrors([]);
  }

  function importCsv() {
    const result = validateHoldingsCsv(csvText, {
      portfolioId: portfolio.portfolioId,
      knownSymbols: instrumentsCatalog.flatMap(instrumentReferenceKeys),
      rejectUnknownSymbols: false,
      maxBytes: 1_000_000,
      maxRows: 500
    });
    setCsvErrors(result.errors);
    if (!result.errors.length && result.holdings.length) {
      setPortfolio((current) => ({
        ...clearSourceLinkedRecords(current),
        holdings: result.holdings.map((holding) => ({
          ...holding,
          portfolioId: current.portfolioId,
          ...(() => {
            const resolved = resolveInstrumentSearchResult(holding.instrumentId, instrumentsCatalog);
            return resolved
              ? {
                  instrumentId: resolved.instrumentId,
                  listingId: resolved.listingId,
                  currency: resolved.currency
                }
              : { instrumentId: holding.instrumentId };
          })()
        }))
      }));
    }
  }

  return (
    <div className="grid min-w-0 gap-6">
      <PortfolioHeader portfolio={portfolio} section={section} />
      <PortfolioNav active={section} portfolioId={portfolio.portfolioId} />
      <ComplianceBanner />
      <PortfolioCoverageBanner
        analysis={analysis}
        marketHistoryCoverage={marketHistoryCoverage}
        adminAuthState={adminAuthState}
      />

      {section === "onboarding" ? (
        <OnboardingSection csvText={csvText} setCsvText={setCsvText} csvErrors={csvErrors} importCsv={importCsv} />
      ) : null}
      {(section === "dashboard" || section === "overview") && monteCarlo ? (
        <EditablePortfolioWorkspace
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          setAssumptions={setAssumptions}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          contextScreen="BUILDER"
          reviewRequests={reviewRequests}
          requestInstrumentReview={(query) => requestInstrumentReview(query, "BUILDER")}
        >
          <DashboardSection portfolio={portfolio} analysis={analysis} monteCarlo={monteCarlo} rebalancePlan={rebalancePlan} />
        </EditablePortfolioWorkspace>
      ) : null}
      {section === "portfolios" ? <PortfoliosSection portfolio={portfolio} analysis={analysis} /> : null}
      {section === "xray" || section === "atlas" ? (
        <AtlasSection
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          reviewRequests={reviewRequests}
          onRequestInstrumentReview={(query) => requestInstrumentReview(query, "HOLDING_ENTRY")}
        />
      ) : null}
      {section === "builder" ? (
        <BuilderSection
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          updateTarget={updateTarget}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          reviewRequests={reviewRequests}
          onRequestInstrumentReview={(query) => requestInstrumentReview(query, "BUILDER")}
        />
      ) : null}
      {section === "backtest" && backtest ? (
        <EditablePortfolioWorkspace
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          setAssumptions={setAssumptions}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          contextScreen="BUILDER"
          reviewRequests={reviewRequests}
          requestInstrumentReview={(query) => requestInstrumentReview(query, "BUILDER")}
        >
          <BacktestSection result={backtest} />
        </EditablePortfolioWorkspace>
      ) : null}
      {section === "monte-carlo" && monteCarlo ? (
        <EditablePortfolioWorkspace
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          setAssumptions={setAssumptions}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          contextScreen="BUILDER"
          reviewRequests={reviewRequests}
          requestInstrumentReview={(query) => requestInstrumentReview(query, "BUILDER")}
        >
          <MonteCarloSection result={monteCarlo} portfolio={portfolio} updateGoal={updateGoal} />
        </EditablePortfolioWorkspace>
      ) : null}
      {section === "rebalance" ? (
        <EditablePortfolioWorkspace
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          setAssumptions={setAssumptions}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          contextScreen="BUILDER"
          reviewRequests={reviewRequests}
          requestInstrumentReview={(query) => requestInstrumentReview(query, "BUILDER")}
        >
          <RebalanceSection plan={rebalancePlan} analysis={analysis} />
        </EditablePortfolioWorkspace>
      ) : null}
      {section === "fees" ? <FeesSection analysis={analysis} assumptions={assumptions} setAssumptions={setAssumptions} /> : null}
      {section === "tax-lots" ? <TaxLotsSection portfolio={portfolio} taxImpact={taxImpact} /> : null}
      {section === "holdings" ? (
        <EditablePortfolioWorkspace
          portfolio={portfolio}
          instrumentCatalog={calculationInstruments}
          analysis={analysis}
          assumptions={assumptions}
          updateGoal={updateGoal}
          setAssumptions={setAssumptions}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          resetPortfolio={resetPortfolio}
          contextScreen="HOLDING_ENTRY"
          reviewRequests={reviewRequests}
          requestInstrumentReview={(query) => requestInstrumentReview(query, "HOLDING_ENTRY")}
        >
          <HoldingsSection portfolio={portfolio} analysis={analysis} instrumentCatalog={calculationInstruments} />
        </EditablePortfolioWorkspace>
      ) : null}
      {section === "transactions" ? (
        <TransactionsSection portfolio={portfolio} csvText={csvText} setCsvText={setCsvText} csvErrors={csvErrors} importCsv={importCsv} />
      ) : null}
      {section.startsWith("settings") ? <SettingsSection section={section} assumptions={assumptions} setAssumptions={setAssumptions} /> : null}
      {section === "glossary" ? <GlossarySection /> : null}

      <PortfolioCoverageLedger analysis={analysis} />
      <DataQualityPanel issues={analysis.dataQualityIssues} />
    </div>
  );
}

function marketHistorySymbolsForPortfolio(portfolio: Portfolio, instruments: Instrument[]): string[] {
  const symbols: string[] = [];
  for (const holding of portfolio.holdings) {
    const instrument = resolveInstrumentReference(holding.instrumentId, instruments);
    if (!instrument || instrument.instrumentType === "cash" || instrument.instrumentType === "manual") continue;
    const listing =
      instrument.listings?.find((item) => item.listingId === holding.listingId) ??
      instrument.listings?.find((item) => item.listingId === instrument.primaryListingId) ??
      instrument.listings?.find((item) => item.isPrimary) ??
      instrument.listings?.[0];
    const symbol = (listing?.symbol ?? instrument.symbol ?? "").trim().toUpperCase();
    if (symbol && /^[A-Z0-9.\-]{1,24}$/.test(symbol)) symbols.push(symbol);
  }
  return Array.from(new Set(symbols)).sort();
}

function rollingThreeYearHistoryWindow() {
  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setUTCDate(startDate.getUTCDate() - 1095);
  return {
    start: startDate.toISOString().slice(0, 10),
    end: endDate.toISOString().slice(0, 10)
  };
}

function chunkMarketHistorySymbols(symbols: string[]): string[][] {
  const batches: string[][] = [];
  let current: string[] = [];
  let currentLength = 0;
  for (const symbol of symbols) {
    const addedLength = symbol.length + (current.length ? 1 : 0);
    if (current.length && currentLength + addedLength > 220) {
      batches.push(current);
      current = [];
      currentLength = 0;
    }
    current.push(symbol);
    currentLength += addedLength;
  }
  if (current.length) batches.push(current);
  return batches;
}

function emptyMarketHistoryCoverage(symbols: string[]): MarketHistoryCoverageState {
  return {
    status: symbols.length ? "idle" : "limited",
    requestedSymbols: symbols,
    coveredSymbols: [],
    missingSymbols: symbols,
    queuedSymbols: [],
    latestPricesBySymbol: {},
    message: symbols.length
      ? "Stored public daily-history coverage has not been checked yet."
      : "No exchange-traded holdings need stored daily-history coverage.",
    warnings: []
  };
}

function mergeMarketHistoryCoverage(
  payloads: MarketHistoryCoverageResponse[],
  requestedSymbols: string[]
): MarketHistoryCoverageState {
  const covered = new Set<string>();
  const latestPricesBySymbol: Record<string, StoredMarketHistoryPrice> = {};
  const warnings: string[] = [];
  let provider: string | undefined;
  let cache: string | undefined;
  let completeThrough: string | null | undefined;
  let stalenessState: string | null | undefined;
  let calculationEligible = false;
  let licenseLimited = false;
  for (const payload of payloads) {
    provider ??= payload.provider;
    cache ??= payload.cache;
    licenseLimited ||= payload.status === "license_limited" || payload.display_status === "license_limited";
    if (payload.data_freshness) {
      const freshness = payload.data_freshness;
      completeThrough = maxIsoDate(completeThrough, freshness.complete_through);
      stalenessState ??= freshness.staleness_state;
      calculationEligible ||= Boolean(freshness.calculation_eligible);
      if (freshness.staleness_reason) warnings.push(freshness.staleness_reason);
    }
    for (const warning of payload.warnings ?? []) warnings.push(warning);
    for (const item of payload.series ?? []) {
      const symbol = item.symbol.toUpperCase();
      if (item.points?.length) {
        covered.add(symbol);
        const latestPoint = latestMarketHistoryPoint(item.points);
        if (latestPoint) {
          const price = Number(latestPoint.adjusted_close ?? latestPoint.close);
          if (Number.isFinite(price) && price > 0) {
            latestPricesBySymbol[symbol] = {
              close: price,
              date: String(latestPoint.date).slice(0, 10),
              provider: item.providers?.[0] ?? payload.provider ?? "stored_normalized_daily_bars",
              currency: latestPoint.currency,
              exchange: latestPoint.exchange,
              timezone: latestPoint.timezone,
              calculationEligible: Boolean(payload.data_freshness?.calculation_eligible),
              stalenessState: payload.data_freshness?.staleness_state
            };
          }
        }
      }
    }
  }
  const coveredSymbols = requestedSymbols.filter((symbol) => covered.has(symbol));
  const missingSymbols = requestedSymbols.filter((symbol) => !covered.has(symbol));
  const status: MarketHistoryCoverageStatus = licenseLimited
    ? "limited"
    : missingSymbols.length === 0 && calculationEligible
      ? "ready"
      : coveredSymbols.length
        ? "partial"
        : "limited";
  const message =
    status === "ready"
      ? "Stored public 3-year daily snapshots are available for all resolved holdings."
      : status === "partial"
        ? "Some holdings have stored public daily bars; missing symbols remain queued or unavailable."
        : "No approved public daily-history snapshot is available yet for one or more holdings.";
  return {
    status,
    requestedSymbols,
    coveredSymbols,
    missingSymbols,
    queuedSymbols: missingSymbols,
    latestPricesBySymbol,
    provider,
    cache,
    completeThrough,
    stalenessState,
    calculationEligible,
    sourcePolicy: licenseLimited ? "public display blocked until an approved stored snapshot exists" : undefined,
    message,
    warnings: Array.from(new Set(warnings)).slice(0, 4)
  };
}

function latestMarketHistoryPoint(
  points: Array<{ date?: string; close?: number; adjusted_close?: number; currency?: string; exchange?: string; timezone?: string }>
) {
  return points
    .filter((point) => point.date && Number.isFinite(Number(point.adjusted_close ?? point.close)))
    .sort((left, right) => String(left.date).localeCompare(String(right.date)))
    .at(-1);
}

function applyStoredMarketHistoryPrices(instruments: Instrument[], coverage: MarketHistoryCoverageState): Instrument[] {
  if (!Object.keys(coverage.latestPricesBySymbol).length) return instruments;
  const calculationEligible =
    coverage.calculationEligible && coverage.status !== "limited" && coverage.status !== "error";
  return instruments.map((instrument) => {
    const candidateSymbols = [
      instrument.symbol,
      instrument.primaryListingId,
      ...(instrument.listings ?? []).flatMap((listing) => [listing.symbol, listing.localCode, listing.listingId])
    ]
      .filter(Boolean)
      .map((value) => String(value).toUpperCase());
    const price = candidateSymbols.map((symbol) => coverage.latestPricesBySymbol[symbol]).find(Boolean);
    if (!price) return instrument;
    const quality: Instrument["priceQuality"] =
      calculationEligible && price.calculationEligible && price.stalenessState !== "stale_fallback"
        ? "COMPLETE"
        : "STALE";
    const primaryListing = primaryListingForInstrumentLike(instrument);
    return {
      ...instrument,
      currentPrice: price.close,
      previousClose: instrument.currentPrice || price.close,
      priceAsOf: price.date,
      priceQuality: quality,
      priceCoverage: calculationEligible ? "available" : "stale",
      calculationEligible,
      sourceProviders: Array.from(new Set([...(instrument.sourceProviders ?? []), "stored_normalized_daily_bars", price.provider])),
      sourceObservedAt: price.date,
      stalenessState: quality === "STALE" ? "stale" : "fresh",
      exchange: price.exchange ?? instrument.exchange ?? primaryListing.exchange,
      currency: price.currency ?? instrument.currency ?? primaryListing.currency
    };
  });
}

function primaryListingForInstrumentLike(instrument: Instrument) {
  return (
    instrument.listings?.find((item) => item.listingId === instrument.primaryListingId) ??
    instrument.listings?.find((item) => item.isPrimary) ??
    instrument.listings?.[0] ?? {
      listingId: instrument.symbol,
      symbol: instrument.symbol,
      exchange: instrument.exchange,
      country: instrument.country,
      currency: instrument.currency,
      isActive: true,
      isPrimary: true
    }
  );
}

function maxIsoDate(left: string | null | undefined, right: string | null | undefined) {
  if (!left) return right;
  if (!right) return left;
  return right > left ? right : left;
}

function PortfolioHeader({ portfolio, section }: { portfolio: Portfolio; section: PortfolioSection }) {
  const locale = useLocale();
  return (
    <section className="panel grid gap-5 p-4 md:grid-cols-[1.5fr_1fr] md:p-5">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
          <Calculator className="h-4 w-4" />
          {locale === "ko" ? "포트폴리오 빌더" : "Portfolio Builder"}
        </div>
        <h1 className="safe-text mt-3 text-3xl font-bold leading-tight md:text-5xl">
          {sectionLabels[section]}
        </h1>
        <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
          {portfolio.name}: an editable, free-data, daily-resolution planning workspace. It tracks assumptions,
          quality limits, contribution-first rebalancing, tax-lot estimates, and queued heavy work without brokerage execution.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <StatusPill label="Mode" value={portfolio.isDemo ? "editable sample" : "private workspace"} />
        <StatusPill label="Data" value="daily/delayed" />
        <StatusPill label="Execution" value="no trading" />
        <StatusPill label="Storage" value={portfolio.isDemo ? "demo browser storage" : "in-memory only"} />
      </div>
    </section>
  );
}

function PortfolioNav({ active, portfolioId }: { active: PortfolioSection; portfolioId: string }) {
  const locale = useLocale();
  const navigate = useNavigate();
  const primary = [
    ["dashboard", "Cockpit", `/${locale}/portfolio`],
    ["portfolios", "Portfolios", `/${locale}/portfolios`],
    ["xray", "X-ray", `/${locale}/portfolios/${portfolioId}/xray`],
    ["atlas", "Exposure", `/${locale}/portfolios/${portfolioId}/atlas`],
    ["builder", "Build", `/${locale}/portfolios/${portfolioId}/builder`],
    ["backtest", "Backtest", `/${locale}/portfolios/${portfolioId}/backtest`],
    ["monte-carlo", "Monte Carlo", `/${locale}/portfolios/${portfolioId}/monte-carlo`],
    ["rebalance", "Rebalance", `/${locale}/portfolios/${portfolioId}/rebalance`],
    ["fees", "Fees", `/${locale}/portfolios/${portfolioId}/fees`],
    ["tax-lots", "Tax lots", `/${locale}/portfolios/${portfolioId}/tax-lots`],
    ["holdings", "Holdings", `/${locale}/portfolios/${portfolioId}/holdings`],
    ["transactions", "Transactions", `/${locale}/portfolios/${portfolioId}/transactions`],
    ["settings-profile", "Settings", `/${locale}/settings/profile`],
    ["glossary", "Glossary", `/${locale}/portfolio/glossary`]
  ] as const;
  return (
    <nav
      className="scroll-fade-x flex min-w-0 gap-2 overflow-x-auto pb-2"
      data-allow-horizontal-scroll
      aria-label="Portfolio workspace sections"
    >
      {primary.map(([key, label, href]) => (
        <a
          key={key}
          href={href}
          onClick={(event) => {
            event.preventDefault();
            void navigate({ to: href as never });
          }}
          className={`focus-ring inline-flex min-h-11 shrink-0 items-center justify-center rounded-md border px-3 text-sm font-semibold ${
            active === key
              ? "border-accent bg-accentSoft text-accent"
              : "border-line bg-panel text-muted hover:border-accent hover:text-ink"
          }`}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

function ComplianceBanner() {
  return (
    <div className="signal-warning min-w-0 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        <p className="safe-text text-sm font-semibold leading-6">
          Analysis and planning only. No broker execution, copy trading, leaderboards, hot-stock alerts, or buy-now language.
          Rebalancing suggestions prioritize future contributions and show assumptions, data quality, fees, and tax-estimate limits.
        </p>
      </div>
    </div>
  );
}

function PortfolioCoverageBanner({
  analysis,
  marketHistoryCoverage,
  adminAuthState
}: {
  analysis: ReturnType<typeof analyzePortfolio>;
  marketHistoryCoverage: MarketHistoryCoverageState;
  adminAuthState: AdminAuthState;
}) {
  const locale = useLocale();
  const summary = analysis.coverageSummary;
  const isBackendLimited = ["limited", "error"].includes(marketHistoryCoverage.status);
  const toneClass =
    isBackendLimited
      ? "border-warning/50 bg-warning/10 text-warning"
      : summary.qualityTier === "HIGH" && marketHistoryCoverage.status === "ready"
      ? "border-success/40 bg-success/10 text-success"
      : summary.qualityTier === "MEDIUM"
        ? "border-line bg-panelAlt text-muted"
        : "border-warning/50 bg-warning/10 text-warning";
  return (
    <section className={`rounded-md border p-4 ${toneClass}`}>
      <div className="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide">
            <DatabaseZap className="h-4 w-4" />
            Calculation data coverage
          </div>
          <p className="safe-text mt-2 text-sm leading-6">
            {summary.basisLabel}. Coverage tier {summary.qualityTier.toLowerCase()}; covered or manual weight {formatPercent(summary.coveredWeight)}.
            {summary.oldestPriceAsOf ? ` Price dates span ${summary.oldestPriceAsOf} to ${summary.latestPriceAsOf}.` : ""}
          </p>
          <p className="safe-text mt-1 text-xs leading-5 opacity-90">{summary.limitation}</p>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[520px]">
          <StatusPill label="Mode" value={analysis.marketDataMode.replaceAll("_", " ").toLowerCase()} />
          <StatusPill label="Base currency" value={analysis.baseCurrency} />
          <StatusPill label="Benchmark" value={analysis.benchmarkSymbol} />
          <StatusPill label="Basis" value="daily close" />
        </div>
      </div>
      <div className="mt-4 grid gap-3 border-t border-current/20 pt-4 lg:grid-cols-[1fr_auto] lg:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide">
            <span>Stored 3Y snapshot status</span>
            <span className="rounded border border-current/30 px-2 py-1">{marketHistoryCoverage.status.replaceAll("_", " ")}</span>
          </div>
          <p className="safe-text mt-2 text-sm leading-6">{marketHistoryCoverage.message}</p>
          {marketHistoryCoverage.missingSymbols.length ? (
            <p className="safe-text mt-1 text-xs leading-5 opacity-90">
              Missing approved history: {marketHistoryCoverage.missingSymbols.slice(0, 10).join(", ")}
              {marketHistoryCoverage.missingSymbols.length > 10 ? ` +${marketHistoryCoverage.missingSymbols.length - 10} more` : ""}.
            </p>
          ) : null}
          {marketHistoryCoverage.queuedSymbols.length ? (
            <p className="safe-text mt-1 text-xs leading-5 opacity-90">
              Refresh queue: {marketHistoryCoverage.queuedSymbols.slice(0, 8).join(", ")}
              {marketHistoryCoverage.queuedSymbols.length > 8 ? ` +${marketHistoryCoverage.queuedSymbols.length - 8} more` : ""} will be retried by the scheduled after-close jobs when quota permits.
            </p>
          ) : null}
          {marketHistoryCoverage.warnings.length ? (
            <ul className="mt-2 grid gap-1 text-xs leading-5 opacity-90">
              {marketHistoryCoverage.warnings.map((warning) => (
                <li key={warning} className="safe-text">
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5 lg:min-w-[650px]">
          <StatusPill label="Covered" value={`${marketHistoryCoverage.coveredSymbols.length}/${marketHistoryCoverage.requestedSymbols.length}`} />
          <StatusPill label="Queued" value={String(marketHistoryCoverage.queuedSymbols.length)} />
          <StatusPill label="Provider" value={marketHistoryCoverage.provider ?? "stored only"} />
          <StatusPill label="Complete through" value={marketHistoryCoverage.completeThrough ?? "pending"} />
          <StatusPill label="Eligible" value={marketHistoryCoverage.calculationEligible ? "yes" : "no"} />
        </div>
      </div>
      <div className="mt-4 grid gap-3 border-t border-current/20 pt-4 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide">
            <ShieldCheck className="h-4 w-4" />
            <span>Private admin data mode</span>
            <span className="rounded border border-current/30 px-2 py-1">
              {adminAuthState.status === "signed_in" ? "Google/admin session active" : adminAuthState.status}
            </span>
          </div>
          <p className="safe-text mt-2 text-sm leading-6">
            Public calculations use stored approved snapshots only. Google admin sign-in can unlock a private Yahoo queue for personal analysis, but those rows stay excluded from public snapshots and must be labeled private/admin-only.
          </p>
        </div>
        {adminAuthState.status === "signed_in" ? (
          <div className="grid grid-cols-2 gap-2 lg:min-w-[320px]">
            <StatusPill label="Admin" value={adminAuthState.email} />
            <StatusPill label="Role" value={adminAuthState.role} />
          </div>
        ) : (
          <Link className="secondary-action justify-center" to="/admin/login">
            {locale === "ko" ? "관리자 로그인" : "Sign in for private mode"}
          </Link>
        )}
      </div>
    </section>
  );
}

function EditablePortfolioWorkspace({
  children,
  portfolio,
  instrumentCatalog,
  analysis,
  assumptions,
  contextScreen,
  reviewRequests,
  requestInstrumentReview,
  updateCashBalance,
  updateHoldingQuantity,
  updateHoldingManualPrice,
  updateHoldingManualMarketValue,
  removeHolding,
  addHolding,
  resetPortfolio,
  updateGoal,
  setAssumptions
}: {
  children: ReactNode;
  portfolio: Portfolio;
  instrumentCatalog: Instrument[];
  analysis: ReturnType<typeof analyzePortfolio>;
  contextScreen: ManualEditorContext;
  reviewRequests: InstrumentReviewRequest[];
  requestInstrumentReview: (query: string) => void;
} & PortfolioEditorControls) {
  return (
    <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="min-w-0">{children}</div>
      <PortfolioEditorPanel
        portfolio={portfolio}
        analysis={analysis}
        assumptions={assumptions}
        instrumentCatalog={instrumentCatalog}
        contextScreen={contextScreen}
        reviewRequests={reviewRequests}
        requestInstrumentReview={requestInstrumentReview}
        updateCashBalance={updateCashBalance}
        updateHoldingQuantity={updateHoldingQuantity}
        updateHoldingManualPrice={updateHoldingManualPrice}
        updateHoldingManualMarketValue={updateHoldingManualMarketValue}
        removeHolding={removeHolding}
        addHolding={addHolding}
        resetPortfolio={resetPortfolio}
        updateGoal={updateGoal}
        setAssumptions={setAssumptions}
      />
    </section>
  );
}

function DashboardSection({
  portfolio,
  analysis,
  monteCarlo,
  rebalancePlan
}: {
  portfolio: Portfolio;
  analysis: ReturnType<typeof analyzePortfolio>;
  monteCarlo: ReturnType<typeof runMonteCarlo>;
  rebalancePlan: ReturnType<typeof generateContributionRebalancePlan>;
}) {
  const nextContribution = rebalancePlan.cashContributionPlan[0];
  return (
    <section className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <CockpitCard icon={<WalletCards />} title="Portfolio value" termKey="portfolio_value" value={formatMoney(analysis.portfolioValue)} detail="Current value plus user-entered cash" />
        <CockpitCard icon={<Target />} title="Goal status" termKey="success_probability" value={formatPercent(monteCarlo.successProbability)} detail={`${formatMoney(monteCarlo.medianOutcome)} median projection`} tone={monteCarlo.successProbability < 0.5 ? "risk" : "normal"} />
        <CockpitCard icon={<Activity />} title="Risk status" termKey="annualized_volatility" value={analysis.diversificationScore < 55 ? "High" : "Moderate"} detail={`Top 5 concentration ${formatPercent(analysis.top5Concentration)}`} tone={analysis.diversificationScore < 55 ? "risk" : "watch"} />
        <CockpitCard icon={<PieChart />} title="Diversification score" termKey="concentration" value={`${analysis.diversificationScore}/100`} detail={`HHI ${analysis.hhi.toFixed(3)}`} />
        <CockpitCard icon={<BarChart3 />} title="Fee drag" termKey="fee_drag" value={formatMoney(analysis.estimatedAnnualFees)} detail={`${formatPercent(analysis.weightedExpenseRatio)} weighted fund expenses`} />
        <CockpitCard
          icon={<ShieldCheck />}
          title="Kelly sizing"
          termKey="allocation_drift"
          value={formatPercent(analysis.kellyEstimate.cappedKellyFraction)}
          detail={`Full ${formatPercent(analysis.kellyEstimate.fullKellyFraction)}; capped fractional guidance`}
          tone={analysis.kellyEstimate.cappedKellyFraction > 0.2 ? "watch" : "normal"}
        />
        <CockpitCard icon={<RefreshCcw />} title="Allocation drift" termKey="allocation_drift" value={formatPercent(analysis.allocationDrift)} detail="Current vs target allocation" tone={analysis.allocationDrift > 0.12 ? "watch" : "normal"} />
        <CockpitCard icon={<ArrowRight />} title="Next action" termKey="rebalancing" value={nextContribution?.assetClass ?? "Hold course"} detail={nextContribution ? `${formatMoney(nextContribution.amount)} of next contribution` : "No material contribution drift"} />
        <CockpitCard
          icon={<DatabaseZap />}
          title="Data freshness"
          termKey="data_freshness"
          value={`${Math.round(analysis.dataFreshnessScore * 100)}/100`}
          detail="Daily/delayed source freshness score"
          tone={analysis.dataFreshnessScore < 0.5 ? "watch" : "normal"}
        />
        <CockpitCard
          icon={<ShieldCheck />}
          title="Coverage quality"
          termKey="data_quality"
          value={analysis.coverageQuality.toLowerCase()}
          detail={`${formatPercent(analysis.coverageSummary.coveredWeight)} covered/manual; ${formatPercent(analysis.coverageSummary.staleWeight)} stale`}
          tone={analysis.coverageQuality === "LOW" || analysis.coverageQuality === "INSUFFICIENT" ? "watch" : "normal"}
        />
      </div>
      <section className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="panel p-4">
          <SectionTitle icon={<LineChart />} title="Goal runway" termKey="monte_carlo" />
          <FanChart rows={monteCarlo.fanChart.slice(0, 10)} targetAmount={portfolio.goal.targetAmount} />
        </div>
        <div className="panel p-4">
          <SectionTitle icon={<ShieldCheck />} title="Plain-language summary" termKey="data_quality" />
          <p className="safe-text mt-3 text-lg font-semibold leading-8">{analysis.healthSummary}</p>
          <div className="mt-4 grid gap-2">
            {rebalancePlan.warnings.map((warning) => (
              <div key={warning} className="rounded-md border border-line bg-panelAlt p-3 text-sm leading-6 text-muted">
                {warning}
              </div>
            ))}
          </div>
        </div>
      </section>
    </section>
  );
}

function OnboardingSection({
  csvText,
  setCsvText,
  csvErrors,
  importCsv
}: {
  csvText: string;
  setCsvText: (value: string) => void;
  csvErrors: string[];
  importCsv: () => void;
}) {
  return (
    <section className="grid gap-4 lg:grid-cols-3">
      <StepCard number="1" title="Create or import" body="Start with manual holdings or paste a CSV. CSV import validates required columns, numeric fields, and spreadsheet-formula injection." />
      <StepCard number="2" title="Set a target" body="Use a template or enter your own target allocation. Target allocation drives drift and contribution guidance." />
      <StepCard number="3" title="Review assumptions" body="Daily prices, FX, risk-free rates, fees, tax drag, and proxy data are visible instead of hidden." />
      <div className="panel min-w-0 p-4 lg:col-span-3">
        <SectionTitle icon={<Upload />} title="CSV import" termKey="data_quality" />
        <textarea className="input-control mt-3 min-h-36 w-full py-3 font-mono text-sm" value={csvText} onChange={(event) => setCsvText(event.target.value)} />
        <button type="button" className="primary-action mt-3" onClick={importCsv}>
          <FileSpreadsheet className="h-4 w-4" />
          Validate and import
        </button>
        {csvErrors.length ? (
          <div className="signal-danger mt-3 p-3 text-sm">
            {csvErrors.map((error) => <div key={error}>{error}</div>)}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PortfoliosSection({ portfolio, analysis }: { portfolio: Portfolio; analysis: ReturnType<typeof analyzePortfolio> }) {
  const locale = useLocale();
  return (
    <section className="grid gap-4 lg:grid-cols-[1fr_0.8fr]">
      <Link
        to="/$locale/portfolios/$portfolioId"
        params={{ locale, portfolioId: portfolio.portfolioId }}
        className="panel focus-ring p-5 hover:border-accent"
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold">{portfolio.name}</h2>
            <p className="mt-2 text-sm text-muted">{portfolio.description}</p>
          </div>
          <ArrowRight className="h-5 w-5 text-accent" />
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-4">
          <StatusPill label="Value" value={formatMoney(analysis.portfolioValue)} />
          <StatusPill label="Holdings" value={String(portfolio.holdings.length)} />
          <StatusPill label="Target drift" value={formatPercent(analysis.allocationDrift)} />
          <StatusPill label="Fee drag" value={formatMoney(analysis.estimatedAnnualFees)} />
        </div>
      </Link>
      <div className="panel p-5">
        <SectionTitle icon={<Lock />} title="Persistence stance" termKey="data_quality" />
        <p className="safe-text mt-3 text-sm leading-6 text-muted">
          This MVP keeps the demo workspace in browser state and is API-ready for persisted users. It avoids broker sync and
          execution. Future server persistence should use the spec entities: Portfolio, Holding, Transaction, TaxLot,
          Instrument, Job, UsageQuota, and AuditEvent.
        </p>
      </div>
    </section>
  );
}

function AtlasSection({
  portfolio,
  instrumentCatalog,
  analysis,
  updateCashBalance,
  updateHoldingQuantity,
  updateHoldingManualPrice,
  updateHoldingManualMarketValue,
  removeHolding,
  addHolding,
  resetPortfolio,
  reviewRequests,
  onRequestInstrumentReview
}: {
  portfolio: Portfolio;
  instrumentCatalog: Instrument[];
  analysis: ReturnType<typeof analyzePortfolio>;
  reviewRequests: InstrumentReviewRequest[];
  onRequestInstrumentReview: (query: string) => void;
} & PortfolioBuildControls) {
  const fundOverlapRows = calculateFundOverlap(portfolio.holdings, instrumentCatalog);
  return (
    <section className="grid gap-4">
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="panel p-4">
            <SectionTitle icon={<Globe2 />} title="Geographic exposure" termKey="geographic_exposure" />
            <ExposureMap rows={analysis.geographicExposure} />
          </div>
          <div className="panel p-4">
            <SectionTitle icon={<Layers3 />} title="Asset-class allocation" termKey="asset_allocation" />
            <SunburstLike rows={analysis.assetAllocation} />
          </div>
        </div>
        <PortfolioEditorPanel
          portfolio={portfolio}
          analysis={analysis}
          instrumentCatalog={instrumentCatalog}
          updateCashBalance={updateCashBalance}
          updateHoldingQuantity={updateHoldingQuantity}
          updateHoldingManualPrice={updateHoldingManualPrice}
          updateHoldingManualMarketValue={updateHoldingManualMarketValue}
          removeHolding={removeHolding}
          addHolding={addHolding}
          contextScreen="HOLDING_ENTRY"
          reviewRequests={reviewRequests}
          requestInstrumentReview={onRequestInstrumentReview}
          resetPortfolio={resetPortfolio}
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <ExposureTable title="Sector exposure" termKey="sector_exposure" rows={analysis.sectorExposure} />
        <ExposureTable title="Currency exposure" termKey="currency_exposure" rows={analysis.currencyExposure} />
        <ExposureTable title="Theme exposure" termKey="theme_exposure" rows={analysis.themeExposure} />
        <RiskConstellation rows={analysis.topHoldings} />
        <FundOverlapPanel rows={fundOverlapRows} />
      </div>
    </section>
  );
}

function BuilderSection({
  portfolio,
  instrumentCatalog,
  analysis,
  assumptions,
  updateGoal,
  updateTarget,
  updateCashBalance,
  updateHoldingQuantity,
  updateHoldingManualPrice,
  updateHoldingManualMarketValue,
  removeHolding,
  addHolding,
  resetPortfolio,
  reviewRequests,
  onRequestInstrumentReview
}: {
  portfolio: Portfolio;
  instrumentCatalog: Instrument[];
  analysis: ReturnType<typeof analyzePortfolio>;
  assumptions: AssumptionSet;
  updateGoal: <K extends keyof Portfolio["goal"]>(key: K, value: Portfolio["goal"][K]) => void;
  updateTarget: (assetClass: string, value: number) => void;
  reviewRequests: InstrumentReviewRequest[];
  onRequestInstrumentReview: (query: string) => void;
} & PortfolioBuildControls) {
  return (
    <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="grid gap-4">
        <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="panel p-4">
            <SectionTitle icon={<Target />} title="Goal setup" termKey="success_probability" />
            <NumberField label="Target amount" termKey="portfolio_value" value={portfolio.goal.targetAmount} onChange={(value) => updateGoal("targetAmount", value)} />
            <NumberField label="Monthly contribution" termKey="rebalancing" value={portfolio.goal.monthlyContribution} onChange={(value) => updateGoal("monthlyContribution", value)} />
            <label className="mt-4 block text-sm font-semibold">
              Target date
              <input className="input-control mt-2 w-full" type="date" value={portfolio.goal.targetDate} onChange={(event) => updateGoal("targetDate", event.target.value)} />
            </label>
          </div>
          <TargetAllocationPanel portfolio={portfolio} analysis={analysis} updateTarget={updateTarget} />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="panel p-4">
            <SectionTitle icon={<Globe2 />} title="Geographic exposure" termKey="geographic_exposure" />
            <ExposureMap rows={analysis.geographicExposure} />
          </div>
          <div className="panel p-4">
            <SectionTitle icon={<Layers3 />} title="Asset-class allocation" termKey="asset_allocation" />
            <SunburstLike rows={analysis.assetAllocation} />
          </div>
        </div>
      </div>
      <PortfolioEditorPanel
        portfolio={portfolio}
        analysis={analysis}
        assumptions={assumptions}
        instrumentCatalog={instrumentCatalog}
        updateCashBalance={updateCashBalance}
        updateHoldingQuantity={updateHoldingQuantity}
        updateHoldingManualPrice={updateHoldingManualPrice}
        updateHoldingManualMarketValue={updateHoldingManualMarketValue}
        removeHolding={removeHolding}
        addHolding={addHolding}
        contextScreen="BUILDER"
        reviewRequests={reviewRequests}
        requestInstrumentReview={onRequestInstrumentReview}
        resetPortfolio={resetPortfolio}
      />
    </section>
  );
}

function TargetAllocationPanel({
  portfolio,
  analysis,
  updateTarget
}: {
  portfolio: Portfolio;
  analysis: ReturnType<typeof analyzePortfolio>;
  updateTarget: (assetClass: string, value: number) => void;
}) {
  return (
    <div className="panel p-4">
      <SectionTitle icon={<PieChart />} title="Target allocation" termKey="target_allocation" />
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {Object.entries(portfolio.targetAllocation).map(([assetClass, value]) => (
          <label key={assetClass} className="grid gap-2">
            <span className="text-sm font-semibold text-muted">{assetClass}</span>
            <input
              className="input-control w-full"
              type="number"
              min={0}
              max={100}
              value={Math.round(value * 100)}
              onChange={(event) => updateTarget(assetClass, Number(event.target.value))}
            />
          </label>
        ))}
      </div>
      <div className="mt-5">
        <div className="text-sm font-bold">
          <MetricLabel label="Current vs target" termKey="allocation_drift" />
        </div>
        <div className="mt-3 grid gap-3">
          {analysis.currentTargetRows.slice(0, 8).map((row) => (
            <div key={row.key} className="grid gap-2 rounded-md border border-line bg-panelAlt p-3">
              <div className="flex justify-between gap-3 text-sm font-semibold">
                <span className="safe-text">{row.key}</span>
                <span className={row.drift > 0 ? "text-warning" : "text-accent"}>
                  {row.drift > 0 ? "over" : "under"} {formatPercent(Math.abs(row.drift))}
                </span>
              </div>
              <div className="relative h-3 rounded bg-paper">
                <div className="absolute left-1/2 top-0 h-3 w-px bg-muted" />
                <div
                  className={`absolute top-0 h-3 rounded ${row.drift > 0 ? "bg-warning" : "bg-accent"}`}
                  style={{
                    left: row.drift > 0 ? "50%" : `${50 - Math.min(50, Math.abs(row.drift) * 220)}%`,
                    width: `${Math.max(2, Math.min(50, Math.abs(row.drift) * 220))}%`
                  }}
                />
              </div>
              <div className="safe-text text-xs text-muted">
                Current {formatPercent(row.currentWeight)} · target {formatPercent(row.targetWeight)} · shift {formatMoney(row.dollarsToTarget)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PortfolioEditorPanel({
  portfolio,
  analysis,
  assumptions,
  instrumentCatalog,
  contextScreen,
  reviewRequests,
  requestInstrumentReview,
  updateCashBalance,
  updateHoldingQuantity,
  updateHoldingManualPrice,
  updateHoldingManualMarketValue,
  removeHolding,
  addHolding,
  resetPortfolio,
  updateGoal,
  setAssumptions
}: {
  portfolio: Portfolio;
  analysis: ReturnType<typeof analyzePortfolio>;
  instrumentCatalog: Instrument[];
  contextScreen: ManualEditorContext;
  reviewRequests: InstrumentReviewRequest[];
  requestInstrumentReview: (query: string) => void;
} & PortfolioEditorControls) {
  const searchInputId = useId();
  const resultListId = useId();
  const manualHelpId = useId();
  const heldInstrumentIds = useMemo(() => new Set(portfolio.holdings.map((holding) => holding.instrumentId)), [portfolio.holdings]);
  const heldListingIds = useMemo(() => new Set(portfolio.holdings.map((holding) => holding.listingId).filter(Boolean)), [portfolio.holdings]);
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState("");
  const [includeAdvancedInstruments, setIncludeAdvancedInstruments] = useState(false);
  const [includeInactiveInstruments, setIncludeInactiveInstruments] = useState(false);
  const [activeResultIndex, setActiveResultIndex] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [apiSearch, setApiSearch] = useState<{
    query: string;
    loading: boolean;
    results: InstrumentSearchResult[];
    error: string | null;
    freshness?: InstrumentSearchApiResponse["dataFreshness"];
  }>({ query: "", loading: false, results: [], error: null });
  const [manualDraft, setManualDraft] = useState<ManualHoldingDraft | null>(null);
  const trimmedQuery = searchTerm.trim();
  const isSymbolLikeQuery = /^[-.A-Za-z0-9]+$/.test(trimmedQuery);
  const minLengthForQuery = isSymbolLikeQuery ? 1 : 2;
  const isSearchReady = trimmedQuery.length >= minLengthForQuery;
  const hasManualDraft = manualDraft !== null;
  const normalizedManualCandidateId = `manual:${normalizedInstrumentId(trimmedQuery || "MANUAL")}`;
  const isManualCandidateAlreadyHeld = heldInstrumentIds.has(normalizedManualCandidateId);
  const draftManualHoldingId = manualDraft ? `manual:${normalizedInstrumentId(manualDraft.symbolOrCode)}` : null;
  const isDraftManualAlreadyHeld = draftManualHoldingId ? heldInstrumentIds.has(draftManualHoldingId) : isManualCandidateAlreadyHeld;

  useEffect(() => {
    if (!trimmedQuery) {
      setDebouncedSearchTerm("");
      setIsSearching(false);
      setActiveResultIndex(0);
      setManualDraft(null);
      return;
    }
    setIsSearching(true);
    const timeout = window.setTimeout(() => {
      setDebouncedSearchTerm(trimmedQuery);
      setIsSearching(false);
    }, 175);
    return () => window.clearTimeout(timeout);
  }, [trimmedQuery]);

  useEffect(() => {
    if (!isSearchReady || !debouncedSearchTerm) {
      setApiSearch({ query: "", loading: false, results: [], error: null });
      return;
    }
    const controller = new AbortController();
    const params = new URLSearchParams({
      q: debouncedSearchTerm,
      limit: "10",
      include_advanced: String(includeAdvancedInstruments),
      include_inactive: String(includeInactiveInstruments),
      context: contextScreen
    });
    setApiSearch((current) => ({
      query: debouncedSearchTerm,
      loading: true,
      results: current.query === debouncedSearchTerm ? current.results : [],
      error: null,
      freshness: current.query === debouncedSearchTerm ? current.freshness : undefined
    }));
    fetch(`/api/instruments/search?${params.toString()}`, {
      credentials: "include",
      headers: { Accept: "application/json" },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Instrument search failed: ${response.status}`);
        return (await response.json()) as InstrumentSearchApiResponse;
      })
      .then((payload) => {
        setApiSearch({
          query: debouncedSearchTerm,
          loading: false,
          results: payload.results ?? [],
          error: null,
          freshness: payload.dataFreshness
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setApiSearch({
          query: debouncedSearchTerm,
          loading: false,
          results: [],
          error: error instanceof Error ? error.message : "Instrument search API unavailable",
          freshness: undefined
        });
      });
    return () => controller.abort();
  }, [contextScreen, debouncedSearchTerm, includeAdvancedInstruments, includeInactiveInstruments, isSearchReady]);

  const localSearchLookup = useMemo(() => {
    if (!isSearchReady || !debouncedSearchTerm) {
      return { allResults: [] as InstrumentSearchResult[], error: null as string | null };
    }
    try {
      const allResults = searchInstruments(debouncedSearchTerm, instrumentCatalog, {
        includeAdvanced: includeAdvancedInstruments,
        includeInactive: includeInactiveInstruments,
        context: contextScreen,
        limit: 10
      });
      return { allResults, error: null };
    } catch {
      return {
        allResults: [] as InstrumentSearchResult[],
        error: "Search index is temporarily unavailable. Retry after a short refresh."
      };
    }
  }, [
    contextScreen,
    debouncedSearchTerm,
    heldInstrumentIds,
    heldListingIds,
    includeAdvancedInstruments,
    includeInactiveInstruments,
    instrumentCatalog,
    isSearchReady
  ]);

  const apiSettledForQuery = apiSearch.query === debouncedSearchTerm && !apiSearch.loading && !apiSearch.error;
  const apiUnavailableForQuery = apiSearch.query === debouncedSearchTerm && Boolean(apiSearch.error);
  const allSearchResults = apiSettledForQuery ? apiSearch.results : localSearchLookup.allResults;
  const searchResults = allSearchResults.filter((result) => !heldInstrumentIds.has(result.instrumentId) && !heldListingIds.has(result.listingId));
  const heldSearchResults = allSearchResults.filter((result) => heldInstrumentIds.has(result.instrumentId) || heldListingIds.has(result.listingId));
  const searchError = localSearchLookup.error ?? (apiUnavailableForQuery && !localSearchLookup.allResults.length ? apiSearch.error : null);
  const isApiSearching = apiSearch.query === debouncedSearchTerm && apiSearch.loading;

  useEffect(() => {
    setActiveResultIndex(0);
  }, [searchResults]);

  const hasSearchResults = searchResults.length > 0;
  const hasHeldSearchResults = heldSearchResults.length > 0;
  const canAddManual = isSearchReady && !isSearching && !isApiSearching && !hasSearchResults && !hasHeldSearchResults && trimmedQuery.length > 0;
  const openManualForm = () => {
    if (!canAddManual) return;
    setManualDraft({
      symbolOrCode: trimmedQuery,
      name: trimmedQuery,
      currency: "",
      assetClass: "Equity",
      instrumentType: "",
      exchange: "",
      country: "",
      quantityText: "1",
      priceText: "",
      marketValueText: ""
    });
  };

  const resetManualDraft = () => {
    setManualDraft(null);
  };

  const currentReviewRequest = reviewRequests
    .filter((request) => request.query.toLowerCase() === trimmedQuery.toLowerCase() && request.contextScreen === contextScreen)
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())[0];

  const selectResult = (result: InstrumentSearchResult) => {
    addHolding({ instrumentId: result.instrumentId, listingId: result.listingId, searchResult: result });
    resetManualDraft();
    setSearchTerm("");
  };

  const selectManual = () => {
    if (!hasManualDraft) return;
    const quantity = Number(manualDraft.quantityText);
    const price = manualDraft.priceText.trim() ? Number(manualDraft.priceText) : undefined;
    const marketValue = manualDraft.marketValueText.trim() ? Number(manualDraft.marketValueText) : undefined;
    if (validateManualDraft(manualDraft).length) return;
    if (isDraftManualAlreadyHeld) return;
    const payload: ManualHoldingPayload = {
      symbolOrCode: cleanManualText(manualDraft.symbolOrCode),
      name: cleanManualText(manualDraft.name),
      currency: cleanCurrency(manualDraft.currency),
      assetClass: manualDraft.assetClass,
      instrumentType: manualDraft.instrumentType || undefined,
      exchange: cleanManualText(manualDraft.exchange) || undefined,
      country: cleanManualText(manualDraft.country) || undefined,
      quantity,
      price,
      marketValue
    };
    addHolding({ instrumentId: manualDraft.symbolOrCode, manual: payload });
    resetManualDraft();
    setSearchTerm("");
  };

  const activeResult = searchResults[activeResultIndex] ?? null;
  const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!isSearching) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveResultIndex((current) => (searchResults.length ? (current + 1) % searchResults.length : 0));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveResultIndex((current) => (searchResults.length ? (current - 1 + searchResults.length) % searchResults.length : 0));
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (activeResult) selectResult(activeResult);
        else if (canAddManual && !hasManualDraft) openManualForm();
        else if (canAddManual && hasManualDraft) selectManual();
      } else if (event.key === "Escape") {
        resetManualDraft();
        setSearchTerm("");
      }
    }
  };

  const noResultGuidance =
    searchTerm && !isSearchReady ? `${minLengthForQuery}-character minimum (1 for symbols, 2 for company names).` : null;
  const canRequestReview = isSearchReady && !searchError && !isSearching && !isApiSearching && !hasSearchResults && !hasHeldSearchResults && trimmedQuery.length > 0;
  const shouldShowNoResults = canRequestReview;
  const manualDraftErrors = manualDraft ? validateManualDraft(manualDraft) : [];
  const activeResultId = activeResult ? `${resultListId}-option-${activeResultIndex}` : undefined;
  const requestCurrentSelectionForReview = () => {
    if (!canRequestReview) return;
    requestInstrumentReview(trimmedQuery);
  };

  useEffect(() => {
    if (!searchTerm) resetManualDraft();
  }, [searchTerm]);

  useEffect(() => {
    if (!canAddManual) {
      resetManualDraft();
    }
  }, [canAddManual]);

  return (
    <aside className="panel min-w-0 p-4 2xl:sticky 2xl:top-4 2xl:self-start">
      <SectionTitle icon={<BriefcaseBusiness />} title="Edit holdings" termKey="asset_allocation" />
      <p className="safe-text mt-2 text-sm leading-6 text-muted">
        Change quantities, cash, or add sample instruments and the exposure views update immediately in this workspace.
      </p>
      {updateGoal || setAssumptions ? (
        <details className="mt-4 rounded-md border border-line bg-panelAlt p-3" open>
          <summary className="cursor-pointer text-sm font-bold text-ink">Goal and assumptions</summary>
          <div className="mt-3 grid gap-2">
            {updateGoal ? (
              <>
                <NumberField label="Target amount" termKey="success_probability" value={portfolio.goal.targetAmount} onChange={(value) => updateGoal("targetAmount", value)} />
                <NumberField label="Monthly contribution" termKey="rebalancing" value={portfolio.goal.monthlyContribution} onChange={(value) => updateGoal("monthlyContribution", value)} />
              </>
            ) : null}
            {setAssumptions ? (
              <>
                <PercentField label="Risk-free rate" termKey="sharpe_ratio" value={assumptions?.riskFreeRate ?? defaultAssumptions.riskFreeRate} onChange={(value) => setAssumptions((current) => ({ ...current, riskFreeRate: value }))} />
                <PercentField label="Equity expected return" termKey="expected_return" value={assumptions?.expectedReturnByAssetClass.Equity ?? defaultAssumptions.expectedReturnByAssetClass.Equity ?? 0} onChange={(value) => setAssumptions((current) => ({ ...current, expectedReturnByAssetClass: { ...current.expectedReturnByAssetClass, Equity: value } }))} />
              </>
            ) : null}
            <div className="rounded-md border border-line bg-paper p-3 text-xs leading-5 text-muted">
              Kelly sizing uses annual excess return over annual variance. It is a planning diagnostic, not an order-size recommendation.
            </div>
          </div>
        </details>
      ) : null}
      <label className="mt-4 block text-sm font-semibold">
        <MetricLabel label="Cash balance" termKey="portfolio_value" />
        <input
          className="input-control mt-2 w-full"
          type="number"
          min={0}
          value={portfolio.cashBalance}
          onChange={(event) => updateCashBalance(Number(event.target.value))}
        />
      </label>
      <div className="mt-4 grid gap-2">
        {portfolio.holdings.map((holding) => {
          const instrument = instrumentCatalog.find((item) => item.instrumentId === holding.instrumentId);
          const row = analysis.topHoldings.find((item) => item.key === holding.instrumentId);
          const symbol = instrument?.symbol ?? holding.instrumentId;
          const needsManualValue = Boolean(instrument?.requiresUserPrice) && !Number.isFinite(holding.manualPrice) && !Number.isFinite(holding.manualMarketValue);
          return (
            <div key={holding.holdingId} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="safe-text text-sm font-bold">{symbol}</div>
                  <div className="safe-text text-xs text-muted">{instrument?.name ?? "Manual holding"}</div>
                </div>
                <button
                  type="button"
                  className="focus-ring grid min-h-11 min-w-11 place-items-center rounded-md border border-line text-muted hover:border-danger hover:text-danger"
                  aria-label={`Remove ${symbol}`}
                  onClick={() => removeHolding(holding.holdingId)}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_1fr_120px] sm:items-end">
                <label className="block text-xs font-semibold uppercase tracking-wide text-muted">
                  Quantity
                  <input
                    className="input-control mt-2 w-full"
                    aria-label={`${symbol} quantity`}
                    type="number"
                    min={0}
                    step={instrument?.instrumentType === "crypto" ? 0.01 : 1}
                    value={holding.quantity}
                    onChange={(event) => updateHoldingQuantity(holding.holdingId, Number(event.target.value))}
                  />
                </label>
                <label className="block text-xs font-semibold uppercase tracking-wide text-muted">
                  Manual price
                  <input
                    className="input-control mt-2 w-full"
                    aria-label={`${symbol} manual price`}
                    type="number"
                    min={0}
                    step="any"
                    placeholder="optional"
                    value={holding.manualPrice ?? ""}
                    onChange={(event) => updateHoldingManualPrice(holding.holdingId, event.target.value === "" ? undefined : Number(event.target.value))}
                  />
                </label>
                <label className="block text-xs font-semibold uppercase tracking-wide text-muted">
                  Market value
                  <input
                    className="input-control mt-2 w-full"
                    aria-label={`${symbol} manual market value`}
                    type="number"
                    min={0}
                    step="any"
                    placeholder="optional"
                    value={holding.manualMarketValue ?? ""}
                    onChange={(event) => updateHoldingManualMarketValue(holding.holdingId, event.target.value === "" ? undefined : Number(event.target.value))}
                  />
                </label>
                <div className="rounded-md border border-line bg-panel p-3 text-right">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted">Weight</div>
                  <div className="mt-1 font-bold text-accent">{row ? formatPercent(row.weight) : "n/a"}</div>
                </div>
              </div>
              {needsManualValue ? (
                <div className="mt-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-xs leading-5 text-warning">
                  Metadata-only directory match. Add a manual price or market value to include this holding in calculations.
                </div>
              ) : null}
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <div className="rounded-md border border-line bg-panel p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted">Value</div>
                  <div className="safe-text mt-1 font-bold">{row ? formatMoney(row.value) : "n/a"}</div>
                </div>
                <div className="rounded-md border border-line bg-panel p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted">Quality</div>
                  <div className="safe-text mt-1 font-bold">{instrument?.priceQuality ?? holding.source}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4 grid gap-2">
        <div className="block min-w-0 text-sm font-semibold">
          <label htmlFor={searchInputId}>Add holding</label>
          <div className="mt-1 flex min-w-0 flex-col gap-2 text-xs sm:flex-row sm:items-center sm:justify-between">
            <span className="safe-text min-w-0 text-muted">Search ticker, company, ETF, ISIN, FIGI, or local code</span>
            <div className="grid min-w-0 grid-cols-1 gap-2 min-[380px]:grid-cols-2 sm:inline-flex sm:items-center sm:gap-3">
              <label className="focus-ring relative inline-flex min-h-11 min-w-0 items-center gap-2 rounded-md border border-line bg-panelAlt px-3 py-2 text-left">
                <input
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  type="checkbox"
                  checked={includeAdvancedInstruments}
                  onChange={(event) => setIncludeAdvancedInstruments(event.target.checked)}
                />
                <span aria-hidden="true" className={`h-4 w-4 shrink-0 rounded border ${includeAdvancedInstruments ? "border-accent bg-accent" : "border-line bg-panel"}`} />
                <span className="safe-text inline-flex min-w-0 items-center gap-1">
                  Include advanced
                  <TermTooltip termKey="advanced_instrument" />
                </span>
              </label>
              <label className="focus-ring relative inline-flex min-h-11 min-w-0 items-center gap-2 rounded-md border border-line bg-panelAlt px-3 py-2 text-left">
                <input
                  className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  type="checkbox"
                  checked={includeInactiveInstruments}
                  onChange={(event) => setIncludeInactiveInstruments(event.target.checked)}
                />
                <span aria-hidden="true" className={`h-4 w-4 shrink-0 rounded border ${includeInactiveInstruments ? "border-accent bg-accent" : "border-line bg-panel"}`} />
                <span className="safe-text inline-flex min-w-0 items-center gap-1">
                  Include inactive
                  <TermTooltip termKey="inactive_security" />
                </span>
              </label>
            </div>
          </div>
          <div className="relative mt-2">
            <input
              id={searchInputId}
              className="input-control w-full pl-10"
              type="text"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={hasSearchResults}
              aria-controls={hasSearchResults ? resultListId : undefined}
              aria-activedescendant={activeResultId}
              placeholder="AAPL / Apple / US0378331005"
              maxLength={INSTRUMENT_SEARCH_QUERY_MAX_LENGTH}
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              onKeyDown={handleSearchKeyDown}
            />
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          </div>
          {isSearching || isApiSearching ? (
            <div className="mt-2 flex items-center gap-2 text-xs text-muted">
              <Loader2 className="h-3 w-3 animate-spin" />
              Searching local instrument index...
            </div>
          ) : null}
          {apiSearch.freshness?.instrumentIndexLastUpdatedAt && apiSearch.query === debouncedSearchTerm ? (
            <div className="mt-2 text-xs text-muted">
              <MetricLabel label={`Index ${apiSearch.freshness.status?.toLowerCase() ?? "checked"} ${new Date(apiSearch.freshness.instrumentIndexLastUpdatedAt).toLocaleDateString()}`} termKey="data_freshness" />
            </div>
          ) : null}
          {noResultGuidance ? <div className="mt-2 text-xs text-muted">{noResultGuidance}</div> : null}
          {searchError ? <div className="mt-2 text-xs text-danger">{searchError}</div> : null}
          {hasSearchResults ? (
            <div id={resultListId} className="mt-2 max-h-80 overflow-auto rounded-md border border-line bg-panelAlt" role="listbox" aria-label="Instrument search results" aria-live="polite">
              {searchResults.map((result, index) => (
                <button
                  id={`${resultListId}-option-${index}`}
                  key={`${result.instrumentId}-${result.listingId}`}
                  type="button"
                  role="option"
                  aria-selected={index === activeResultIndex}
                  className={`block w-full border-b border-line px-3 py-3 text-left text-sm last:border-b-0 ${
                    index === activeResultIndex ? "bg-accentSoft text-ink" : "hover:bg-panel"
                  }`}
                  onMouseEnter={() => setActiveResultIndex(index)}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectResult(result)}
                >
                  <div className="safe-text text-sm font-bold">
                    {result.displaySymbol}
                    {result.isStale ? <InlineBadge label="Stale price" termKey="stale_data" tone="warning" /> : null}
                    {!result.isActive ? <InlineBadge label="Inactive" termKey="inactive_security" tone="danger" /> : null}
                    {result.isAdvancedInstrument ? <InlineBadge label="Advanced" termKey="advanced_instrument" tone="muted" /> : null}
                    {result.requiresUserPrice ? <InlineBadge label="Needs price" termKey="data_quality" tone="warning" /> : null}
                  </div>
                  <div className="safe-text text-xs text-muted">{result.name}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <InstrumentMetaChip label={result.exchange} termKey="exchange" />
                    <InstrumentMetaChip label={result.country} termKey="country" />
                    <InstrumentMetaChip label={result.currency} termKey="currency" />
                    <InstrumentMetaChip label={result.instrumentType.toUpperCase()} termKey="instrument_type" />
                    <InstrumentMetaChip label={result.assetClass} termKey="asset_class" />
                    <InstrumentMetaChip label={result.sector} termKey="sector" />
                  </div>
                  <div className="mt-2 text-xs text-muted">
                    <MetricLabel label={result.qualityMessage} termKey="data_quality" />
                  </div>
                  {result.qualityLevel === "STALE" ? (
                    <p className="mt-1 text-xs text-warning">
                      <TermTooltip termKey="stale_data" />
                      <span className="ml-1">Instrument record may be stale.</span>
                    </p>
                  ) : null}
                  {result.qualityLevel === "PARTIAL" || result.qualityLevel === "ESTIMATED" ? (
                    <p className="mt-1 text-xs text-warning">
                      <TermTooltip termKey={result.qualityLevel === "PARTIAL" ? "partial_data" : "estimated_data"} />
                      <span className="ml-1">Some metadata is incomplete.</span>
                    </p>
                  ) : null}
                  {result.requiresUserPrice ? (
                    <p className="mt-1 text-xs text-warning">
                      Directory match only. Add a manual price or market value after selection to include it in calculations.
                    </p>
                  ) : null}
                </button>
              ))}
            </div>
          ) : null}
          {hasHeldSearchResults && !hasSearchResults ? (
            <div className="mt-2 rounded-md border border-line bg-panel p-3 text-xs leading-5 text-muted">
              <div className="font-semibold text-ink">Already in this workspace</div>
              <div className="safe-text mt-1">
                {heldSearchResults.slice(0, 2).map((result) => result.displaySymbol).join(", ")} already exists as a holding. Edit its quantity above instead of adding a duplicate.
              </div>
            </div>
          ) : null}
          {shouldShowNoResults ? (
            <div className="mt-2">
              <div className="text-xs text-muted">No matching instrument found.</div>
              <div className="mt-2 rounded-md border border-line bg-panel p-3 text-xs leading-5 text-muted">
                <div className="font-semibold text-ink">Try:</div>
                <ul className="mt-2 list-disc pl-5">
                  <li>Searching by company or fund name</li>
                  <li>Adding the exchange code</li>
                  <li>Searching by ISIN or FIGI</li>
                  <li>Enabling advanced instruments</li>
                </ul>
                <button
                  type="button"
                  className="secondary-action mt-3 justify-center"
                  onClick={requestCurrentSelectionForReview}
                  disabled={!canRequestReview}
                >
                  <AlertTriangle className="h-4 w-4" />
                  Request instrument review
                </button>
                {currentReviewRequest ? (
                  <p className="mt-2">
                    Local review status for "{trimmedQuery}": <span className="font-semibold">{currentReviewRequest.status}</span> (
                    {new Date(currentReviewRequest.createdAt).toLocaleDateString()}
                    )
                  </p>
                ) : null}
              </div>
            </div>
          ) : null}
          {canAddManual ? (
            <div className="mt-2 rounded-md border border-dashed border-line bg-panel p-3">
              <p id={manualHelpId} className="safe-text text-xs text-muted">
                No sample match. Add a manual holding only when you know the listing, currency, quantity, and either price or market value.
              </p>
              {!hasManualDraft ? (
                <button
                  type="button"
                  className="secondary-action mt-2 justify-center"
                  onClick={openManualForm}
                  disabled={isManualCandidateAlreadyHeld}
                >
                  <Plus className="h-4 w-4" />
                  Add manual holding
                </button>
              ) : (
                <div className="mt-3 grid gap-2" aria-describedby={manualHelpId}>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <ManualTextField label="Symbol / code" required value={manualDraft.symbolOrCode} onChange={(value) => setManualDraft((current) => (current ? { ...current, symbolOrCode: value } : current))} />
                    <ManualTextField label="Instrument name" required value={manualDraft.name} onChange={(value) => setManualDraft((current) => (current ? { ...current, name: value } : current))} />
                    <ManualTextField label="Currency" required value={manualDraft.currency} maxLength={3} pattern="[A-Za-z]{3}" onChange={(value) => setManualDraft((current) => (current ? { ...current, currency: value.toUpperCase() } : current))} />
                    <label className="block text-xs font-semibold">
                      Asset class*
                      <select
                        className="input-control mt-1 w-full"
                        required
                        value={manualDraft.assetClass}
                        onChange={(event) =>
                          setManualDraft((current) => (current ? { ...current, assetClass: event.target.value as AssetClass } : current))
                        }
                      >
                        {ASSET_CLASS_OPTIONS.map((item) => (
                          <option key={item} value={item}>
                            {item}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-xs font-semibold">
                      Instrument type
                      <select
                        className="input-control mt-1 w-full"
                        value={manualDraft.instrumentType}
                        onChange={(event) =>
                          setManualDraft((current) => (current ? { ...current, instrumentType: event.target.value as ManualInstrumentType } : current))
                        }
                      >
                        {MANUAL_INSTRUMENT_TYPE_OPTIONS.map((item) => (
                          <option key={item} value={item}>
                            {item || "Choose (optional)"}
                          </option>
                        ))}
                      </select>
                    </label>
                    <ManualTextField label="Exchange" value={manualDraft.exchange} onChange={(value) => setManualDraft((current) => (current ? { ...current, exchange: value } : current))} />
                    <ManualTextField label="Country" value={manualDraft.country} onChange={(value) => setManualDraft((current) => (current ? { ...current, country: value } : current))} />
                    <ManualNumberField label="Quantity" required min={0.0001} max={MANUAL_QUANTITY_MAX} value={manualDraft.quantityText} onChange={(value) => setManualDraft((current) => (current ? { ...current, quantityText: value } : current))} />
                    <ManualNumberField label="Price" min={0} max={MANUAL_MONEY_MAX} value={manualDraft.priceText} onChange={(value) => setManualDraft((current) => (current ? { ...current, priceText: value } : current))} />
                    <ManualNumberField label="Market value" min={0} max={MANUAL_MONEY_MAX} value={manualDraft.marketValueText} onChange={(value) => setManualDraft((current) => (current ? { ...current, marketValueText: value } : current))} />
                  </div>
                  {manualDraftErrors.length ? (
                    <div className="signal-danger p-3 text-xs leading-5" role="alert">
                      {manualDraftErrors.map((error) => <div key={error}>{error}</div>)}
                    </div>
                  ) : null}
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="primary-action mt-2 justify-center"
                      onClick={selectManual}
                      disabled={!hasManualDraft || isDraftManualAlreadyHeld || manualDraftErrors.length > 0}
                    >
                      <Plus className="h-4 w-4" />
                      Save manual holding
                    </button>
                    <button
                      type="button"
                      className="secondary-action mt-2 justify-center"
                      onClick={resetManualDraft}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            className="primary-action justify-center"
            onClick={() => hasSearchResults && activeResult ? selectResult(activeResult) : null}
            disabled={!hasSearchResults}
          >
            <Plus className="h-4 w-4" />
            Add selected holding
          </button>
          <button type="button" className="secondary-action justify-center" onClick={resetPortfolio}>
            <RefreshCcw className="h-4 w-4" />
            Reset sample
          </button>
        </div>
      </div>
      <div className="signal-warning mt-4 p-3 text-xs leading-5">
        Holding edits are planning inputs for this browser session. Source-linked demo tax lots and transactions are cleared
        after holding changes so tax/backtest views do not reuse stale records.
      </div>
    </aside>
  );
}

function InstrumentMetaChip({ label, termKey }: { label: string; termKey: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line bg-paper px-2 py-1 text-xs text-muted">
      {label}
      <TermTooltip termKey={termKey} />
    </span>
  );
}

function InlineBadge({ label, termKey, tone }: { label: string; termKey: string; tone: "warning" | "danger" | "muted" }) {
  const toneClass = tone === "warning" ? "text-warning" : tone === "danger" ? "text-danger" : "text-muted";
  return (
    <span className={`ml-2 inline-flex items-center gap-1 text-xs ${toneClass}`}>
      {label}
      <TermTooltip termKey={termKey} />
    </span>
  );
}

function BacktestSection({ result }: { result: ReturnType<typeof runBacktest> }) {
  return (
    <section className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard title="Ending value" termKey="portfolio_value" value={formatMoney(result.endingValue)} />
        <MetricCard title="CAGR" termKey="cagr" value={formatPercent(result.cagr)} />
        <MetricCard title="Volatility" termKey="annualized_volatility" value={formatPercent(result.annualizedVolatility)} />
        <MetricCard title="Max drawdown" termKey="max_drawdown" value={formatPercent(result.maxDrawdown)} />
      </div>
      <div className="panel p-4">
        <SectionTitle icon={<LineChart />} title="Backtest equity curve" termKey="backtest" />
        <LineBars rows={result.equityCurve.map((row) => ({ label: row.date.slice(0, 7), value: row.value }))} />
        <p className="mt-3 text-sm text-muted">Backtesting shows what would have happened in the past. It does not prove what will happen in the future.</p>
      </div>
      <ExposureTable title="Backtest diagnostics" termKey="data_quality" rows={[
        { key: "best", label: "Best year", value: result.bestYear, weight: Math.abs(result.bestYear), topHoldings: [formatPercent(result.bestYear)], quality: "PROXY" },
        { key: "worst", label: "Worst year", value: result.worstYear, weight: Math.abs(result.worstYear), topHoldings: [formatPercent(result.worstYear)], quality: "PROXY" },
        { key: "tracking", label: "Tracking error", value: result.trackingError, weight: result.trackingError, topHoldings: [formatPercent(result.trackingError)], quality: "PROXY" },
        { key: "relative", label: "Benchmark relative return", value: result.benchmarkRelativeReturn, weight: Math.abs(result.benchmarkRelativeReturn), topHoldings: [formatPercent(result.benchmarkRelativeReturn)], quality: "PROXY" }
      ]} />
    </section>
  );
}

function MonteCarloSection({
  result,
  portfolio,
  updateGoal
}: {
  result: ReturnType<typeof runMonteCarlo>;
  portfolio: Portfolio;
  updateGoal: <K extends keyof Portfolio["goal"]>(key: K, value: Portfolio["goal"][K]) => void;
}) {
  return (
    <section className="grid gap-4 xl:grid-cols-[0.75fr_1.25fr]">
      <div className="panel p-4">
        <SectionTitle icon={<Calculator />} title="Simulation inputs" termKey="monte_carlo" />
        <NumberField label="Target amount" termKey="success_probability" value={portfolio.goal.targetAmount} onChange={(value) => updateGoal("targetAmount", value)} />
        <NumberField label="Monthly contribution" termKey="rebalancing" value={portfolio.goal.monthlyContribution} onChange={(value) => updateGoal("monthlyContribution", value)} />
        <StatusPill label="Paths" value={String(result.pathCount)} />
        <StatusPill label="Method" value={result.method} />
      </div>
      <div className="panel p-4">
        <SectionTitle icon={<LineChart />} title="Monte Carlo fan chart" termKey="monte_carlo" />
        <FanChart rows={result.fanChart} targetAmount={portfolio.goal.targetAmount} />
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <MetricCard title="Success probability" termKey="success_probability" value={formatPercent(result.successProbability)} />
          <MetricCard title="Median outcome" termKey="percentile" value={formatMoney(result.medianOutcome)} />
          <MetricCard title="P10 / P90" termKey="percentile" value={`${formatMoney(result.p10Outcome)} / ${formatMoney(result.p90Outcome)}`} />
          <MetricCard title="Required monthly" termKey="money_weighted_return" value={formatMoney(result.requiredMonthlyContribution)} />
        </div>
      </div>
    </section>
  );
}

function RebalanceSection({ plan, analysis }: { plan: ReturnType<typeof generateContributionRebalancePlan>; analysis: ReturnType<typeof analyzePortfolio> }) {
  return (
    <section className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
      <div className="panel p-4">
        <SectionTitle icon={<RefreshCcw />} title="Rebalancing compass" termKey="rebalancing" />
        <Compass rows={analysis.currentTargetRows.slice(0, 6)} />
      </div>
      <div className="panel p-4">
        <SectionTitle icon={<ArrowRight />} title="Contribution-first plan" termKey="rebalancing_band" />
        <div className="mt-4 grid gap-3">
          {plan.cashContributionPlan.map((item) => (
            <div key={item.assetClass} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex justify-between gap-3 text-sm font-semibold">
                <span>{item.assetClass}</span>
                <span className="text-accent">{formatMoney(item.amount)}</span>
              </div>
              <p className="mt-2 text-sm text-muted">{item.reason}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-warning">{plan.warnings[0]}</p>
      </div>
    </section>
  );
}

function FeesSection({
  analysis,
  assumptions,
  setAssumptions
}: {
  analysis: ReturnType<typeof analyzePortfolio>;
  assumptions: AssumptionSet;
  setAssumptions: Dispatch<SetStateAction<AssumptionSet>>;
}) {
  const parts = [
    ["Fund expense ratios", analysis.weightedExpenseRatio],
    ["Platform fees", assumptions.platformFeeRate],
    ["FX fees", assumptions.fxFeeRate],
    ["Estimated tax drag", assumptions.taxDragRate]
  ];
  return (
    <section className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
      <div className="panel p-4">
        <SectionTitle icon={<BarChart3 />} title="Fee assumptions" termKey="fee_drag" />
        <PercentField label="Platform fee" termKey="platform_fee" value={assumptions.platformFeeRate} onChange={(value) => setAssumptions((current) => ({ ...current, platformFeeRate: value }))} />
        <PercentField label="FX fee" termKey="fx_fee" value={assumptions.fxFeeRate} onChange={(value) => setAssumptions((current) => ({ ...current, fxFeeRate: value }))} />
        <PercentField label="Tax drag" termKey="tax_drag" value={assumptions.taxDragRate} onChange={(value) => setAssumptions((current) => ({ ...current, taxDragRate: value }))} />
      </div>
      <div className="panel p-4">
        <SectionTitle icon={<DatabaseZap />} title="Fee leak chart" termKey="expense_ratio" />
        <div className="mt-4 grid gap-3">
          {parts.map(([label, value]) => (
            <div key={label} className="grid gap-2">
              <div className="flex justify-between gap-3 text-sm font-semibold">
                <span>{label}</span>
                <span>{formatPercent(value as number)}</span>
              </div>
              <div className="h-3 rounded bg-panelAlt">
                <div className="h-3 rounded bg-warning" style={{ width: `${Math.min(100, (value as number) * 4000)}%` }} />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xl font-bold">Estimated annual fee drag: {formatMoney(analysis.estimatedAnnualFees)}</p>
      </div>
    </section>
  );
}

function TaxLotsSection({ portfolio, taxImpact }: { portfolio: Portfolio; taxImpact: TaxLotImpact }) {
  return (
    <section className="grid gap-4">
      <div className="signal-warning p-4 text-sm font-semibold leading-6">
        Tax estimates are approximate and depend on your country, account type, and personal circumstances. This is not tax advice.
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_0.7fr]">
        <TablePanel title="Tax lots" termKey="tax_lot">
          {portfolio.taxLots.map((lot) => (
            <TableRow key={lot.lotId} cells={[lot.instrumentId, lot.purchaseDate, formatNumber(lot.quantityRemaining), formatMoney(lot.costBasisPerUnit), lot.source]} />
          ))}
        </TablePanel>
        <div className="panel p-4">
          <SectionTitle icon={<Calculator />} title="Estimated sale impact" termKey="unrealized_gain" />
          <MetricCard title="Method" termKey="specific_lot" value={taxImpact.method.replaceAll("_", " ")} />
          <MetricCard title="Realized gain" termKey="realized_gain" value={formatMoney(taxImpact.realizedGain)} />
          <MetricCard title="Estimated fees" termKey="transaction_fee" value={formatMoney(taxImpact.estimatedFees)} />
          <p className="mt-3 text-sm text-warning">{taxImpact.warning}</p>
        </div>
      </div>
    </section>
  );
}

function HoldingsSection({
  portfolio,
  analysis,
  instrumentCatalog
}: { portfolio: Portfolio; analysis: ReturnType<typeof analyzePortfolio>; instrumentCatalog: Instrument[] }) {
  return (
    <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <TablePanel title="Holdings table" termKey="asset_allocation">
        {portfolio.holdings.map((holding) => {
          const instrument = instrumentCatalog.find((item) => item.instrumentId === holding.instrumentId);
          const row = analysis.topHoldings.find((item) => item.key === holding.instrumentId);
          return (
            <TableRow
              key={holding.holdingId}
              cells={[
                instrument?.symbol ?? holding.instrumentId,
                instrument?.name ?? "Unknown",
                formatNumber(holding.quantity),
                row ? formatMoney(row.value) : "n/a",
                row ? formatPercent(row.weight) : "n/a",
                instrument?.priceQuality ?? "UNAVAILABLE"
              ]}
            />
          );
        })}
      </TablePanel>
      <ExposureTable title="Top holdings concentration" termKey="concentration" rows={analysis.topHoldings} />
    </section>
  );
}

function TransactionsSection({
  portfolio,
  csvText,
  setCsvText,
  csvErrors,
  importCsv
}: {
  portfolio: Portfolio;
  csvText: string;
  setCsvText: (value: string) => void;
  csvErrors: string[];
  importCsv: () => void;
}) {
  return (
    <section className="grid gap-4 xl:grid-cols-[1fr_0.8fr]">
      <TablePanel title="Transactions table" termKey="money_weighted_return">
        {portfolio.transactions.map((txn) => (
          <TableRow key={txn.transactionId} cells={[txn.date, txn.type, txn.instrumentId, formatNumber(txn.quantity), formatMoney(txn.price), formatMoney(txn.amount)]} />
        ))}
      </TablePanel>
      <div className="panel p-4">
        <SectionTitle icon={<FileSpreadsheet />} title="Holdings CSV import" termKey="data_quality" />
        <textarea className="input-control mt-3 min-h-40 w-full py-3 font-mono text-sm" value={csvText} onChange={(event) => setCsvText(event.target.value)} />
        <button type="button" className="primary-action mt-3" onClick={importCsv}>Validate CSV</button>
        {csvErrors.length ? <div className="signal-danger mt-3 p-3 text-sm">{csvErrors.join(" ")}</div> : null}
      </div>
    </section>
  );
}

function SettingsSection({
  section,
  assumptions,
  setAssumptions
}: {
  section: PortfolioSection;
  assumptions: AssumptionSet;
  setAssumptions: Dispatch<SetStateAction<AssumptionSet>>;
}) {
  const locale = useLocale();
  const links = [
    ["settings-profile", "Profile", `/${locale}/settings/profile`],
    ["settings-assumptions", "Assumptions", `/${locale}/settings/assumptions`],
    ["settings-data-sources", "Data sources", `/${locale}/settings/data-sources`],
    ["settings-security", "Security", `/${locale}/settings/security`]
  ] as const;
  return (
    <section className="grid gap-4 xl:grid-cols-[240px_1fr]">
      <SideLinks active={section} links={links} />
      <div className="panel p-4">
        {section === "settings-profile" ? (
          <>
            <SectionTitle icon={<BriefcaseBusiness />} title="Profile" termKey="base_currency" />
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <StatusPill label="Base currency" value="USD" />
              <StatusPill label="Tax region" value="User provided" />
              <StatusPill label="Mode" value="Analysis only" />
            </div>
          </>
        ) : null}
        {section === "settings-assumptions" ? (
          <>
            <SectionTitle icon={<Calculator />} title="Assumption set" termKey="data_quality" />
            <PercentField label="Risk-free rate" termKey="risk_free_rate" value={assumptions.riskFreeRate} onChange={(value) => setAssumptions((current) => ({ ...current, riskFreeRate: value }))} />
            <PercentField label="Rebalancing band" termKey="rebalancing_band" value={assumptions.rebalanceBand} onChange={(value) => setAssumptions((current) => ({ ...current, rebalanceBand: value }))} />
          </>
        ) : null}
        {section === "settings-data-sources" ? (
          <>
            <SectionTitle icon={<DatabaseZap />} title="Data-source policy" termKey="proxy" />
            <DataSourceCards />
          </>
        ) : null}
        {section === "settings-security" ? (
          <>
            <SectionTitle icon={<ShieldCheck />} title="Security boundary" termKey="data_quality" />
            <ul className="mt-4 grid gap-3 text-sm text-muted">
              <li>Protected server routes require server-side authorization; client hiding is not trusted.</li>
              <li>CSV import rejects suspicious spreadsheet formula values.</li>
              <li>Heavy work is designed for queueing or browser-side execution, not request-path CPU spikes.</li>
              <li>No public route triggers LLM analysis or broker execution.</li>
            </ul>
          </>
        ) : null}
      </div>
    </section>
  );
}

function GlossarySection() {
  return (
    <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Object.entries(portfolioTerms).map(([key, term]) => (
        <div key={key} id={`term-${key}`} className="panel p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-accent">{term.category.replace("_", " ")}</div>
          <h2 className="mt-2 text-lg font-bold">{term.label}</h2>
          <p className="mt-2 text-sm leading-6 text-muted">{term.short}</p>
          {term.long ? <p className="mt-2 text-sm leading-6 text-muted">{term.long}</p> : null}
        </div>
      ))}
    </section>
  );
}

function DataSourceCards() {
  const rows = [
    ["Manual input", "complete for user-entered holdings", "free"],
    ["Daily market data", "delayed, cache-first, provider-policy constrained", "free quota"],
    ["ETF look-through", "public filings where available; otherwise proxy", "partial"],
    ["Tax rules", "user-provided lots only; no country-specific tax automation", "manual"]
  ];
  return (
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      {rows.map(([title, body, badge]) => (
        <div key={title} className="rounded-md border border-line bg-panelAlt p-4">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-semibold">{title}</h3>
            <span className="badge border-line bg-panel text-muted">{badge}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
        </div>
      ))}
    </div>
  );
}

function DataQualityPanel({ issues }: { issues: ReturnType<typeof analyzePortfolio>["dataQualityIssues"] }) {
  return (
    <section className="panel p-4">
      <SectionTitle icon={<DatabaseZap />} title="Data-quality ledger" termKey="data_quality" />
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        {issues.map((issue) => (
          <div key={issue.issueId} className="rounded-md border border-line bg-panelAlt p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="font-semibold">{issue.metricKey.replaceAll("_", " ")}</span>
              <span className="badge border-line bg-panel text-muted">{issue.qualityLevel}</span>
            </div>
            <p className="safe-text mt-2 leading-6 text-muted">{issue.reason}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function PortfolioCoverageLedger({ analysis }: { analysis: ReturnType<typeof analyzePortfolio> }) {
  return (
    <section className="panel p-4">
      <SectionTitle icon={<DatabaseZap />} title="Calculation provenance" termKey="data_quality" />
      <div className="mt-3 grid gap-3 lg:grid-cols-[0.8fr_1.2fr]">
        <div className="grid gap-2">
          <StatusPill label="Return basis" value="daily close proxy" />
          <StatusPill label="Cache policy" value="shared daily bars" />
          <StatusPill label="Source policy" value="no public live fetch" />
        </div>
        <div className="grid gap-2">
          {analysis.holdingCoverageRows.slice(0, 8).map((row) => (
            <div key={row.holdingId} className="grid gap-2 rounded-md border border-line bg-panelAlt p-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <div className="min-w-0">
                <div className="safe-text text-sm font-semibold">{row.symbol} · {row.name}</div>
                <div className="safe-text mt-1 text-xs text-muted">
                  {row.coverageStatus} · {row.qualityLevel.toLowerCase()} · {row.priceAsOf || "date unavailable"}
                </div>
              </div>
              <div className="text-right text-sm font-semibold">
                {formatPercent(row.weight)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ExposureTable({ title, termKey, rows }: { title: string; termKey: string; rows: ExposureRow[] }) {
  return (
    <div className="panel p-4">
      <SectionTitle icon={<BarChart3 />} title={title} termKey={termKey} />
      <div className="mt-4 grid gap-3">
        {rows.slice(0, 8).map((row) => (
          <div key={row.key} className="grid gap-2 rounded-md border border-line bg-panelAlt p-3">
            <div className="flex justify-between gap-3 text-sm font-semibold">
              <span className="safe-text">{row.label}</span>
              <span>{formatPercent(row.weight)}</span>
            </div>
            <div className="h-2 rounded bg-paper">
              <div className="h-2 rounded bg-accent" style={{ width: `${Math.min(100, row.weight * 100)}%` }} />
            </div>
            <div className="safe-text text-xs text-muted">{row.topHoldings.join(" / ")} · {row.quality}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FundOverlapPanel({ rows }: { rows: ReturnType<typeof calculateFundOverlap> }) {
  return (
    <div className="panel p-4">
      <SectionTitle icon={<Layers3 />} title="Fund overlap" termKey="fund_overlap" />
      <div className="mt-4 grid gap-3">
        {rows.length ? (
          rows.slice(0, 6).map((row) => (
            <div key={row.pairKey} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex justify-between gap-3 text-sm font-semibold">
                <span>{row.leftSymbol} / {row.rightSymbol}</span>
                <span className="text-accent">{formatPercent(row.overlapWeight)}</span>
              </div>
              <p className="safe-text mt-2 text-xs text-muted">
                Shared: {row.sharedHoldings.slice(0, 4).map((item) => `${item.symbol} ${formatPercent(item.weight)}`).join(", ")}
              </p>
              <p className="mt-2 text-xs text-warning">Look-through data is partial/proxy where public holdings are delayed or incomplete.</p>
            </div>
          ))
        ) : (
          <div className="rounded-md border border-dashed border-line bg-panelAlt p-4 text-sm text-muted">
            No source-backed fund overlap rows are available for the current holdings.
          </div>
        )}
      </div>
    </div>
  );
}

function ExposureMap({ rows }: { rows: ExposureRow[] }) {
  return (
    <div className="mt-4 grid min-h-[300px] content-end rounded-md border border-line bg-[radial-gradient(circle_at_20%_20%,rgba(103,216,239,0.18),transparent_28%),linear-gradient(135deg,#0b1420,#111c28)] p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {rows.slice(0, 6).map((row) => (
          <div key={row.key} className="rounded-md border border-accent/30 bg-accentSoft p-3">
            <div className="text-sm font-bold text-accent">{row.label}</div>
            <div className="mt-2 text-2xl font-bold">{formatPercent(row.weight)}</div>
            <div className="safe-text mt-1 text-xs text-muted">{row.topHoldings.join(", ")}</div>
          </div>
      ))}
      </div>
      <p className="mt-4 text-xs text-muted">
        Exposure uses listing country, domicile, currency, and available fund look-through. Missing look-through stays labeled instead of inferred.
      </p>
    </div>
  );
}

function SunburstLike({ rows }: { rows: ExposureRow[] }) {
  return (
    <div className="mt-4 grid min-h-[300px] grid-cols-2 gap-2 md:grid-cols-3">
      {rows.map((row, index) => (
        <div
          key={row.key}
          className="grid place-items-center rounded-md border border-line bg-panelAlt p-3 text-center"
          style={{ minHeight: `${Math.max(80, 220 * row.weight)}px`, opacity: 1 - index * 0.04 }}
        >
          <div>
            <div className="safe-text text-sm font-bold">{row.label}</div>
            <div className="mt-1 text-2xl font-bold text-accent">{formatPercent(row.weight)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function RiskConstellation({ rows }: { rows: ExposureRow[] }) {
  const topRows = rows.slice(0, 8);
  const maxWeight = Math.max(...topRows.map((row) => row.weight), 0.01);
  return (
    <div className="panel p-4">
      <SectionTitle icon={<Activity />} title="Holding concentration risk" termKey="risk_contribution" />
      <p className="safe-text mt-2 text-sm leading-6 text-muted">
        Until per-holding volatility and correlation data are connected, this ranks risk by portfolio weight and flags concentration.
      </p>
      <div className="mt-4 grid gap-3">
        {topRows.map((row) => {
          const riskLabel = row.weight >= 0.2 ? "High concentration" : row.weight >= 0.1 ? "Medium concentration" : "Lower concentration";
          const tone = row.weight >= 0.2 ? "text-danger" : row.weight >= 0.1 ? "text-warning" : "text-accent";
          return (
            <div key={row.key} className="rounded-md border border-line bg-panelAlt p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="safe-text text-sm font-bold">{row.label}</div>
                  <div className={`mt-1 text-xs font-semibold ${tone}`}>{riskLabel}</div>
                </div>
                <div className="text-right">
                  <div className="font-bold">{formatPercent(row.weight)}</div>
                  <div className="text-xs text-muted">{formatMoney(row.value)}</div>
                </div>
              </div>
              <div className="mt-3 h-2 rounded bg-paper">
                <div className={`h-2 rounded ${row.weight >= 0.2 ? "bg-danger" : row.weight >= 0.1 ? "bg-warning" : "bg-accent"}`} style={{ width: `${Math.max(4, (row.weight / maxWeight) * 100)}%` }} />
              </div>
              <div className="safe-text mt-2 text-xs text-muted">{row.topHoldings.join(" / ")} · {row.quality}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FanChart({ rows, targetAmount }: { rows: { month: number; p10: number; median: number; p90: number }[]; targetAmount: number }) {
  const max = Math.max(targetAmount, ...rows.map((row) => row.p90), 1);
  return (
    <div className="mt-4 grid gap-2">
      {rows.map((row) => (
        <div key={row.month} className="grid grid-cols-[72px_1fr] items-center gap-3">
          <span className="text-xs font-semibold text-muted">M{row.month}</span>
          <div className="relative h-8 rounded bg-panelAlt">
            <div className="absolute top-1/2 h-3 -translate-y-1/2 rounded bg-accent/20" style={{ left: `${(row.p10 / max) * 100}%`, width: `${Math.max(2, ((row.p90 - row.p10) / max) * 100)}%` }} />
            <div className="absolute top-1/2 h-5 w-1 -translate-y-1/2 rounded bg-accent" style={{ left: `${Math.min(100, (row.median / max) * 100)}%` }} />
            <div className="absolute top-0 h-8 w-px bg-warning" style={{ left: `${Math.min(100, (targetAmount / max) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function LineBars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(...rows.map((row) => row.value), 1);
  return (
    <div className="mt-4 flex h-72 items-end gap-1 overflow-hidden rounded-md border border-line bg-panelAlt p-3" aria-label="Backtest equity curve">
      {rows.map((row, index) => (
        <div key={`${row.label}-${index}`} className="min-w-2 flex-1 rounded-t bg-accent" style={{ height: `${Math.max(2, (row.value / max) * 100)}%` }} title={`${row.label}: ${formatMoney(row.value)}`} />
      ))}
    </div>
  );
}

function Compass({ rows }: { rows: ReturnType<typeof analyzePortfolio>["currentTargetRows"] }) {
  return (
    <div className="mt-4 grid gap-3">
      {rows.map((row) => (
        <div key={row.key} className="grid gap-2">
          <div className="flex justify-between gap-3 text-sm font-semibold">
            <span>{row.key}</span>
            <span className={row.drift > 0 ? "text-warning" : "text-accent"}>{row.drift > 0 ? "overweight" : "underweight"} {formatPercent(Math.abs(row.drift))}</span>
          </div>
          <div className="relative h-4 rounded bg-panelAlt">
            <div className="absolute left-1/2 top-0 h-4 w-px bg-muted" />
            <div className={`absolute top-1 h-2 rounded ${row.drift > 0 ? "bg-warning" : "bg-accent"}`} style={{ left: row.drift > 0 ? "50%" : `${50 - Math.min(48, Math.abs(row.drift) * 180)}%`, width: `${Math.max(2, Math.min(48, Math.abs(row.drift) * 180))}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function CockpitCard({
  icon,
  title,
  termKey,
  value,
  detail,
  tone = "normal"
}: {
  icon: ReactNode;
  title: string;
  termKey: string;
  value: string;
  detail: string;
  tone?: "normal" | "watch" | "risk";
}) {
  const toneClass = tone === "risk" ? "text-danger" : tone === "watch" ? "text-warning" : "text-accent";
  return (
    <div className="panel min-w-0 p-4">
      <div className={`flex items-center gap-2 text-sm font-semibold ${toneClass}`}>
        <IconWrap>{icon}</IconWrap>
        <MetricLabel label={title} termKey={termKey} />
      </div>
      <div className="safe-text mt-3 text-2xl font-bold">{value}</div>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">{detail}</p>
    </div>
  );
}

function MetricCard({ title, termKey, value }: { title: string; termKey: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panelAlt p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted"><MetricLabel label={title} termKey={termKey} /></div>
      <div className="safe-text mt-2 text-lg font-bold">{value}</div>
    </div>
  );
}

function SectionTitle({ icon, title, termKey }: { icon: ReactNode; title: string; termKey: string }) {
  return (
    <div className="flex items-center gap-2 text-lg font-bold">
      <IconWrap>{icon}</IconWrap>
      <MetricLabel label={title} termKey={termKey} />
    </div>
  );
}

function MetricLabel({ label, termKey }: { label: string; termKey: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <span className="safe-text">{label}</span>
      <TermTooltip termKey={termKey} />
    </span>
  );
}

function IconWrap({ children }: { children: ReactNode }) {
  return <span className="[&>svg]:h-4 [&>svg]:w-4">{children}</span>;
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panelAlt p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted">
        <MetricLabel label={label} termKey={statusPillTermKey(label)} />
      </div>
      <div className="safe-text mt-1 font-bold">{value}</div>
    </div>
  );
}

function statusPillTermKey(label: string) {
  const normalized = label.toLowerCase();
  if (normalized.includes("currency")) return "base_currency";
  if (normalized.includes("fee")) return "fee_drag";
  if (normalized.includes("drift")) return "allocation_drift";
  if (normalized.includes("holdings")) return "asset_allocation";
  if (normalized.includes("storage") || normalized.includes("data") || normalized.includes("mode")) return "data_quality";
  if (normalized.includes("paths") || normalized.includes("method")) return "monte_carlo";
  if (normalized.includes("execution")) return "rebalancing";
  return "data_quality";
}

function StepCard({ number, title, body }: { number: string; title: string; body: string }) {
  return (
    <div className="panel p-4">
      <div className="grid h-9 w-9 place-items-center rounded-md bg-accent text-sm font-bold text-paper">{number}</div>
      <h2 className="mt-4 text-xl font-bold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
    </div>
  );
}

function NumberField({ label, termKey, value, onChange }: { label: string; termKey: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="mt-4 block text-sm font-semibold">
      <MetricLabel label={label} termKey={termKey} />
      <input className="input-control mt-2 w-full" type="number" min={0} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function PercentField({ label, termKey, value, onChange }: { label: string; termKey: string; value: number; onChange: (value: number) => void }) {
  return (
    <label className="mt-4 block text-sm font-semibold">
      <MetricLabel label={label} termKey={termKey} />
      <input className="input-control mt-2 w-full" type="number" min={0} step={0.01} value={(value * 100).toFixed(2)} onChange={(event) => onChange(Number(event.target.value) / 100)} />
    </label>
  );
}

function ManualTextField({
  label,
  value,
  onChange,
  required = false,
  maxLength = MANUAL_TEXT_MAX_LENGTH,
  pattern
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  maxLength?: number;
  pattern?: string;
}) {
  const id = useId();
  const invalid = required && !value.trim();
  return (
    <label className="block text-xs font-semibold" htmlFor={id}>
      {label}{required ? "*" : ""}
      <input
        id={id}
        className="input-control mt-1 w-full"
        required={required}
        maxLength={maxLength}
        pattern={pattern}
        aria-invalid={invalid || undefined}
        value={value}
        onChange={(event) => onChange(event.target.value.slice(0, maxLength))}
      />
    </label>
  );
}

function ManualNumberField({
  label,
  value,
  onChange,
  required = false,
  min,
  max
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  min: number;
  max: number;
}) {
  const id = useId();
  const numeric = value.trim() ? Number(value) : NaN;
  const invalid = required ? !Number.isFinite(numeric) || numeric < min || numeric > max : value.trim() ? !Number.isFinite(numeric) || numeric < min || numeric > max : false;
  return (
    <label className="block text-xs font-semibold" htmlFor={id}>
      {label}{required ? "*" : ""}
      <input
        id={id}
        className="input-control mt-1 w-full"
        type="number"
        min={min}
        max={max}
        required={required}
        aria-invalid={invalid || undefined}
        value={value}
        onChange={(event) => onChange(event.target.value.slice(0, 24))}
      />
    </label>
  );
}

function TablePanel({ title, termKey, children }: { title: string; termKey: string; children: ReactNode }) {
  return (
    <div className="panel min-w-0 p-4">
      <SectionTitle icon={<FileSpreadsheet />} title={title} termKey={termKey} />
      <div className="table-surface mt-4">
        <div className="min-w-[720px] divide-y divide-line">{children}</div>
      </div>
    </div>
  );
}

function TableRow({ cells }: { cells: ReactNode[] }) {
  return (
    <div className="grid gap-3 px-3 py-3 text-sm even:bg-panelAlt/50" style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(120px, 1fr))` }}>
      {cells.map((cell, index) => (
        <div key={index} className="safe-text min-w-0">
          {cell}
        </div>
      ))}
    </div>
  );
}

function SideLinks({ active, links }: { active: PortfolioSection; links: readonly (readonly [PortfolioSection, string, string])[] }) {
  const navigate = useNavigate();
  return (
    <nav className="panel grid content-start gap-2 p-3" aria-label="Subsection navigation">
      {links.map(([key, label, href]) => (
        <a
          key={key}
          href={href}
          onClick={(event) => {
            event.preventDefault();
            void navigate({ to: href as never });
          }}
          className={`focus-ring rounded-md px-3 py-3 text-sm font-semibold ${active === key ? "bg-accentSoft text-accent" : "text-muted hover:bg-panelAlt hover:text-ink"}`}
        >
          {label}
        </a>
      ))}
    </nav>
  );
}

function normalizedInstrumentId(value: string) {
  return value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "-").replace(/-+/g, "-");
}

function toSafeId(value: string) {
  const safe = value.trim().toLowerCase().replace(/[^a-z0-9]/g, "-").replace(/-+/g, "-");
  return safe.replace(/^-|-$/g, "") || "holding";
}

type StoredPortfolioWorkspace = {
  version: number;
  portfolio: Portfolio;
  manualInstruments: Instrument[];
  reviewRequests: InstrumentReviewRequest[];
  assumptions: AssumptionSet;
};

function createPortfolioForWorkspace(portfolioId: string): Portfolio {
  const demo = createDemoPortfolio();
  if (portfolioId === demo.portfolioId) return demo;
  return {
    ...demo,
    portfolioId,
    name: `${portfolioId} workspace`,
    description: "User-local planning workspace based on the demo template.",
    isDemo: false,
    holdings: demo.holdings.map((holding) => ({ ...holding, portfolioId })),
    transactions: [],
    taxLots: [],
    goal: { ...demo.goal, portfolioId }
  };
}

function workspaceStorageKey(portfolioId: string) {
  return `${PORTFOLIO_WORKSPACE_STORAGE_PREFIX}${toSafeId(portfolioId)}`;
}

function canPersistWorkspace(portfolioId: string) {
  return portfolioId === "demo-growth-income";
}

function loadPortfolioWorkspace(portfolioId: string): StoredPortfolioWorkspace | null {
  if (!canPersistWorkspace(portfolioId)) return null;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(workspaceStorageKey(portfolioId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredPortfolioWorkspace>;
    if (parsed.version !== PORTFOLIO_WORKSPACE_STORAGE_VERSION || !parsed.portfolio) return null;
    return {
      version: PORTFOLIO_WORKSPACE_STORAGE_VERSION,
      portfolio: parsed.portfolio,
      manualInstruments: parsed.manualInstruments ?? [],
      reviewRequests: parsed.reviewRequests ?? [],
      assumptions: parsed.assumptions ?? defaultAssumptions
    };
  } catch {
    return null;
  }
}

function savePortfolioWorkspace(portfolioId: string, workspace: Omit<StoredPortfolioWorkspace, "version">) {
  if (!canPersistWorkspace(portfolioId)) return;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      workspaceStorageKey(portfolioId),
      JSON.stringify({ version: PORTFOLIO_WORKSPACE_STORAGE_VERSION, ...workspace })
    );
  } catch {
    // Browser storage may be disabled or full; the workspace still functions as an in-memory session.
  }
}

function clearSourceLinkedRecords(portfolio: Portfolio): Portfolio {
  if (!portfolio.transactions.length && !portfolio.taxLots.length) return portfolio;
  return { ...portfolio, transactions: [], taxLots: [] };
}

function cleanManualText(value: string) {
  return value.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, MANUAL_TEXT_MAX_LENGTH);
}

function cleanCurrency(value: string) {
  const normalized = value.trim().toUpperCase().replace(/[^A-Z]/g, "").slice(0, 3);
  return /^[A-Z]{3}$/.test(normalized) ? normalized : "USD";
}

function validateManualDraft(draft: ManualHoldingDraft): string[] {
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

function portfolioIdFromPath(pathname: string): string | null {
  const path = pathname.replace(/^\/(en|ko)(?=\/|$)/, "") || "/";
  const match = path.match(/^\/portfolios\/([^/]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function sectionFromPath(pathname: string): PortfolioSection {
  const path = pathname.replace(/^\/(en|ko)(?=\/|$)/, "") || "/";
  if (path === "/portfolio" || path === "/dashboard") return "dashboard";
  if (path === "/onboarding") return "onboarding";
  if (path === "/portfolios") return "portfolios";
  if (path.includes("/portfolio/glossary")) return "glossary";
  if (path === "/settings") return "settings-profile";
  if (/^\/portfolios\/[^/]+$/.test(path)) return "overview";
  const endings: [string, PortfolioSection][] = [
    ["/xray", "xray"],
    ["/atlas", "atlas"],
    ["/builder", "builder"],
    ["/backtest", "backtest"],
    ["/monte-carlo", "monte-carlo"],
    ["/rebalance", "rebalance"],
    ["/fees", "fees"],
    ["/tax-lots", "tax-lots"],
    ["/holdings", "holdings"],
    ["/transactions", "transactions"],
    ["/settings/profile", "settings-profile"],
    ["/settings/assumptions", "settings-assumptions"],
    ["/settings/data-sources", "settings-data-sources"],
    ["/settings/security", "settings-security"]
  ];
  return endings.find(([ending]) => path.endsWith(ending))?.[1] ?? "dashboard";
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}
