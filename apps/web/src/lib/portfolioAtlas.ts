export type QualityLevel =
  | "COMPLETE"
  | "PARTIAL"
  | "PROXY"
  | "STALE"
  | "USER_PROVIDED"
  | "ESTIMATED"
  | "UNAVAILABLE";

export type AssetClass =
  | "Cash & Cash Equivalents"
  | "Fixed Income"
  | "Equity"
  | "Real Assets"
  | "Alternatives"
  | "Crypto / Digital Assets"
  | "Derivatives / Leveraged Products"
  | "Other Assets"
  | "Liabilities";

export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "DEAD_LETTER";
export type JobType =
  | "PRICE_REFRESH"
  | "FX_REFRESH"
  | "INSTRUMENT_CLASSIFICATION"
  | "ETF_LOOKTHROUGH_REFRESH"
  | "BACKTEST"
  | "MONTE_CARLO"
  | "REBALANCE_PLAN"
  | "TAX_LOT_ESTIMATE"
  | "PDF_REPORT"
  | "AI_SUMMARY"
  | "DATA_IMPORT";

export interface DataQualityIssue {
  issueId: string;
  metricKey: string;
  severity: "info" | "warning" | "critical";
  qualityLevel: QualityLevel;
  reason: string;
  affectedWeightPercent?: number;
}

export type InstrumentIdentifierType = "ISIN" | "FIGI" | "CUSIP" | "SEDOL" | "LOCAL_CODE" | "RIC" | "OTHER";

export interface InstrumentIdentifier {
  type: InstrumentIdentifierType;
  value: string;
}

export interface InstrumentListing {
  listingId: string;
  symbol: string;
  exchange: string;
  country: string;
  currency: string;
  localCode?: string;
  isPrimary?: boolean;
  isActive?: boolean;
}

export interface Instrument {
  instrumentId: string;
  symbol: string;
  exchange: string;
  name: string;
  instrumentType: "stock" | "etf" | "bond" | "cash" | "crypto" | "manual" | "leveraged";
  isActive?: boolean;
  assetClass: AssetClass;
  subAssetClass: string;
  country: string;
  domicileCountry: string;
  currency: string;
  sector: string;
  industry: string;
  theme: string[];
  expenseRatio: number;
  leverageFlag?: boolean;
  inverseFlag?: boolean;
  fundFlag?: boolean;
  dataQualityScore: number;
  currentPrice: number;
  previousClose: number;
  priceAsOf: string;
  priceQuality: QualityLevel;
  aliases?: string[];
  identifiers?: InstrumentIdentifier[];
  listings?: InstrumentListing[];
  primaryListingId?: string;
  lookThroughHoldings?: { symbol: string; weight: number }[];
}

export interface Holding {
  holdingId: string;
  portfolioId: string;
  accountId: string;
  instrumentId: string;
  listingId?: string;
  quantity: number;
  manualPrice?: number;
  manualMarketValue?: number;
  currency: string;
  source: "manual" | "csv" | "sample";
}

export interface InstrumentSearchResult {
  instrumentId: string;
  listingId: string;
  displaySymbol: string;
  name: string;
  exchange: string;
  country: string;
  currency: string;
  assetClass: string;
  instrumentType: Instrument["instrumentType"];
  sector: string;
  isPrimaryListing: boolean;
  isAdvancedInstrument: boolean;
  isActive: boolean;
  isStale: boolean;
  qualityLevel: QualityLevel;
  qualityMessage: string;
  score: number;
  matchedOn: string[];
  tooltipKeys: string[];
}

export interface InstrumentSearchOptions {
  limit?: number;
  includeAdvanced?: boolean;
  includeInactive?: boolean;
  country?: string;
  exchange?: string;
  context?: "HOLDING_ENTRY" | "TAX_LOT" | "BUILDER" | "IMPORT_RECONCILIATION";
}

export interface Transaction {
  transactionId: string;
  portfolioId: string;
  accountId: string;
  instrumentId: string;
  type: "BUY" | "SELL" | "DIVIDEND" | "DEPOSIT" | "WITHDRAWAL" | "FEE";
  date: string;
  quantity: number;
  price: number;
  fees: number;
  amount: number;
  currency: string;
}

export interface TaxLot {
  lotId: string;
  portfolioId: string;
  accountId: string;
  instrumentId: string;
  purchaseDate: string;
  quantityOriginal: number;
  quantityRemaining: number;
  costBasisPerUnit: number;
  fees: number;
  currency: string;
  currentPrice: number;
  source: "manual" | "csv" | "sample";
}

export interface Goal {
  goalId: string;
  portfolioId: string;
  targetAmount: number;
  targetDate: string;
  monthlyContribution: number;
  inflationAssumption: number;
}

export interface Portfolio {
  portfolioId: string;
  userId: string;
  name: string;
  baseCurrency: string;
  description: string;
  isDemo: boolean;
  cashBalance: number;
  holdings: Holding[];
  transactions: Transaction[];
  taxLots: TaxLot[];
  targetAllocation: Record<string, number>;
  goal: Goal;
}

export interface AssumptionSet {
  assumptionId: string;
  name: string;
  riskFreeRate: number;
  downsideTargetRate: number;
  expectedReturnByAssetClass: Record<string, number>;
  volatilityByAssetClass: Record<string, number>;
  correlationMatrix: Record<string, Record<string, number>>;
  platformFeeRate: number;
  fxFeeRate: number;
  taxDragRate: number;
  rebalanceBand: number;
}

export interface ExposureRow {
  key: string;
  label: string;
  value: number;
  weight: number;
  topHoldings: string[];
  quality: QualityLevel;
}

export interface PortfolioAnalysis {
  portfolioValue: number;
  netInvestedCapital: number;
  totalGainLoss: number;
  totalGainLossPercent: number;
  weightedExpenseRatio: number;
  estimatedAnnualFees: number;
  hhi: number;
  top5Concentration: number;
  diversificationScore: number;
  assetAllocation: ExposureRow[];
  geographicExposure: ExposureRow[];
  currencyExposure: ExposureRow[];
  sectorExposure: ExposureRow[];
  themeExposure: ExposureRow[];
  topHoldings: ExposureRow[];
  allocationDrift: number;
  currentTargetRows: AllocationDriftRow[];
  dataFreshnessScore: number;
  dataQualityIssues: DataQualityIssue[];
  healthSummary: string;
}

export interface AllocationDriftRow {
  key: string;
  currentWeight: number;
  targetWeight: number;
  drift: number;
  dollarsToTarget: number;
}

export interface BacktestResult {
  endingValue: number;
  cagr: number;
  annualizedVolatility: number;
  maxDrawdown: number;
  bestYear: number;
  worstYear: number;
  rolling12MonthReturns: number[];
  rolling36MonthReturns: number[];
  sharpe: number | null;
  sortino: number | null;
  benchmarkRelativeReturn: number;
  trackingError: number;
  equityCurve: { date: string; value: number; benchmarkValue: number }[];
  drawdowns: { date: string; value: number }[];
  dataQualityIssues: DataQualityIssue[];
}

export interface MonteCarloResult {
  successProbability: number;
  medianOutcome: number;
  p10Outcome: number;
  p90Outcome: number;
  p5Outcome: number;
  p95Outcome: number;
  shortfallProbability: number;
  medianShortfallAmount: number;
  requiredMonthlyContribution: number;
  estimatedBadCaseDrawdown: number;
  pathCount: number;
  method: "normal" | "bootstrap" | "fat_tail";
  fanChart: { month: number; p10: number; median: number; p90: number }[];
  dataQualityIssues: DataQualityIssue[];
}

export interface RebalancePlan {
  currentWeight: Record<string, number>;
  targetWeight: Record<string, number>;
  drift: Record<string, number>;
  cashContributionPlan: { assetClass: string; amount: number; reason: string }[];
  estimatedMonthsToTarget: number;
  optionalSellTrades: { assetClass: string; amount: number }[];
  optionalBuyTrades: { assetClass: string; amount: number }[];
  estimatedFees: number;
  estimatedTaxableGain: number;
  postRebalanceWeights: Record<string, number>;
  warnings: string[];
  dataQualityIssues: DataQualityIssue[];
}

export interface TaxLotImpact {
  method: "FIFO" | "HIGHEST_COST_FIRST" | "LOWEST_GAIN_FIRST";
  sellQuantity: number;
  realizedGain: number;
  estimatedFees: number;
  lotsUsed: { lotId: string; quantity: number; gain: number; holdingPeriodDays: number }[];
  warning: string;
}

export interface FundOverlapRow {
  pairKey: string;
  leftSymbol: string;
  rightSymbol: string;
  overlapWeight: number;
  sharedHoldings: { symbol: string; weight: number }[];
  quality: QualityLevel;
}

export interface CsvValidationOptions {
  portfolioId?: string;
  knownSymbols?: string[];
  maxBytes?: number;
  maxRows?: number;
  fileName?: string;
  mimeType?: string;
  rejectUnknownSymbols?: boolean;
}

export interface FeatureGate {
  key: string;
  displayName: string;
  description: string;
  enabledGlobally: boolean;
  enabledForFreeUsers: boolean;
  enabledForPaidUsers: boolean;
  enabledForAdmins: boolean;
  rolloutPercentage: number;
  hardDisabled: boolean;
}

export interface UsageQuota {
  resource: string;
  freeUserDefault: number;
  adminDefault: number | "bypass_user_limit";
  used: number;
  resetsAt: string;
}

export interface PortfolioJob {
  jobId: string;
  userId: string;
  portfolioId?: string;
  jobType: JobType;
  status: JobStatus;
  priority: number;
  idempotencyKey: string;
  progressPercent: number;
  attempts: number;
  maxAttempts: number;
  createdAt: string;
}

const MONTHS_PER_YEAR = 12;
const TRADING_DAYS_PER_YEAR = 252;
const MS_PER_DAY = 86_400_000;
const SEARCH_CACHE_MAX_RESULTS = 25;
const SEARCH_CACHE_MAX_ENTRIES = 200;
const SEARCH_QUERY_MAX_LENGTH = 80;
const SEARCH_PRICE_STALE_DAYS = 2;
const SEARCH_HARD_STALE_DAYS = 14;
const INSTRUMENT_SEARCH_RESULTS_TTL_MS = 30000;
const instrumentSearchCache = new Map<string, { expiresAt: number; results: InstrumentSearchResult[] }>();
const instrumentIndexCache = new WeakMap<Instrument[], InstrumentIndex>();

export const INSTRUMENT_SEARCH_QUERY_MAX_LENGTH = SEARCH_QUERY_MAX_LENGTH;

interface InstrumentSearchToken {
  value: string;
  normalized: string;
  compact: string;
  matchType: string;
}

interface InstrumentSearchEntry {
  instrument: Instrument;
  listing: InstrumentListing;
  tokens: InstrumentSearchToken[];
  isPrimaryListing: boolean;
  isActive: boolean;
}

interface InstrumentIndex {
  cacheKey: string;
  entries: InstrumentSearchEntry[];
  byInstrumentId: Map<string, Instrument>;
  byListingId: Map<string, Instrument>;
  byReference: Map<string, Instrument>;
}

const QUALITY_MESSAGES: Record<QualityLevel, string> = {
  COMPLETE: "The app has enough metadata to classify this instrument for portfolio analysis.",
  PARTIAL: "The app has incomplete classification data for this instrument. Some portfolio metrics may be estimated or unavailable.",
  PROXY: "The app is using proxy metadata; results are approximate.",
  STALE: "This instrument record may be stale. Verify the exchange, currency, and symbol before adding it.",
  USER_PROVIDED: "This data was entered manually and may not be independently verified.",
  ESTIMATED: "Some fields are estimated. Results may be approximate.",
  UNAVAILABLE: "The app cannot fully classify or price this instrument yet."
};

const TOOLTIP_KEYS = {
  ticker: "ticker",
  symbol: "symbol",
  exchange: "exchange",
  country: "country",
  currency: "currency",
  assetClass: "asset_class",
  instrumentType: "instrument_type",
  dataQuality: "data_quality",
  sector: "sector",
  advancedInstrument: "advanced_instrument",
  inactiveSecurity: "inactive_security",
  staleData: "stale_data",
  partialData: "partial_data",
  estimatedData: "estimated_data"
} as const;

function normalizeSearchQuery(rawQuery: string): string {
  return rawQuery
    .slice(0, SEARCH_QUERY_MAX_LENGTH)
    .normalize("NFKC")
    .toUpperCase()
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2212]/g, "-")
    .replace(/[^\p{L}\p{N}.\-\/\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeSymbol(value: string): string {
  return normalizeSearchQuery(value).replace(/\//g, "-").replace(/\s+/g, "");
}

function isLikelySymbolQuery(query: string): boolean {
  return query.length > 0 && /^[\p{L}\p{N}.\-]+$/u.test(query);
}

function primaryListingFor(instrument: Instrument): InstrumentListing {
  const explicit = instrument.listings?.find((listing) => listing.listingId === instrument.primaryListingId);
  const primary = explicit ?? instrument.listings?.find((listing) => listing.isPrimary) ?? instrument.listings?.[0];
  return (
    primary ?? {
      listingId: `${instrument.exchange}:${instrument.symbol}`,
      symbol: instrument.symbol,
      exchange: instrument.exchange,
      country: instrument.country,
      currency: instrument.currency,
      localCode: instrument.symbol,
      isPrimary: true,
      isActive: instrument.isActive ?? true
    }
  );
}

function listingSetFor(instrument: Instrument): InstrumentListing[] {
  return instrument.listings?.length ? instrument.listings : [primaryListingFor(instrument)];
}

function token(value: string | undefined, matchType: string): InstrumentSearchToken | null {
  const normalized = normalizeSearchQuery(value ?? "");
  if (!normalized) return null;
  return { value: value ?? "", normalized, compact: normalizeSymbol(normalized), matchType };
}

function addReference(map: Map<string, Instrument>, reference: string | undefined, instrument: Instrument) {
  const normalized = normalizeSymbol(reference ?? "");
  if (normalized && !map.has(normalized)) map.set(normalized, instrument);
}

function getInstrumentIndex(instruments: Instrument[]): InstrumentIndex {
  const cached = instrumentIndexCache.get(instruments);
  if (cached) return cached;
  const entries: InstrumentSearchEntry[] = [];
  const byInstrumentId = new Map<string, Instrument>();
  const byListingId = new Map<string, Instrument>();
  const byReference = new Map<string, Instrument>();

  for (const instrument of instruments) {
    addReference(byInstrumentId, instrument.instrumentId, instrument);
    addReference(byReference, instrument.instrumentId, instrument);
    addReference(byReference, instrument.symbol, instrument);
    for (const identifier of instrument.identifiers ?? []) addReference(byReference, identifier.value, instrument);
    for (const alias of instrument.aliases ?? []) addReference(byReference, alias, instrument);

    for (const listing of listingSetFor(instrument)) {
      addReference(byListingId, listing.listingId, instrument);
      addReference(byReference, listing.listingId, instrument);
      addReference(byReference, listing.symbol, instrument);
      addReference(byReference, listing.localCode, instrument);
      const rawTokens = [
        token(listing.symbol, "SYMBOL"),
        token(listing.localCode, "LOCAL_CODE"),
        token(instrument.name, "NAME"),
        ...((instrument.aliases ?? []).map((alias) => token(alias, "ALIAS"))),
        ...((instrument.identifiers ?? []).map((identifier) => token(identifier.value, identifier.type)))
      ];
      entries.push({
        instrument,
        listing,
        tokens: rawTokens.filter((item): item is InstrumentSearchToken => Boolean(item)),
        isPrimaryListing: listing.isPrimary ?? listing.listingId === primaryListingFor(instrument).listingId,
        isActive: (instrument.isActive ?? true) && (listing.isActive ?? true)
      });
    }
  }

  const cacheKey = instruments
    .map((instrument) => `${instrument.instrumentId}:${instrument.primaryListingId ?? primaryListingFor(instrument).listingId}:${instrument.priceAsOf}`)
    .join("|");
  const index = { cacheKey, entries, byInstrumentId, byListingId, byReference };
  instrumentIndexCache.set(instruments, index);
  return index;
}

function scoreTokenForQuery(tokenInfo: InstrumentSearchToken, normalized: string, querySymbol: string): { score: number; matchedOn: string | null } {
  const normalizedToken = tokenInfo.normalized;
  const compactToken = tokenInfo.compact;
  const exact = normalizedToken === normalized || compactToken === querySymbol;
  const prefix = normalizedToken.startsWith(normalized) || compactToken.startsWith(querySymbol);
  const includes = normalizedToken.includes(normalized) || compactToken.includes(querySymbol);
  const wordsMatch = normalized.split(" ").some((word) => word.length > 1 && normalizedToken.includes(word));
  const kind = tokenInfo.matchType;
  const exactBase = kind === "SYMBOL" ? 1000 : kind === "LOCAL_CODE" ? 960 : ["ISIN", "FIGI", "CUSIP", "SEDOL", "RIC"].includes(kind) ? 940 : kind === "NAME" ? 700 : 640;
  const prefixBase = kind === "SYMBOL" ? 800 : kind === "LOCAL_CODE" ? 760 : ["ISIN", "FIGI", "CUSIP", "SEDOL", "RIC"].includes(kind) ? 720 : kind === "NAME" ? 500 : 460;
  const includeBase = kind === "SYMBOL" ? 550 : kind === "LOCAL_CODE" ? 520 : kind === "NAME" ? 350 : 320;
  if (exact) return { score: exactBase, matchedOn: `${kind}_EXACT` };
  if (prefix) return { score: prefixBase, matchedOn: `${kind}_PREFIX` };
  if (includes) return { score: includeBase, matchedOn: `${kind}_MATCH` };
  if (kind === "NAME" && wordsMatch) return { score: 125, matchedOn: "NAME_TOKEN" };
  return { score: 0, matchedOn: null };
}

function setSearchCache(cacheKey: string, results: InstrumentSearchResult[]) {
  for (const [key, cached] of instrumentSearchCache) {
    if (cached.expiresAt <= Date.now()) instrumentSearchCache.delete(key);
  }
  while (instrumentSearchCache.size >= SEARCH_CACHE_MAX_ENTRIES) {
    const oldestKey = instrumentSearchCache.keys().next().value;
    if (!oldestKey) break;
    instrumentSearchCache.delete(oldestKey);
  }
  instrumentSearchCache.set(cacheKey, { expiresAt: Date.now() + INSTRUMENT_SEARCH_RESULTS_TTL_MS, results });
}

function isAdvancedInstrument(instrument: Instrument): boolean {
  const tokenSource = `${instrument.instrumentType} ${instrument.subAssetClass} ${instrument.assetClass} ${instrument.name}`.toLowerCase();
  return (
    ["manual", "leveraged"].includes(instrument.instrumentType) ||
    tokenSource.includes("preferred") ||
    tokenSource.includes("warrant") ||
    tokenSource.includes("right") ||
    tokenSource.includes("unit") ||
    tokenSource.includes("adr") ||
    tokenSource.includes("gdr")
  );
}

function isPriceStale(priceAsOf: string, staleAfterDays: number) {
  const lastUpdate = new Date(priceAsOf);
  if (!Number.isFinite(lastUpdate.getTime())) return false;
  return (Date.now() - lastUpdate.getTime()) / MS_PER_DAY > staleAfterDays;
}

function qualityFromRecord(instrument: Instrument): QualityLevel {
  if (isPriceStale(instrument.priceAsOf, SEARCH_HARD_STALE_DAYS)) return "STALE";
  if (instrument.priceQuality === "STALE") return "STALE";
  return instrument.priceQuality;
}

export function searchInstruments(
  query: string,
  instruments: Instrument[],
  options: InstrumentSearchOptions = {}
): InstrumentSearchResult[] {
  const normalized = normalizeSearchQuery(query);
  if (!normalized) return [];
  const includeAdvanced = options.includeAdvanced ?? false;
  const includeInactive = options.includeInactive ?? false;
  const minLength = isLikelySymbolQuery(normalized) ? 1 : 2;
  if (normalized.length < minLength) return [];
  const limit = Math.max(1, Math.min(SEARCH_CACHE_MAX_RESULTS, options.limit ?? 10));
  const index = getInstrumentIndex(instruments);
  const cacheKey = JSON.stringify({
    index: index.cacheKey,
    query: normalized,
    includeAdvanced,
    includeInactive,
    country: options.country ?? null,
    exchange: options.exchange ?? null,
    context: options.context ?? "HOLDING_ENTRY",
    limit
  });
  const cached = instrumentSearchCache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.results.slice(0, limit);
  }
  if (cached) instrumentSearchCache.delete(cacheKey);

  const querySymbol = normalizeSymbol(normalized);
  const bestByListing = new Map<string, InstrumentSearchResult>();

  for (const entry of index.entries) {
    const { instrument, listing } = entry;
    if (options.country && listing.country.toUpperCase() !== options.country.toUpperCase()) continue;
    if (options.exchange && listing.exchange.toUpperCase() !== options.exchange.toUpperCase()) continue;
    const isActive = entry.isActive;
    if (!isActive && !includeInactive) continue;

    const isAdvanced = isAdvancedInstrument(instrument);
    const exactSymbolMatch = normalizeSymbol(listing.symbol) === querySymbol || normalizeSymbol(instrument.symbol) === querySymbol;
    const exactNameMatch = normalizeSearchQuery(instrument.name) === normalized;
    if (isAdvanced && !includeAdvanced && !exactSymbolMatch && !exactNameMatch) continue;

    let score = 0;
    const matchedOn: string[] = [];
    for (const tokenInfo of entry.tokens) {
      const tokenScore = scoreTokenForQuery(tokenInfo, normalized, querySymbol);
      if (tokenScore.score > 0) {
        score += tokenScore.score;
        if (tokenScore.matchedOn) matchedOn.push(tokenScore.matchedOn);
      }
    }
    if (score === 0) continue;

    if (isActive) score += 150;
    if (entry.isPrimaryListing) score += 80;
    if (listing.currency === "USD") score += 20;
    if (instrument.instrumentType === "etf" || instrument.instrumentType === "stock") score += 50;

    const stale = isPriceStale(instrument.priceAsOf, SEARCH_PRICE_STALE_DAYS);
    if (stale) score -= 80;

    const qualityLevel = qualityFromRecord(instrument);
    const qualityMessages = [QUALITY_MESSAGES[qualityLevel]];
    if (instrument.leverageFlag || instrument.inverseFlag) {
      qualityMessages.push("This is a leveraged or inverse product. Confirm suitability before adding.");
    }
    if (!instrument.isActive) {
      qualityMessages.push("This security is inactive in current catalog settings.");
    }
    const qualityMessage = qualityMessages.join(" ");

    const tooltipKeys: string[] = [TOOLTIP_KEYS.ticker, TOOLTIP_KEYS.exchange, TOOLTIP_KEYS.assetClass, TOOLTIP_KEYS.instrumentType, TOOLTIP_KEYS.currency, TOOLTIP_KEYS.country, TOOLTIP_KEYS.dataQuality, TOOLTIP_KEYS.sector];
    if (isAdvanced) tooltipKeys.push(TOOLTIP_KEYS.advancedInstrument);
    if (!isActive) tooltipKeys.push(TOOLTIP_KEYS.inactiveSecurity);
    if (qualityLevel === "STALE") tooltipKeys.push(TOOLTIP_KEYS.staleData);
    if (qualityLevel === "PARTIAL") tooltipKeys.push(TOOLTIP_KEYS.partialData);
    if (qualityLevel === "ESTIMATED") tooltipKeys.push(TOOLTIP_KEYS.estimatedData);

    const result = {
      instrumentId: instrument.instrumentId,
      listingId: listing.listingId,
      displaySymbol: listing.symbol.toUpperCase(),
      name: instrument.name,
      exchange: listing.exchange,
      country: listing.country,
      currency: listing.currency,
      assetClass: instrument.assetClass,
      instrumentType: instrument.instrumentType,
      sector: instrument.sector,
      isPrimaryListing: entry.isPrimaryListing,
      isAdvancedInstrument: isAdvanced,
      isActive,
      isStale: stale,
      qualityLevel,
      qualityMessage,
      score,
      matchedOn: [...new Set(matchedOn)],
      tooltipKeys
    };
    const previous = bestByListing.get(result.listingId);
    if (!previous || result.score > previous.score) bestByListing.set(result.listingId, result);
  }

  const sorted = [...bestByListing.values()].sort((left, right) => {
    if (right.score !== left.score) return right.score - left.score;
    return left.displaySymbol.localeCompare(right.displaySymbol);
  });
  const limited = sorted.slice(0, limit);
  setSearchCache(cacheKey, sorted.slice(0, SEARCH_CACHE_MAX_RESULTS));
  return limited;
}

export function resolveInstrumentReference(reference: string, instruments: Instrument[]): Instrument | undefined {
  const normalized = normalizeSymbol(reference);
  if (!normalized) return undefined;
  const index = getInstrumentIndex(instruments);
  return index.byInstrumentId.get(normalized) ?? index.byListingId.get(normalized) ?? index.byReference.get(normalized);
}

export function resolveInstrumentSearchResult(reference: string, instruments: Instrument[]): InstrumentSearchResult | undefined {
  return searchInstruments(reference, instruments, { includeAdvanced: true, includeInactive: true, limit: 1 })[0];
}

export function instrumentReferenceKeys(instrument: Instrument): string[] {
  return [
    instrument.instrumentId,
    instrument.symbol,
    ...(instrument.aliases ?? []),
    ...((instrument.identifiers ?? []).map((identifier) => identifier.value)),
    ...listingSetFor(instrument).flatMap((listing) => [listing.listingId, listing.symbol, listing.localCode ?? ""])
  ].filter(Boolean);
}

export const demoInstruments: Instrument[] = [
  instrument("AAPL", "Apple Inc.", "NASDAQ", "Equity", "Single Stocks", "US", "USD", "Information Technology", ["Big Tech", "AI infrastructure"], 195.4, 194.2, 0, false, undefined, {
    aliases: ["Apple", "Apple Computer"],
    identifiers: [
      { type: "ISIN", value: "US0378331005" },
      { type: "FIGI", value: "BBG000B9XRY4" }
    ]
  }),
  instrument("MSFT", "Microsoft Corp.", "NASDAQ", "Equity", "Single Stocks", "US", "USD", "Information Technology", ["Big Tech", "AI infrastructure"], 425.7, 421.3, 0, false, undefined, {
    aliases: ["Microsoft"],
    identifiers: [
      { type: "ISIN", value: "US5949181045" },
      { type: "FIGI", value: "BBG000BPH459" }
    ]
  }),
  instrument("NVDA", "NVIDIA Corporation", "NASDAQ", "Equity", "Single Stocks", "US", "USD", "Information Technology", ["AI infrastructure", "Semiconductors"], 1120.0, 1108.5, 0, false, undefined, {
    aliases: ["Nvidia", "NVIDIA Corp"],
    identifiers: [{ type: "ISIN", value: "US67066G1040" }]
  }),
  instrument("TSLA", "Tesla, Inc.", "NASDAQ", "Equity", "Single Stocks", "US", "USD", "Consumer Discretionary", ["EV", "Big Tech"], 180.2, 178.9, 0, false, undefined, {
    aliases: ["Tesla"],
    identifiers: [{ type: "ISIN", value: "US88160R1014" }]
  }),
  instrument("005930.KS", "Samsung Electronics Co., Ltd.", "KRX", "Equity", "Single Stocks", "Korea", "KRW", "Information Technology", ["Semiconductors", "Korea"], 75_300, 74_800, 0, false, undefined, {
    aliases: ["Samsung Electronics", "삼성전자"],
    identifiers: [
      { type: "ISIN", value: "KR7005930003" },
      { type: "LOCAL_CODE", value: "005930" }
    ],
    listings: [
      {
        listingId: "KRX:005930",
        symbol: "005930.KS",
        exchange: "KRX",
        country: "Korea",
        currency: "KRW",
        localCode: "005930",
        isPrimary: true,
        isActive: true
      }
    ],
    primaryListingId: "KRX:005930"
  }),
  instrument("VXUS", "Vanguard Total International Stock ETF", "NASDAQ", "Equity", "Developed ex-US Equity", "Global ex-US", "USD", "Multi-sector", ["Global diversification"], 62.1, 61.8, 0.0007, true, [
    { symbol: "TSM", weight: 0.031 },
    { symbol: "NOVO.B", weight: 0.019 },
    { symbol: "ASML", weight: 0.016 },
    { symbol: "NESN", weight: 0.015 }
  ]),
  instrument("TLT", "iShares 20+ Year Treasury Bond ETF", "NASDAQ", "Fixed Income", "Government Bonds", "US", "USD", "Government bonds", ["Duration hedge"], 92.4, 92.1, 0.0015, true, [
    { symbol: "US912810TZ12", weight: 0.089 },
    { symbol: "US912810UB25", weight: 0.082 },
    { symbol: "US912810UC08", weight: 0.077 }
  ]),
  instrument("SGOV", "iShares 0-3 Month Treasury Bond ETF", "NYSE", "Cash & Cash Equivalents", "T-bills", "US", "USD", "Government bonds", ["Cash management"], 100.8, 100.79, 0.0009, true, [
    { symbol: "USTBILL-1M", weight: 0.48 },
    { symbol: "USTBILL-2M", weight: 0.32 },
    { symbol: "USTBILL-3M", weight: 0.2 }
  ]),
  instrument("GLD", "SPDR Gold Shares", "NYSE", "Real Assets", "Gold", "US", "USD", "Commodities", ["Commodities"], 210.2, 209.1, 0.004, true, [
    { symbol: "GOLD-BULLION", weight: 1 }
  ]),
  instrument("BTC-USD", "Bitcoin", "CRYPTO", "Crypto / Digital Assets", "Bitcoin", "Global", "USD", "Crypto", ["Crypto ecosystem"], 67_000, 66_500, 0)
];

export const defaultAssumptions: AssumptionSet = {
  assumptionId: "default-planning",
  name: "Daily-resolution planning assumptions",
  riskFreeRate: 0.04,
  downsideTargetRate: 0,
  platformFeeRate: 0,
  fxFeeRate: 0.001,
  taxDragRate: 0.0015,
  rebalanceBand: 0.05,
  expectedReturnByAssetClass: {
    "Cash & Cash Equivalents": 0.035,
    "Fixed Income": 0.042,
    Equity: 0.075,
    "Real Assets": 0.045,
    Alternatives: 0.055,
    "Crypto / Digital Assets": 0.08,
    "Derivatives / Leveraged Products": 0.02,
    "Other Assets": 0.04,
    Liabilities: -0.05
  },
  volatilityByAssetClass: {
    "Cash & Cash Equivalents": 0.01,
    "Fixed Income": 0.09,
    Equity: 0.18,
    "Real Assets": 0.16,
    Alternatives: 0.12,
    "Crypto / Digital Assets": 0.65,
    "Derivatives / Leveraged Products": 0.55,
    "Other Assets": 0.12,
    Liabilities: 0.02
  },
  correlationMatrix: {}
};

export const featureGates: FeatureGate[] = [
  gate("FEATURE_ADVANCED_BACKTESTING", "Advanced backtesting", "Longer windows, benchmark comparison, and rebalance-frequency controls."),
  gate("FEATURE_MONTE_CARLO_HIGH_PATH_COUNT", "High-path Monte Carlo", "Allows up to 10,000 free-user paths and higher admin caps."),
  gate("FEATURE_TAX_LOT_REBALANCING", "Tax-lot rebalancing", "Estimated lot-aware rebalancing. Not tax advice."),
  gate("FEATURE_ETF_LOOKTHROUGH", "ETF look-through", "Uses public filings or user overrides where available."),
  gate("FEATURE_AI_MONTHLY_REPORT", "AI monthly report", "Queued summary generation from approved portfolio facts."),
  gate("FEATURE_PDF_EXPORT", "PDF export", "Queued report export."),
  gate("FEATURE_MULTIPLE_PORTFOLIOS", "Multiple portfolios", "Allows more than one saved portfolio."),
  gate("FEATURE_ADMIN_USAGE_DASHBOARD", "Admin usage dashboard", "Admin queue, quota, and usage views.")
];

export const usageQuotas: UsageQuota[] = [
  quota("Dashboard refreshes", 60, "bypass_user_limit"),
  quota("Manual recalculations", 20, "bypass_user_limit"),
  quota("Backtests", 10, "bypass_user_limit"),
  quota("Monte Carlo runs", 20, "bypass_user_limit"),
  quota("PDF reports", 5, 25),
  quota("CSV imports", 10, 50),
  quota("AI reports", 3, 20)
];

export const queueJobs: PortfolioJob[] = [
  job("BACKTEST", "SUCCEEDED", 100),
  job("MONTE_CARLO", "SUCCEEDED", 100),
  job("REBALANCE_PLAN", "QUEUED", 35),
  job("DATA_IMPORT", "SUCCEEDED", 100)
];

export function createDemoPortfolio(): Portfolio {
  return {
    portfolioId: "demo-growth-income",
    userId: "demo-user",
    name: "Growth + shock absorber portfolio",
    baseCurrency: "USD",
    description: "A daily-resolution sample portfolio for planning, not trading.",
    isDemo: true,
    cashBalance: 6_500,
    holdings: [
      holding("h-aapl", "AAPL", 44),
      holding("h-msft", "MSFT", 34),
      holding("h-vxus", "VXUS", 520),
      holding("h-tlt", "TLT", 180),
      holding("h-sgov", "SGOV", 85),
      holding("h-gld", "GLD", 42),
      holding("h-btc", "BTC-USD", 0.18)
    ],
    transactions: [
      txn("t-deposit-1", "DEPOSIT", "SGOV", "2024-01-02", 0, 0, 110_000),
      txn("t-aapl-1", "BUY", "AAPL", "2024-01-03", 44, 155, -6_830),
      txn("t-msft-1", "BUY", "MSFT", "2024-01-03", 34, 310, -10_550),
      txn("t-vxus-1", "BUY", "VXUS", "2024-01-05", 520, 55, -28_620),
      txn("t-tlt-1", "BUY", "TLT", "2024-02-02", 180, 91, -16_390),
      txn("t-gld-1", "BUY", "GLD", "2024-02-02", 42, 184, -7_735),
      txn("t-btc-1", "BUY", "BTC-USD", "2024-03-15", 0.18, 53_000, -9_545)
    ],
    taxLots: [
      lot("lot-aapl-1", "AAPL", "2024-01-03", 24, 155),
      lot("lot-aapl-2", "AAPL", "2025-08-12", 20, 182),
      lot("lot-msft-1", "MSFT", "2024-01-03", 34, 310),
      lot("lot-vxus-1", "VXUS", "2024-01-05", 520, 55),
      lot("lot-tlt-1", "TLT", "2024-02-02", 180, 91),
      lot("lot-gld-1", "GLD", "2024-02-02", 42, 184),
      lot("lot-btc-1", "BTC-USD", "2024-03-15", 0.18, 53_000)
    ],
    targetAllocation: {
      Equity: 0.62,
      "Fixed Income": 0.2,
      "Cash & Cash Equivalents": 0.05,
      "Real Assets": 0.1,
      "Crypto / Digital Assets": 0.03
    },
    goal: {
      goalId: "goal-demo",
      portfolioId: "demo-growth-income",
      targetAmount: 300_000,
      targetDate: "2036-12-31",
      monthlyContribution: 1_200,
      inflationAssumption: 0.025
    }
  };
}

export function analyzePortfolio(
  portfolio: Portfolio,
  instruments: Instrument[],
  assumptions: AssumptionSet = defaultAssumptions
): PortfolioAnalysis {
  const portfolioValue = calculatePortfolioValue(portfolio.holdings, instruments) + portfolio.cashBalance;
  const netInvestedCapital = calculateNetInvestedCapital(portfolio.transactions);
  const { gainLoss: totalGainLoss, gainLossPercent: totalGainLossPercent } = calculateTotalGainLoss(portfolioValue, netInvestedCapital);
  const assetAllocation = calculateAssetAllocation(portfolio.holdings, instruments, portfolioValue, portfolio.cashBalance);
  const geographicExposure = calculateGeographicExposure(portfolio.holdings, instruments, portfolioValue, portfolio.cashBalance);
  const currencyExposure = calculateCurrencyExposure(portfolio.holdings, instruments, portfolioValue, portfolio.cashBalance);
  const sectorExposure = calculateSectorExposure(portfolio.holdings, instruments, portfolioValue);
  const themeExposure = calculateThemeExposure(portfolio.holdings, instruments, portfolioValue);
  const topHoldings = calculateTopHoldings(portfolio.holdings, instruments, portfolioValue, portfolio.cashBalance);
  const hhi = calculateHHI(topHoldings.map((row) => row.weight));
  const weightedExpenseRatio = calculateWeightedExpenseRatio(portfolio.holdings, instruments, portfolioValue);
  const estimatedAnnualFees = calculateEstimatedAnnualFees(portfolioValue, weightedExpenseRatio, assumptions.platformFeeRate, assumptions.fxFeeRate, assumptions.taxDragRate);
  const currentTargetRows = calculateAllocationDrift(assetAllocation, portfolio.targetAllocation, portfolioValue);
  const allocationDrift = currentTargetRows.reduce((sum, row) => sum + Math.abs(row.drift), 0) / 2;
  const dataFreshnessScore = calculateDataFreshnessScore(instruments);
  const dataQualityIssues = buildDataQualityIssues(assetAllocation, instruments, portfolio.holdings);

  return {
    portfolioValue,
    netInvestedCapital,
    totalGainLoss,
    totalGainLossPercent,
    weightedExpenseRatio,
    estimatedAnnualFees,
    hhi,
    top5Concentration: topHoldings.slice(0, 5).reduce((sum, row) => sum + row.weight, 0),
    diversificationScore: Math.max(0, Math.min(100, Math.round((1 - hhi) * 112))),
    assetAllocation,
    geographicExposure,
    currencyExposure,
    sectorExposure,
    themeExposure,
    topHoldings,
    allocationDrift,
    currentTargetRows,
    dataFreshnessScore,
    dataQualityIssues,
    healthSummary: generatePortfolioHealthSummary({
      portfolioValue,
      top5Concentration: topHoldings.slice(0, 5).reduce((sum, row) => sum + row.weight, 0),
      allocationDrift,
      annualFees: estimatedAnnualFees,
      weightedExpenseRatio,
      largestAssetClass: assetAllocation[0]?.label ?? "unknown",
      largestAssetClassWeight: assetAllocation[0]?.weight ?? 0
    })
  };

}

export function calculatePortfolioValue(holdings: Holding[], instruments: Instrument[]): number {
  return holdings.reduce((sum, item) => sum + holdingMarketValue(item, instruments), 0);
}

export function calculateNetInvestedCapital(transactions: Transaction[]): number {
  const externalFlows = transactions.filter((item) => item.type === "DEPOSIT" || item.type === "WITHDRAWAL");
  if (externalFlows.length > 0) {
    return externalFlows.reduce((sum, item) => {
      if (item.type === "DEPOSIT") return sum + Math.abs(item.amount);
      return sum - Math.abs(item.amount);
    }, 0);
  }

  return transactions.reduce((sum, item) => {
    if (item.type === "BUY") return sum + Math.abs(item.amount);
    if (item.type === "SELL") return sum - Math.abs(item.amount);
    if (item.type === "FEE") return sum + Math.abs(item.amount);
    return sum;
  }, 0);
}

export function calculateTotalGainLoss(portfolioValue: number, netInvestedCapital: number) {
  const gainLoss = portfolioValue - netInvestedCapital;
  return {
    gainLoss,
    gainLossPercent: netInvestedCapital > 0 ? gainLoss / netInvestedCapital : 0
  };
}

export function calculateAssetAllocation(
  holdings: Holding[],
  instruments: Instrument[],
  totalValue: number,
  cashBalance = 0
): ExposureRow[] {
  const rows = calculateExposure(holdings, instruments, totalValue, "assetClass", "asset_allocation", cashBalance);
  if (cashBalance > 0) {
    const cashRow = rows.find((row) => row.key === "Cash & Cash Equivalents");
    if (cashRow) {
      cashRow.value += cashBalance;
      cashRow.weight = totalValue > 0 ? cashRow.value / totalValue : 0;
      cashRow.topHoldings = [...cashRow.topHoldings, "Cash"].slice(0, 4);
      cashRow.quality = mergeQuality(cashRow.quality, "USER_PROVIDED");
    } else {
      rows.push({
        key: "Cash & Cash Equivalents",
        label: "Cash & Cash Equivalents",
        value: cashBalance,
        weight: totalValue > 0 ? cashBalance / totalValue : 0,
        topHoldings: ["Cash"],
        quality: "USER_PROVIDED"
      });
    }
  }
  return rows.sort((left, right) => right.value - left.value);
}

export function calculateExposure(
  holdings: Holding[],
  instruments: Instrument[],
  totalValue: number,
  key: keyof Pick<Instrument, "assetClass" | "country" | "currency" | "sector">,
  metricKey: string,
  cashBalance = 0
): ExposureRow[] {
  const buckets = new Map<string, { value: number; top: string[]; quality: QualityLevel }>();
  for (const item of holdings) {
    const instrument = findInstrument(item.instrumentId, instruments);
    const bucketKey = instrument?.[key] ?? "Unknown";
    const value = holdingMarketValue(item, instruments);
    const previous = buckets.get(bucketKey) ?? { value: 0, top: [], quality: "COMPLETE" as QualityLevel };
    previous.value += value;
    previous.top.push(instrument?.symbol ?? item.instrumentId);
    previous.quality = mergeQuality(previous.quality, instrument?.priceQuality ?? "UNAVAILABLE");
    buckets.set(bucketKey, previous);
  }
  if ((key === "currency" || key === "country") && cashBalance > 0) {
    const bucketKey = key === "currency" ? "USD" : "Cash";
    const previous = buckets.get(bucketKey) ?? { value: 0, top: [], quality: "USER_PROVIDED" as QualityLevel };
    previous.value += cashBalance;
    previous.top.push("Cash");
    buckets.set(bucketKey, previous);
  }
  return [...buckets.entries()]
    .map(([bucketKey, row]) => ({
      key: bucketKey,
      label: bucketKey,
      value: row.value,
      weight: totalValue > 0 ? row.value / totalValue : 0,
      topHoldings: row.top.slice(0, 4),
      quality: row.quality
    }))
    .sort((left, right) => right.value - left.value);
}

export function calculateGeographicExposure(holdings: Holding[], instruments: Instrument[], totalValue: number, cashBalance = 0): ExposureRow[] {
  return calculateExposure(holdings, instruments, totalValue, "country", "geographic_exposure", cashBalance);
}

export function calculateCurrencyExposure(holdings: Holding[], instruments: Instrument[], totalValue: number, cashBalance = 0): ExposureRow[] {
  return calculateExposure(holdings, instruments, totalValue, "currency", "currency_exposure", cashBalance);
}

export function calculateSectorExposure(holdings: Holding[], instruments: Instrument[], totalValue: number): ExposureRow[] {
  return calculateExposure(holdings, instruments, totalValue, "sector", "sector_exposure");
}

export function calculateThemeExposure(holdings: Holding[], instruments: Instrument[], totalValue: number): ExposureRow[] {
  const buckets = new Map<string, { value: number; top: string[] }>();
  for (const item of holdings) {
    const instrument = findInstrument(item.instrumentId, instruments);
    const themes = instrument?.theme.length ? instrument.theme : ["Unclassified"];
    const value = holdingMarketValue(item, instruments) / themes.length;
    for (const theme of themes) {
      const previous = buckets.get(theme) ?? { value: 0, top: [] };
      previous.value += value;
      previous.top.push(instrument?.symbol ?? item.instrumentId);
      buckets.set(theme, previous);
    }
  }
  return [...buckets.entries()]
    .map(([key, row]) => ({
      key,
      label: key,
      value: row.value,
      weight: totalValue > 0 ? row.value / totalValue : 0,
      topHoldings: [...new Set(row.top)].slice(0, 4),
      quality: (key === "Unclassified" ? "PARTIAL" : "ESTIMATED") as QualityLevel
    }))
    .sort((left, right) => right.value - left.value);
}

export function calculateFundOverlap(holdings: Holding[], instruments: Instrument[]): FundOverlapRow[] {
  const fundHoldings = holdings
    .map((holdingItem) => ({
      holding: holdingItem,
      instrument: findInstrument(holdingItem.instrumentId, instruments)
    }))
    .filter((row) => row.instrument?.fundFlag && row.instrument.lookThroughHoldings?.length);
  const rows: FundOverlapRow[] = [];

  for (let leftIndex = 0; leftIndex < fundHoldings.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < fundHoldings.length; rightIndex += 1) {
      const left = fundHoldings[leftIndex].instrument;
      const right = fundHoldings[rightIndex].instrument;
      if (!left || !right) continue;

      const rightWeights = new Map((right.lookThroughHoldings ?? []).map((item) => [item.symbol.toUpperCase(), normalizeWeight(item.weight)]));
      const sharedHoldings = (left.lookThroughHoldings ?? [])
        .map((item) => {
          const symbol = item.symbol.toUpperCase();
          const rightWeight = rightWeights.get(symbol) ?? 0;
          const weight = Math.min(normalizeWeight(item.weight), rightWeight);
          return { symbol, weight };
        })
        .filter((item) => item.weight > 0)
        .sort((leftItem, rightItem) => rightItem.weight - leftItem.weight);

      if (sharedHoldings.length > 0) {
        rows.push({
          pairKey: `${left.symbol}:${right.symbol}`,
          leftSymbol: left.symbol,
          rightSymbol: right.symbol,
          overlapWeight: sharedHoldings.reduce((sum, item) => sum + item.weight, 0),
          sharedHoldings,
          quality: mergeQuality(left.priceQuality, right.priceQuality)
        });
      }
    }
  }

  return rows.sort((left, right) => right.overlapWeight - left.overlapWeight);
}

export function calculateTopHoldings(
  holdings: Holding[],
  instruments: Instrument[],
  totalValue: number,
  cashBalance = 0
): ExposureRow[] {
  const rows = holdings.map((item) => {
    const instrument = findInstrument(item.instrumentId, instruments);
    const value = holdingMarketValue(item, instruments);
    return {
      key: instrument?.symbol ?? item.instrumentId,
      label: instrument?.name ?? item.instrumentId,
      value,
      weight: totalValue > 0 ? value / totalValue : 0,
      topHoldings: [instrument?.symbol ?? item.instrumentId],
      quality: instrument?.priceQuality ?? "UNAVAILABLE"
    } satisfies ExposureRow;
  });
  if (cashBalance > 0) {
    rows.push({
      key: "CASH",
      label: "Cash balance",
      value: cashBalance,
      weight: totalValue > 0 ? cashBalance / totalValue : 0,
      topHoldings: ["Cash"],
      quality: "USER_PROVIDED"
    });
  }
  return rows.sort((left, right) => right.value - left.value);
}

export function calculateHHI(weights: number[]): number {
  return weights.reduce((sum, weight) => sum + weight * weight, 0);
}

export function calculateWeightedExpenseRatio(holdings: Holding[], instruments: Instrument[], totalValue: number): number {
  if (totalValue <= 0) return 0;
  return holdings.reduce((sum, item) => {
    const instrument = findInstrument(item.instrumentId, instruments);
    const value = holdingMarketValue(item, instruments);
    return sum + (instrument?.expenseRatio ?? 0) * (value / totalValue);
  }, 0);
}

export function calculateEstimatedAnnualFees(
  portfolioValue: number,
  weightedExpenseRatio: number,
  platformFeeRate: number,
  fxFeeRate: number,
  taxDragRate: number
): number {
  return portfolioValue * Math.max(0, weightedExpenseRatio + platformFeeRate + fxFeeRate + taxDragRate);
}

export function calculateCAGR(beginningValue: number, endingValue: number, years: number): number | null {
  if (beginningValue <= 0 || endingValue <= 0 || years <= 0) return null;
  return Math.pow(endingValue / beginningValue, 1 / years) - 1;
}

export function calculateTimeWeightedReturn(periods: { beginningValue: number; endingValue: number; externalCashFlow: number }[]): number {
  return periods.reduce((compound, period) => {
    if (period.beginningValue <= 0) return compound;
    const subperiodReturn = (period.endingValue - period.externalCashFlow - period.beginningValue) / period.beginningValue;
    return compound * (1 + subperiodReturn);
  }, 1) - 1;
}

export function calculateMoneyWeightedReturn(cashFlows: { date: string; amount: number }[]): number | null {
  const sorted = [...cashFlows].sort((left, right) => left.date.localeCompare(right.date));
  if (sorted.length < 2 || !sorted.some((flow) => flow.amount < 0) || !sorted.some((flow) => flow.amount > 0)) {
    return null;
  }
  const firstDate = new Date(sorted[0].date).getTime();
  if (!Number.isFinite(firstDate)) return null;
  const npv = (rate: number) =>
    sorted.reduce((sum, flow) => {
      const flowDate = new Date(flow.date).getTime();
      if (!Number.isFinite(flowDate) || rate <= -1) return Number.NaN;
      const years = (flowDate - firstDate) / (MS_PER_DAY * 365.25);
      return sum + flow.amount / Math.pow(1 + rate, years);
    }, 0);
  let low = -0.999999;
  let high = 1;
  let lowValue = npv(low);
  let highValue = npv(high);
  for (let expansion = 0; expansion < 32 && Number.isFinite(lowValue) && Number.isFinite(highValue) && Math.sign(lowValue) === Math.sign(highValue); expansion += 1) {
    high = high * 2 + 1;
    highValue = npv(high);
  }
  if (!Number.isFinite(lowValue) || !Number.isFinite(highValue) || Math.sign(lowValue) === Math.sign(highValue)) return null;
  for (let index = 0; index < 120; index += 1) {
    const mid = (low + high) / 2;
    const value = npv(mid);
    if (!Number.isFinite(value)) return null;
    if (Math.abs(value) < 1e-7) return mid;
    if (Math.sign(value) === Math.sign(lowValue)) {
      low = mid;
      lowValue = value;
    } else {
      high = mid;
      highValue = value;
    }
  }
  return (low + high) / 2;
}

export function calculateVolatility(returns: number[], periodsPerYear = TRADING_DAYS_PER_YEAR): number {
  return standardDeviation(returns, true) * Math.sqrt(periodsPerYear);
}

export function calculateMaxDrawdownFromReturns(returns: number[]): number {
  let equity = 1;
  let peak = 1;
  let worst = 0;
  for (const value of returns) {
    equity *= 1 + value;
    peak = Math.max(peak, equity);
    worst = Math.min(worst, equity / peak - 1);
  }
  return worst;
}

export function calculateMaxDrawdown(returns: number[]): number {
  return calculateMaxDrawdownFromReturns(returns);
}

export function calculateWorstRollingReturn(returns: number[], windowSize: number): number | null {
  if (windowSize <= 0 || returns.length < windowSize) return null;
  let worst = Infinity;
  for (let index = 0; index <= returns.length - windowSize; index += 1) {
    const value = cumulativeReturn(returns.slice(index, index + windowSize));
    worst = Math.min(worst, value);
  }
  return Number.isFinite(worst) ? worst : null;
}

export function calculateSharpe(annualizedReturn: number, annualizedVolatility: number, riskFreeRate: number): number | null {
  return annualizedVolatility > 0 ? (annualizedReturn - riskFreeRate) / annualizedVolatility : null;
}

export function calculateSortino(
  annualizedReturn: number,
  periodicReturns: number[],
  targetReturn: number,
  periodsPerYear = MONTHS_PER_YEAR
): number | null {
  if (!periodicReturns.length || periodsPerYear <= 0) return null;
  const targetPerPeriod = Math.pow(1 + targetReturn, 1 / periodsPerYear) - 1;
  const downside = periodicReturns.map((value) => Math.min(0, value - targetPerPeriod));
  const downsideDeviation = Math.sqrt(mean(downside.map((value) => value * value))) * Math.sqrt(periodsPerYear);
  return downsideDeviation > 0 ? (annualizedReturn - targetReturn) / downsideDeviation : null;
}

export function calculateBeta(portfolioReturns: number[], benchmarkReturns: number[]): number | null {
  const length = Math.min(portfolioReturns.length, benchmarkReturns.length);
  if (length < 2) return null;
  const portfolio = portfolioReturns.slice(0, length);
  const benchmark = benchmarkReturns.slice(0, length);
  const benchmarkVariance = variance(benchmark, true);
  return benchmarkVariance > 0 ? covariance(portfolio, benchmark, true) / benchmarkVariance : null;
}

export function calculateTrackingError(portfolioReturns: number[], benchmarkReturns: number[], periodsPerYear = MONTHS_PER_YEAR): number {
  const length = Math.min(portfolioReturns.length, benchmarkReturns.length);
  const activeReturns = portfolioReturns.slice(0, length).map((value, index) => value - benchmarkReturns[index]);
  return standardDeviation(activeReturns, true) * Math.sqrt(periodsPerYear);
}

export function calculateAllocationDrift(current: ExposureRow[], targetAllocation: Record<string, number>, portfolioValue: number): AllocationDriftRow[] {
  const currentMap = new Map(current.map((row) => [row.key, row.weight]));
  const keys = [...new Set([...currentMap.keys(), ...Object.keys(targetAllocation)])];
  return keys
    .map((key) => {
      const currentWeight = currentMap.get(key) ?? 0;
      const targetWeight = targetAllocation[key] ?? 0;
      return {
        key,
        currentWeight,
        targetWeight,
        drift: currentWeight - targetWeight,
        dollarsToTarget: (targetWeight - currentWeight) * portfolioValue
      };
    })
    .sort((left, right) => Math.abs(right.drift) - Math.abs(left.drift));
}

export function runBacktest(params: {
  portfolio: Portfolio;
  instruments: Instrument[];
  assumptions?: AssumptionSet;
  startDate?: string;
  years?: number;
  initialAmount?: number;
  monthlyContribution?: number;
  rebalanceFrequencyMonths?: number;
}): BacktestResult {
  const assumptions = params.assumptions ?? defaultAssumptions;
  const analysis = analyzePortfolio(params.portfolio, params.instruments, assumptions);
  const years = Math.max(1, params.years ?? 10);
  const monthCount = years * MONTHS_PER_YEAR;
  const initialAmount = params.initialAmount ?? Math.max(1, analysis.netInvestedCapital || analysis.portfolioValue);
  const monthlyContribution = params.monthlyContribution ?? params.portfolio.goal.monthlyContribution;
  const rebalanceFrequency = Math.max(1, params.rebalanceFrequencyMonths ?? 12);
  let value = initialAmount;
  let benchmarkValue = initialAmount;
  const monthlyReturns: number[] = [];
  const benchmarkReturns: number[] = [];
  const equityCurve: BacktestResult["equityCurve"] = [];
  const start = new Date(params.startDate ?? "2016-01-31");
  const weightedAnnualReturn = analysis.assetAllocation.reduce(
    (sum, row) => sum + row.weight * (assumptions.expectedReturnByAssetClass[row.key] ?? 0.05),
    0
  );
  const weightedAnnualVol = Math.sqrt(
    analysis.assetAllocation.reduce(
      (sum, row) => sum + row.weight * row.weight * (assumptions.volatilityByAssetClass[row.key] ?? 0.15) ** 2,
      0
    )
  );
  for (let month = 1; month <= monthCount; month += 1) {
    const seasonalShock = Math.sin(month * 1.7) * weightedAnnualVol / Math.sqrt(12) * 0.38;
    const stressShock = month % 37 === 0 ? -weightedAnnualVol * 0.22 : 0;
    const monthlyReturn = weightedAnnualReturn / 12 + seasonalShock + stressShock;
    const benchmarkReturn = 0.07 / 12 + Math.sin(month * 1.45) * 0.18 / Math.sqrt(12) * 0.35 + (month % 41 === 0 ? -0.04 : 0);
    monthlyReturns.push(monthlyReturn);
    benchmarkReturns.push(benchmarkReturn);
    value = value * (1 + monthlyReturn) + monthlyContribution;
    benchmarkValue = benchmarkValue * (1 + benchmarkReturn) + monthlyContribution;
    const date = new Date(start);
    date.setMonth(start.getMonth() + month);
    equityCurve.push({ date: date.toISOString().slice(0, 10), value, benchmarkValue });
    if (month % rebalanceFrequency === 0) {
      value *= 0.9995;
    }
  }
  const annualizedReturn = calculateCAGR(initialAmount, value, years) ?? 0;
  const benchmarkAnnualizedReturn = calculateCAGR(initialAmount, benchmarkValue, years) ?? 0;
  const annualizedReturns = chunk(monthlyReturns, 12).map(cumulativeReturn);
  const drawdowns = drawdownSeries(equityCurve);
  return {
    endingValue: value,
    cagr: annualizedReturn,
    annualizedVolatility: calculateVolatility(monthlyReturns, MONTHS_PER_YEAR),
    maxDrawdown: Math.min(...drawdowns.map((row) => row.value), 0),
    bestYear: Math.max(...annualizedReturns, 0),
    worstYear: Math.min(...annualizedReturns, 0),
    rolling12MonthReturns: rollingReturns(monthlyReturns, 12),
    rolling36MonthReturns: rollingReturns(monthlyReturns, 36),
    sharpe: calculateSharpe(annualizedReturn, calculateVolatility(monthlyReturns, MONTHS_PER_YEAR), assumptions.riskFreeRate),
    sortino: calculateSortino(annualizedReturn, monthlyReturns, assumptions.downsideTargetRate, MONTHS_PER_YEAR),
    benchmarkRelativeReturn: annualizedReturn - benchmarkAnnualizedReturn,
    trackingError: calculateTrackingError(monthlyReturns, benchmarkReturns),
    equityCurve,
    drawdowns,
    dataQualityIssues: [
      {
        issueId: "backtest-proxy",
        metricKey: "backtest",
        severity: "warning",
        qualityLevel: "PROXY",
        reason: "Prototype backtest uses a synthetic monthly planning proxy where exact historical price series are unavailable."
      }
    ]
  };
}

export function runMonteCarlo(params: {
  portfolio: Portfolio;
  instruments: Instrument[];
  assumptions?: AssumptionSet;
  pathCount?: number;
  method?: "normal" | "bootstrap" | "fat_tail";
  seed?: number;
}): MonteCarloResult {
  const assumptions = params.assumptions ?? defaultAssumptions;
  const analysis = analyzePortfolio(params.portfolio, params.instruments, assumptions);
  const goal = params.portfolio.goal;
  const months = Math.max(1, monthsBetween(new Date(), new Date(goal.targetDate)));
  const pathCount = Math.min(Math.max(100, params.pathCount ?? 5000), 10_000);
  const rng = mulberry32(params.seed ?? 42);
  const weightedAnnualReturn = analysis.assetAllocation.reduce(
    (sum, row) => sum + row.weight * (assumptions.expectedReturnByAssetClass[row.key] ?? 0.05),
    0
  );
  const weightedAnnualVolatility = Math.sqrt(
    analysis.assetAllocation.reduce(
      (sum, row) => sum + row.weight * row.weight * (assumptions.volatilityByAssetClass[row.key] ?? 0.15) ** 2,
      0
    )
  );
  const terminalValues: number[] = [];
  const badDrawdowns: number[] = [];
  const checkpoints = new Map<number, number[]>();
  for (let path = 0; path < pathCount; path += 1) {
    let value = analysis.portfolioValue;
    let peak = value;
    let worstDrawdown = 0;
    for (let month = 1; month <= months; month += 1) {
      const shock = randomNormal(rng);
      const tailMultiplier = params.method === "fat_tail" && rng() < 0.05 ? 2.8 : 1;
      const monthlyReturn = weightedAnnualReturn / 12 + shock * (weightedAnnualVolatility / Math.sqrt(12)) * tailMultiplier;
      value = value * (1 + monthlyReturn) + goal.monthlyContribution;
      peak = Math.max(peak, value);
      worstDrawdown = Math.min(worstDrawdown, value / peak - 1);
      if (month % 12 === 0 || month === months) {
        const bucket = checkpoints.get(month) ?? [];
        bucket.push(value);
        checkpoints.set(month, bucket);
      }
    }
    terminalValues.push(value);
    badDrawdowns.push(worstDrawdown);
  }
  terminalValues.sort((left, right) => left - right);
  const successCount = terminalValues.filter((value) => value >= goal.targetAmount).length;
  const shortfalls = terminalValues.filter((value) => value < goal.targetAmount).map((value) => goal.targetAmount - value);
  return {
    successProbability: successCount / pathCount,
    medianOutcome: percentile(terminalValues, 0.5),
    p10Outcome: percentile(terminalValues, 0.1),
    p90Outcome: percentile(terminalValues, 0.9),
    p5Outcome: percentile(terminalValues, 0.05),
    p95Outcome: percentile(terminalValues, 0.95),
    shortfallProbability: shortfalls.length / pathCount,
    medianShortfallAmount: shortfalls.length ? percentile(shortfalls, 0.5) : 0,
    requiredMonthlyContribution: calculateRequiredMonthlyContribution(goal.targetAmount, months, analysis.portfolioValue, weightedAnnualReturn),
    estimatedBadCaseDrawdown: percentile(badDrawdowns.sort((left, right) => left - right), 0.1),
    pathCount,
    method: params.method ?? "normal",
    fanChart: [...checkpoints.entries()].map(([month, values]) => {
      const sorted = values.sort((left, right) => left - right);
      return { month, p10: percentile(sorted, 0.1), median: percentile(sorted, 0.5), p90: percentile(sorted, 0.9) };
    }),
    dataQualityIssues: [
      {
        issueId: "monte-carlo-assumptions",
        metricKey: "monte_carlo",
        severity: "warning",
        qualityLevel: "ESTIMATED",
        reason: "Simulation depends on return, volatility, and contribution assumptions. It is not a prediction."
      }
    ]
  };
}

export function calculateRequiredMonthlyContribution(targetAmount: number, months: number, currentValue: number, annualReturn: number) {
  if (months <= 0) return 0;
  const monthlyReturn = annualReturn / 12;
  const futureCurrent = currentValue * Math.pow(1 + monthlyReturn, months);
  const gap = targetAmount - futureCurrent;
  if (gap <= 0) return 0;
  if (Math.abs(monthlyReturn) < 1e-9) return gap / months;
  return gap * monthlyReturn / (Math.pow(1 + monthlyReturn, months) - 1);
}

export function calculateDataFreshnessScore(instruments: Instrument[], asOf = new Date(), staleAfterDays = 2): number {
  if (instruments.length === 0) return 0;
  const scores = instruments.map((instrumentItem) => {
    const priceDate = new Date(instrumentItem.priceAsOf);
    if (!Number.isFinite(priceDate.getTime()) || instrumentItem.priceQuality === "UNAVAILABLE") return 0;
    if (instrumentItem.priceQuality === "USER_PROVIDED") return 0.75;
    const ageDays = Math.max(0, (asOf.getTime() - priceDate.getTime()) / MS_PER_DAY);
    const freshness = Math.max(0, 1 - ageDays / Math.max(1, staleAfterDays));
    const qualityMultiplier = instrumentItem.priceQuality === "COMPLETE" ? 1 : instrumentItem.priceQuality === "PROXY" ? 0.7 : 0.55;
    return freshness * qualityMultiplier;
  });
  return Math.max(0, Math.min(1, mean(scores)));
}

export function generateContributionRebalancePlan(
  analysis: PortfolioAnalysis,
  targetAllocation: Record<string, number>,
  monthlyContribution: number,
  assumptions: AssumptionSet = defaultAssumptions
): RebalancePlan {
  const currentWeight = Object.fromEntries(analysis.assetAllocation.map((row) => [row.key, row.weight]));
  const driftRows = calculateAllocationDrift(analysis.assetAllocation, targetAllocation, analysis.portfolioValue);
  const underweight = driftRows.filter((row) => row.drift < -0.005).sort((left, right) => left.drift - right.drift);
  const totalUnderweight = underweight.reduce((sum, row) => sum + Math.abs(row.drift), 0);
  const cashContributionPlan = underweight.map((row) => ({
    assetClass: row.key,
    amount: totalUnderweight > 0 ? monthlyContribution * (Math.abs(row.drift) / totalUnderweight) : 0,
    reason: "Direct your next contribution toward underweight assets."
  }));
  const materialOverweight = driftRows.filter((row) => row.drift > assumptions.rebalanceBand);
  const optionalSellTrades = materialOverweight.map((row) => ({ assetClass: row.key, amount: row.dollarsToTarget * -1 }));
  const estimatedFees = optionalSellTrades.reduce((sum, row) => sum + Math.abs(row.amount) * 0.001, 0);
  const estimatedTaxableGain = optionalSellTrades.reduce((sum, row) => sum + Math.abs(row.amount) * assumptions.taxDragRate, 0);
  return {
    currentWeight,
    targetWeight: targetAllocation,
    drift: Object.fromEntries(driftRows.map((row) => [row.key, row.drift])),
    cashContributionPlan,
    estimatedMonthsToTarget:
      monthlyContribution > 0
        ? Math.ceil(
            driftRows.reduce((sum, row) => sum + Math.max(0, row.dollarsToTarget), 0) /
              monthlyContribution
          )
        : Infinity,
    optionalSellTrades,
    optionalBuyTrades: underweight.map((row) => ({ assetClass: row.key, amount: Math.max(0, row.dollarsToTarget) })),
    estimatedFees,
    estimatedTaxableGain,
    postRebalanceWeights: targetAllocation,
    warnings: [
      "You can reduce most drift with future contributions. Selling is optional unless you want to rebalance faster.",
      "Tax estimates are approximate and depend on your country, account type, and personal circumstances. This is not tax advice."
    ],
    dataQualityIssues: analysis.dataQualityIssues
  };
}

export function estimateTaxLotImpact(
  taxLots: TaxLot[],
  instruments: Instrument[],
  instrumentId: string,
  sellQuantity: number,
  method: TaxLotImpact["method"] = "FIFO"
): TaxLotImpact {
  const instrument = findInstrument(instrumentId, instruments);
  const currentPrice = instrument?.currentPrice ?? 0;
  const orderedLots = taxLots
    .filter((lot) => lot.instrumentId === instrumentId && lot.quantityRemaining > 0)
    .sort((left, right) => {
      if (method === "FIFO") return left.purchaseDate.localeCompare(right.purchaseDate);
      if (method === "HIGHEST_COST_FIRST") return right.costBasisPerUnit - left.costBasisPerUnit;
      return (currentPrice - left.costBasisPerUnit) - (currentPrice - right.costBasisPerUnit);
    });
  let remaining = Math.max(0, sellQuantity);
  const lotsUsed: TaxLotImpact["lotsUsed"] = [];
  for (const lot of orderedLots) {
    if (remaining <= 0) break;
    const quantity = Math.min(remaining, lot.quantityRemaining);
    const gain = (currentPrice - lot.costBasisPerUnit) * quantity - lot.fees * (quantity / lot.quantityOriginal);
    lotsUsed.push({
      lotId: lot.lotId,
      quantity,
      gain,
      holdingPeriodDays: Math.max(0, Math.round((Date.now() - new Date(lot.purchaseDate).getTime()) / MS_PER_DAY))
    });
    remaining -= quantity;
  }
  const realizedGain = lotsUsed.reduce((sum, lot) => sum + lot.gain, 0);
  return {
    method,
    sellQuantity: sellQuantity - remaining,
    realizedGain,
    estimatedFees: Math.abs(sellQuantity - remaining) * currentPrice * 0.001,
    lotsUsed,
    warning: "Estimated lot impact only. This is not tax advice and does not apply country-specific tax rules."
  };
}

export function validateHoldingsCsv(
  text: string,
  portfolioIdOrOptions: string | CsvValidationOptions = "demo-growth-income"
): { holdings: Holding[]; errors: string[] } {
  const options: CsvValidationOptions =
    typeof portfolioIdOrOptions === "string" ? { portfolioId: portfolioIdOrOptions } : portfolioIdOrOptions;
  const portfolioId = options.portfolioId ?? "demo-growth-income";
  const maxBytes = options.maxBytes ?? 1_000_000;
  const maxRows = options.maxRows ?? 500;
  const errors: string[] = [];
  if (textByteLength(text) > maxBytes) {
    errors.push(`CSV is too large. Maximum accepted size is ${Math.round(maxBytes / 1024)} KB.`);
  }
  if (options.fileName && !/\.(csv|txt)$/i.test(options.fileName)) {
    errors.push("CSV import only accepts .csv or .txt files.");
  }
  if (options.mimeType && !["text/csv", "text/plain", "application/vnd.ms-excel"].includes(options.mimeType)) {
    errors.push("CSV import only accepts text/csv or text/plain content.");
  }
  if (errors.length) return { holdings: [], errors };

  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2) return { holdings: [], errors: ["CSV needs a header row and at least one holding row."] };
  if (lines.length - 1 > maxRows) {
    return { holdings: [], errors: [`CSV has too many holding rows. Maximum accepted row count is ${maxRows}.`] };
  }
  const header = splitCsvLine(lines[0]).map((item) => item.trim().toLowerCase());
  const symbolIndex = header.indexOf("symbol");
  const quantityIndex = header.indexOf("quantity");
  const priceIndex = header.indexOf("price");
  const valueIndex = header.indexOf("market_value");
  const purchaseDateIndex = header.indexOf("purchase_date");
  const tradeDateIndex = header.indexOf("date");
  const knownSymbols = new Set((options.knownSymbols ?? []).map((symbol) => normalizeSymbol(symbol)));
  const seenRows = new Set<string>();
  if (symbolIndex < 0) errors.push("Missing required column: symbol.");
  if (quantityIndex < 0 && valueIndex < 0) errors.push("CSV needs quantity or market_value.");
  if (errors.length) return { holdings: [], errors };
  const holdings = lines.slice(1).map((line, index) => {
    const row = splitCsvLine(line);
    if (row.some((cell) => /^[=+\-@]/.test(cell.trim()))) {
      errors.push(`Row ${index + 2} contains a spreadsheet formula-like value and was rejected.`);
    }
    const symbol = row[symbolIndex]?.trim().toUpperCase();
    const normalizedSymbol = normalizeSymbol(symbol ?? "");
    const quantity = quantityIndex >= 0 ? Number(row[quantityIndex]) : 0;
    const manualPrice = priceIndex >= 0 ? Number(row[priceIndex]) : undefined;
    const manualMarketValue = valueIndex >= 0 ? Number(row[valueIndex]) : undefined;
    const dateValue = (purchaseDateIndex >= 0 ? row[purchaseDateIndex] : tradeDateIndex >= 0 ? row[tradeDateIndex] : undefined)?.trim();
    const dedupeKey = [symbol, row[quantityIndex]?.trim() ?? "", row[priceIndex]?.trim() ?? "", row[valueIndex]?.trim() ?? "", dateValue ?? ""].join("|");
    if (!symbol) errors.push(`Row ${index + 2} is missing a symbol.`);
    if (symbol && options.rejectUnknownSymbols && knownSymbols.size > 0 && !knownSymbols.has(normalizedSymbol)) {
      errors.push(`Row ${index + 2} references unknown symbol ${symbol}.`);
    }
    if (seenRows.has(dedupeKey)) {
      errors.push(`Row ${index + 2} duplicates an earlier holding row.`);
    }
    seenRows.add(dedupeKey);
    if (quantityIndex >= 0 && (!Number.isFinite(quantity) || quantity < 0)) {
      errors.push(`Row ${index + 2} has an invalid quantity.`);
    }
    if (manualPrice !== undefined && (!Number.isFinite(manualPrice) || manualPrice < 0)) {
      errors.push(`Row ${index + 2} has an invalid price.`);
    }
    if (manualMarketValue !== undefined && (!Number.isFinite(manualMarketValue) || manualMarketValue < 0)) {
      errors.push(`Row ${index + 2} has an invalid market_value.`);
    }
    if (dateValue && Number.isNaN(Date.parse(dateValue))) {
      errors.push(`Row ${index + 2} has an invalid date.`);
    }
    return {
      holdingId: `csv-${symbol}-${index}`,
      portfolioId,
      accountId: "taxable",
      instrumentId: symbol,
      quantity: Number.isFinite(quantity) ? quantity : 0,
      manualPrice: Number.isFinite(manualPrice) ? manualPrice : undefined,
      manualMarketValue: Number.isFinite(manualMarketValue) ? manualMarketValue : undefined,
      currency: "USD",
      source: "csv" as const
    };
  });
  return errors.length ? { holdings: [], errors } : { holdings, errors };
}

export function isFeatureEnabled(
  gates: FeatureGate[],
  featureKey: string,
  user: { role: "USER" | "TRUSTED_USER" | "ADMIN" | "SUPERADMIN"; paid?: boolean; entitlementKeys?: string[]; userId?: string }
): boolean {
  const gate = gates.find((item) => item.key === featureKey);
  if (!gate) return false;
  if (gate.hardDisabled && user.role !== "SUPERADMIN") return false;
  if ((user.role === "ADMIN" || user.role === "SUPERADMIN") && gate.enabledForAdmins) return true;
  if (user.entitlementKeys?.includes(featureKey)) return true;
  if (gate.enabledGlobally) return true;
  if (user.paid && gate.enabledForPaidUsers) return true;
  if (!user.paid && gate.enabledForFreeUsers) return true;
  return stableRollout(user.userId ?? "anonymous", featureKey) < gate.rolloutPercentage;
}

export function generatePortfolioHealthSummary(input: {
  portfolioValue: number;
  top5Concentration: number;
  allocationDrift: number;
  annualFees: number;
  weightedExpenseRatio: number;
  largestAssetClass: string;
  largestAssetClassWeight: number;
}): string {
  const concentration = input.top5Concentration > 0.65 ? "concentrated" : input.top5Concentration > 0.45 ? "moderately concentrated" : "broadly diversified";
  const drift = input.allocationDrift > 0.12 ? "materially off target" : input.allocationDrift > 0.05 ? "slightly off target" : "close to target";
  return `Portfolio is ${concentration} and ${drift}. Largest asset class is ${input.largestAssetClass} at ${formatPercent(input.largestAssetClassWeight)}. Estimated annual fee drag is ${formatPercent(input.weightedExpenseRatio)} plus platform, FX, and tax-drag assumptions.`;
}

function instrument(
  symbol: string,
  name: string,
  exchange: string,
  assetClass: AssetClass,
  subAssetClass: string,
  country: string,
  currency: string,
  sector: string,
  theme: string[],
  currentPrice: number,
  previousClose: number,
  expenseRatio: number,
  fundFlag = false,
  lookThroughHoldings?: { symbol: string; weight: number }[],
  options: Partial<Pick<Instrument, "aliases" | "identifiers" | "listings" | "primaryListingId" | "priceQuality" | "isActive">> = {}
): Instrument {
  const primaryListing = options.listings?.find((listing) => listing.isPrimary) ?? options.listings?.[0];
  const listingId = primaryListing?.listingId ?? `${exchange}:${symbol}`;
  return {
    instrumentId: symbol,
    symbol,
    exchange,
    name,
    instrumentType: fundFlag ? "etf" : assetClass === "Fixed Income" ? "bond" : assetClass === "Crypto / Digital Assets" ? "crypto" : "stock",
    assetClass,
    subAssetClass,
    country,
    domicileCountry: country,
    currency,
    sector,
    industry: sector,
    theme,
    expenseRatio,
    fundFlag,
    dataQualityScore: fundFlag ? 0.78 : 0.9,
    currentPrice,
    previousClose,
    priceAsOf: "2026-05-29",
    priceQuality: options.priceQuality ?? (fundFlag ? "PROXY" : "STALE"),
    aliases: options.aliases,
    identifiers: options.identifiers,
    listings: options.listings ?? [
      {
        listingId,
        symbol,
        exchange,
        country,
        currency,
        localCode: symbol,
        isPrimary: true,
        isActive: options.isActive ?? true
      }
    ],
    primaryListingId: options.primaryListingId ?? listingId,
    isActive: options.isActive,
    lookThroughHoldings
  };
}

function holding(holdingId: string, instrumentId: string, quantity: number): Holding {
  return { holdingId, portfolioId: "demo-growth-income", accountId: "taxable", instrumentId, quantity, currency: "USD", source: "sample" };
}

function txn(transactionId: string, type: Transaction["type"], instrumentId: string, date: string, quantity: number, price: number, amount: number): Transaction {
  return { transactionId, portfolioId: "demo-growth-income", accountId: "taxable", instrumentId, type, date, quantity, price, fees: type === "BUY" ? 5 : 0, amount, currency: "USD" };
}

function lot(lotId: string, instrumentId: string, purchaseDate: string, quantity: number, cost: number): TaxLot {
  const instrument = demoInstruments.find((item) => item.instrumentId === instrumentId);
  return {
    lotId,
    portfolioId: "demo-growth-income",
    accountId: "taxable",
    instrumentId,
    purchaseDate,
    quantityOriginal: quantity,
    quantityRemaining: quantity,
    costBasisPerUnit: cost,
    fees: 5,
    currency: "USD",
    currentPrice: instrument?.currentPrice ?? cost,
    source: "sample"
  };
}

function gate(key: string, displayName: string, description: string): FeatureGate {
  return {
    key,
    displayName,
    description,
    enabledGlobally: true,
    enabledForFreeUsers: true,
    enabledForPaidUsers: true,
    enabledForAdmins: true,
    rolloutPercentage: 100,
    hardDisabled: false
  };
}

function quota(resource: string, freeUserDefault: number, adminDefault: number | "bypass_user_limit"): UsageQuota {
  return { resource, freeUserDefault, adminDefault, used: Math.round(freeUserDefault * 0.22), resetsAt: "2026-06-01T00:00:00Z" };
}

function job(jobType: JobType, status: JobStatus, progressPercent: number): PortfolioJob {
  return {
    jobId: `job-${jobType.toLowerCase()}`,
    userId: "demo-user",
    portfolioId: "demo-growth-income",
    jobType,
    status,
    priority: jobType === "DATA_IMPORT" ? 20 : 100,
    idempotencyKey: `${jobType}:demo-growth-income`,
    progressPercent,
    attempts: status === "SUCCEEDED" ? 1 : 0,
    maxAttempts: 5,
    createdAt: "2026-05-30T09:00:00Z"
  };
}

function holdingMarketValue(holding: Holding, instruments: Instrument[]): number {
  if (Number.isFinite(holding.manualMarketValue)) return Math.max(0, holding.manualMarketValue ?? 0);
  const instrument = findInstrument(holding.instrumentId, instruments);
  const price = holding.manualPrice ?? instrument?.currentPrice ?? 0;
  return Math.max(0, holding.quantity * price);
}

function findInstrument(instrumentId: string, instruments: Instrument[]) {
  return resolveInstrumentReference(instrumentId, instruments);
}

function buildDataQualityIssues(assetAllocation: ExposureRow[], instruments: Instrument[], holdings: Holding[]): DataQualityIssue[] {
  const issues: DataQualityIssue[] = [];
  const proxyWeight = assetAllocation.filter((row) => row.quality === "PROXY").reduce((sum, row) => sum + row.weight, 0);
  if (proxyWeight > 0) {
    issues.push({
      issueId: "proxy-data",
      metricKey: "asset_allocation",
      severity: "warning",
      qualityLevel: "PROXY",
      reason: "Some ETF or fund-like holdings use proxy metadata instead of full look-through holdings.",
      affectedWeightPercent: proxyWeight * 100
    });
  }
  const missing = holdings.filter((holding) => !findInstrument(holding.instrumentId, instruments));
  if (missing.length > 0) {
    issues.push({
      issueId: "unknown-symbols",
      metricKey: "instrument_classification",
      severity: "critical",
      qualityLevel: "UNAVAILABLE",
      reason: `${missing.length} holdings do not have instrument metadata.`,
      affectedWeightPercent: undefined
    });
  }
  issues.push({
    issueId: "daily-delayed",
    metricKey: "data_freshness",
    severity: "info",
    qualityLevel: "STALE",
    reason: "MVP is daily-resolution and does not require real-time prices."
  });
  return issues;
}

function mergeQuality(left: QualityLevel, right: QualityLevel): QualityLevel {
  const rank: QualityLevel[] = ["COMPLETE", "USER_PROVIDED", "ESTIMATED", "PROXY", "PARTIAL", "STALE", "UNAVAILABLE"];
  return rank.indexOf(right) > rank.indexOf(left) ? right : left;
}

function drawdownSeries(equityCurve: BacktestResult["equityCurve"]) {
  let peak = 0;
  return equityCurve.map((row) => {
    peak = Math.max(peak, row.value);
    return { date: row.date, value: peak > 0 ? row.value / peak - 1 : 0 };
  });
}

function rollingReturns(returns: number[], windowSize: number) {
  const values: number[] = [];
  for (let index = 0; index <= returns.length - windowSize; index += 1) {
    values.push(cumulativeReturn(returns.slice(index, index + windowSize)));
  }
  return values;
}

function splitCsvLine(line: string) {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells;
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function variance(values: number[], sample = false) {
  if (values.length < 2) return 0;
  const average = mean(values);
  const squaredDeviations = values.map((value) => (value - average) ** 2);
  const denominator = sample ? values.length - 1 : values.length;
  return squaredDeviations.reduce((sum, value) => sum + value, 0) / denominator;
}

function standardDeviation(values: number[], sample = false) {
  return Math.sqrt(variance(values, sample));
}

function covariance(left: number[], right: number[], sample = false) {
  const length = Math.min(left.length, right.length);
  if (length < 2) return 0;
  const leftMean = mean(left.slice(0, length));
  const rightMean = mean(right.slice(0, length));
  const products = left.slice(0, length).map((value, index) => (value - leftMean) * (right[index] - rightMean));
  return products.reduce((sum, value) => sum + value, 0) / (sample ? length - 1 : length);
}

function cumulativeReturn(returns: number[]) {
  return returns.reduce((compound, value) => compound * (1 + value), 1) - 1;
}

function chunk<T>(items: T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < items.length; index += size) result.push(items.slice(index, index + size));
  return result;
}

function percentile(sortedValues: number[], p: number): number {
  if (sortedValues.length === 0) return 0;
  const clamped = Math.min(1, Math.max(0, p));
  const position = (sortedValues.length - 1) * clamped;
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  if (lowerIndex === upperIndex) return sortedValues[lowerIndex];
  const lowerValue = sortedValues[lowerIndex];
  const upperValue = sortedValues[upperIndex];
  return lowerValue + (upperValue - lowerValue) * (position - lowerIndex);
}

function normalizeWeight(value: number) {
  return value > 1 ? value / 100 : value;
}

function textByteLength(value: string) {
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(value).length;
  }
  return value.length;
}

function randomNormal(rng: () => number): number {
  const u1 = Math.max(Number.EPSILON, rng());
  const u2 = Math.max(Number.EPSILON, rng());
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function mulberry32(seed: number) {
  return function next() {
    let value = (seed += 0x6d2b79f5);
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function monthsBetween(start: Date, end: Date) {
  return Math.max(1, (end.getFullYear() - start.getFullYear()) * 12 + end.getMonth() - start.getMonth());
}

function stableRollout(userId: string, featureKey: string) {
  let hash = 0;
  const input = `${userId}:${featureKey}`;
  for (let index = 0; index < input.length; index += 1) {
    hash = (hash * 31 + input.charCodeAt(index)) % 10_000;
  }
  return hash / 100;
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}
