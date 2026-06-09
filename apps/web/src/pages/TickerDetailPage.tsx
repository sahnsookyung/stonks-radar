import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  ChevronRight,
  Copy,
  Database,
  ExternalLink,
  FileText,
  GitCompare,
  LineChart as LineChartIcon,
  ListChecks,
  Newspaper,
  PlusCircle,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  StickyNote,
  TrendingDown,
  TrendingUp
} from "lucide-react";
import type { AlternativeSignalItem, HomeSnapshotData, NewsEventListItem, NewsTickerSnapshotData, SnapshotEnvelope } from "@frw/shared-types";
import { EntityLink } from "../components/EntityLink";
import { LineChart } from "../components/LineChart";
import { NewsEventCard, SourcePill } from "../components/NewsEventCard";
import { apiGet } from "../lib/api";
import { disclosureTransactionBucket, disclosureTransactionCaveat, disclosureTransactionLabel } from "../lib/disclosureLabels";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";
import { getTrackedTicker, relatedTrackedEntities, resolveTrackedEntity, trackedTickers, type TrackedEntity, type TrackedTicker } from "../lib/trackedTickers";

interface MarketHistoryResponse {
  status: string;
  provider: string;
  source_note: string;
  cache: "hit" | "miss" | "persistent_hit" | "quota_wait" | "stale_fallback" | "license_limited";
  display_mode?: "public" | "private";
  display_status?: "display_allowed" | "stored_public_allowed" | "internal_stored" | "license_limited" | "provider_limit_reached" | "unavailable";
  data_freshness?: DataFreshness;
  provider_budget_status?: ProviderLimitSnapshot[];
  symbols: string[];
  start: string;
  end: string;
  series: MarketSeries[];
  warnings: string[];
}

interface DataFreshness {
  provider: string;
  provider_timestamp: string | null;
  fetched_at: string;
  source_observed_at?: string | null;
  market_session_date: string | null;
  complete_through?: string | null;
  hard_expires_at?: string | null;
  staleness_state?: string | null;
  calculation_eligible?: boolean;
  delayed_by_seconds?: number | null;
  exchange_timezone: string;
  delay_label: string;
  is_same_day_valid: boolean;
  is_public_display_allowed: boolean;
  staleness_reason: string;
  license_mode: string;
  source_url?: string;
}

interface ProviderLimitSnapshot {
  provider_key: string;
  endpoint_key: string;
  refresh_interval?: string;
  source_checked_at: string;
  attribution_required: boolean;
  public_display_allowed: boolean;
}

interface MarketSeries {
  symbol: string;
  points: MarketPoint[];
}

interface MarketPoint {
  date: string;
  close: number;
  volume?: number | null;
}

interface DisclosureFiling {
  id: number;
  source: "OGE" | "SEC";
  form_type: string;
  filer_name?: string | null;
  issuer_name?: string | null;
  ticker?: string | null;
  cik?: string | null;
  accession_number?: string | null;
  doc_date?: string | null;
  filed_at?: string | null;
  source_url: string;
  parse_status: string;
  transaction_count?: number | null;
}

interface DisclosureTransaction {
  id: number;
  source: "OGE" | "SEC";
  person_name?: string | null;
  owner_name?: string | null;
  issuer_name?: string | null;
  ticker?: string | null;
  asset_description?: string | null;
  transaction_type?: string | null;
  transaction_code?: string | null;
  transaction_date?: string | null;
  amount_min?: number | null;
  amount_max?: number | null;
  shares?: number | null;
  price?: number | null;
  confidence?: number | null;
  source_url: string;
  form_type: string;
}

interface FilingsResponse {
  filings: DisclosureFiling[];
  limitations?: string[];
}

interface TransactionsResponse {
  transactions: DisclosureTransaction[];
  limitations?: string[];
  min_confidence?: number | string | null;
}

interface InsidersResponse extends TransactionsResponse {
  insiders: {
    owner_name: string;
    transactions: number;
    latest_transaction_date?: string | null;
  }[];
}

type TabKey = "overview" | "chart" | "technicals" | "options" | "news" | "shorts" | "filings" | "fundamentals" | "notes";
type ChartPresetKey = "clean" | "trend" | "momentum" | "risk";

const tabs: { key: TabKey; labelEn: string; labelKo: string; icon: ReactNode }[] = [
  { key: "overview", labelEn: "Overview", labelKo: "개요", icon: <ListChecks className="h-4 w-4" /> },
  { key: "chart", labelEn: "Chart", labelKo: "차트", icon: <LineChartIcon className="h-4 w-4" /> },
  { key: "technicals", labelEn: "Technicals", labelKo: "기술 지표", icon: <BarChart3 className="h-4 w-4" /> },
  { key: "options", labelEn: "Options", labelKo: "옵션", icon: <Activity className="h-4 w-4" /> },
  { key: "news", labelEn: "News", labelKo: "뉴스", icon: <Newspaper className="h-4 w-4" /> },
  { key: "shorts", labelEn: "Shorts", labelKo: "공매도", icon: <TrendingDown className="h-4 w-4" /> },
  { key: "filings", labelEn: "Filings", labelKo: "공시", icon: <FileText className="h-4 w-4" /> },
  { key: "fundamentals", labelEn: "Fundamentals", labelKo: "펀더멘털", icon: <Database className="h-4 w-4" /> },
  { key: "notes", labelEn: "Notes", labelKo: "노트", icon: <Bell className="h-4 w-4" /> }
];

const chartPresets: Record<ChartPresetKey, { labelEn: string; labelKo: string; studies: string[]; detailEn: string; detailKo: string }> = {
  clean: {
    labelEn: "Clean",
    labelKo: "기본",
    studies: [],
    detailEn: "Price action only.",
    detailKo: "가격 흐름만 표시합니다."
  },
  trend: {
    labelEn: "Trend",
    labelKo: "추세",
    studies: ["Volume@tv-basicstudies", "STD;EMA", "STD;SMA"],
    detailEn: "Adds volume, EMA, and SMA overlays.",
    detailKo: "거래량, EMA, SMA 오버레이를 추가합니다."
  },
  momentum: {
    labelEn: "Momentum",
    labelKo: "모멘텀",
    studies: ["STD;RSI", "STD;MACD", "STD;Stochastic_RSI"],
    detailEn: "Adds RSI, MACD, and Stochastic RSI.",
    detailKo: "RSI, MACD, Stochastic RSI를 추가합니다."
  },
  risk: {
    labelEn: "Risk",
    labelKo: "위험",
    studies: ["STD;Bollinger_Bands", "STD;ATR"],
    detailEn: "Adds volatility and range studies.",
    detailKo: "변동성과 범위 지표를 추가합니다."
  }
};

const safeTradingViewSymbol = /^[A-Z0-9_:.\\/-]{1,40}$/;

function localeText(locale: "en" | "ko", en: string, ko: string) {
  return locale === "ko" ? ko : en;
}

function buildHistoryWarnings(error: unknown, warnings: string[] | undefined, locale: "en" | "ko") {
  if (error) {
    return [
      localeText(
        locale,
        "Market-data API is unavailable, so price, technical indicators, and app-computed chart snapshots are shown as pending.",
        "시장 데이터 API를 읽지 못해 가격, 기술 지표, 차트 스냅샷을 대기 상태로 표시합니다."
      )
    ];
  }
  return warnings ?? [];
}

export function TickerDetailPage() { // NOSONAR - ticker detail owns tab/query orchestration; subpanels keep rendering scoped.
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = useParams({ strict: false }) as { symbol?: string };
  const ticker = getTrackedTicker(params.symbol);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [chartPreset, setChartPreset] = useState<ChartPresetKey>("trend");
  const defaultDates = useMemo(() => tickerDateRange(), []);
  const shouldLoadFilings = activeTab === "filings" || activeTab === "overview";
  const shouldLoadNews = activeTab === "news";

  const snapshotQuery = useQuery({
    queryKey: ["snapshot", "ticker-detail", locale],
    queryFn: () => snapshotQueries.home(locale)
  });
  const historyQuery = useQuery({
    queryKey: ["market-history", ticker?.symbol, defaultDates.start, defaultDates.end],
    queryFn: () =>
      apiGet<MarketHistoryResponse>(
        `/api/public/market/history?symbols=${encodeURIComponent(ticker?.symbol ?? "")}&start=${defaultDates.start}&end=${defaultDates.end}`
      ),
    enabled: Boolean(ticker),
    retry: false
  });
  const filingsQuery = useQuery({
    queryKey: ["ticker-filings", ticker?.symbol],
    queryFn: () => apiGet<FilingsResponse>(`/api/public/filings?ticker=${encodeURIComponent(ticker?.symbol ?? "")}&limit=16`),
    enabled: Boolean(ticker) && shouldLoadFilings,
    retry: false
  });
  const transactionsQuery = useQuery({
    queryKey: ["ticker-transactions", ticker?.symbol],
    queryFn: () =>
      apiGet<TransactionsResponse>(`/api/public/transactions?ticker=${encodeURIComponent(ticker?.symbol ?? "")}&limit=24`),
    enabled: Boolean(ticker) && shouldLoadFilings,
    retry: false
  });
  const insidersQuery = useQuery({
    queryKey: ["ticker-insiders", ticker?.symbol],
    queryFn: () => apiGet<InsidersResponse>(`/api/public/entities/${encodeURIComponent(ticker?.symbol ?? "")}/insiders?limit=50`),
    enabled: Boolean(ticker) && shouldLoadFilings,
    retry: false
  });
  const tickerNewsQuery = useQuery({
    queryKey: ["snapshot", "ticker-news", ticker?.symbol, locale],
    queryFn: () => snapshotQueries.newsTicker(newsSymbolKey(ticker?.symbol ?? ""), locale),
    enabled: Boolean(ticker) && shouldLoadNews,
    retry: false
  });

  if (!ticker) {
    return <UnknownTicker symbol={params.symbol} locale={locale} />;
  }

  const snapshot = snapshotQuery.data;
  const marketSeries = historyQuery.data?.series.find((series) => series.symbol.toUpperCase() === ticker.symbol)?.points ?? [];
  const sortedPoints = normalizePoints(marketSeries);
  const indicators = computeIndicatorSet(sortedPoints);
  const sourceItems = snapshot ? collectTickerSignals(snapshot.data, ticker) : [];
  const shortItems = sourceItems.filter((item) => item.group === "shorts");
  const newsItems = sourceItems.filter((item) => item.group === "news" || item.group === "event");
  const trumpItems = sourceItems.filter((item) => item.group === "trump");
  const filings = filingsQuery.data?.filings ?? [];
  const transactions = transactionsQuery.data?.transactions ?? [];
  const insiders = insidersQuery.data?.insiders ?? [];
  const freshness = buildFreshnessMeta(historyQuery.data, historyQuery.dataUpdatedAt, indicators.latestPoint);
  const canDisplayMarketData = Boolean(
    historyQuery.data &&
      (historyQuery.data.data_freshness
        ? historyQuery.data.data_freshness.is_public_display_allowed || historyQuery.data.display_mode === "private"
        : true)
  );
  const secUrl = ticker.secCik
    ? `https://www.sec.gov/edgar/browse/?CIK=${encodeURIComponent(ticker.secCik)}`
    : `https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker.symbol)}`;
  const hasPositiveChange = Number.isFinite(indicators.changePct) && indicators.changePct >= 0;
  const quoteValue = canDisplayMarketData ? formatCurrency(indicators.latestClose, ticker.currency) : localeText(locale, "Chart only", "차트 전용");
  const quoteChange = canDisplayMarketData
    ? `${formatSigned(indicators.change, ticker.currency)} (${formatPercent(indicators.changePct)})`
    : localeText(locale, "Internal prices withheld", "내부 가격 표시 보류");
  let quoteTone = "text-muted";
  if (canDisplayMarketData) {
    quoteTone = hasPositiveChange ? "text-success" : "text-danger";
  }
  const quoteKicker = canDisplayMarketData
    ? localeText(locale, "Latest Daily Candle", "마지막 일봉")
    : localeText(locale, "Public Display Limited", "공개 표시 제한");
  const dataStatValue = canDisplayMarketData ? freshness.delayLabel : localeText(locale, "TradingView display", "TradingView 표시");
  const scoreStatValue = canDisplayMarketData ? `${indicators.score.total}/100` : localeText(locale, "withheld", "보류");
  const rsiStatValue = canDisplayMarketData ? formatFixed(indicators.rsi14, 1) : localeText(locale, "withheld", "보류");
  const historyWarnings = buildHistoryWarnings(historyQuery.error, historyQuery.data?.warnings, locale);

  return (
    <div className="relative left-1/2 right-1/2 -mx-[50vw] -my-4 min-h-screen w-screen max-w-[100vw] overflow-x-clip bg-[#071018] sm:-my-6">
      <div className="mx-auto grid max-w-[1800px] gap-3 px-3 py-3 lg:px-4">
        <section className="panel min-w-0 overflow-hidden">
          <div className="grid min-w-0 gap-3 px-2 py-2 sm:px-3 sm:py-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:px-4">
            <div className="grid min-w-0 gap-2 md:grid-cols-[minmax(220px,0.72fr)_minmax(220px,0.28fr)]">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-semibold uppercase leading-5 text-muted sm:gap-2 sm:text-xs">
                  <TrendingUp className="h-4 w-4 text-accent" />
                  <span>{isKo ? "추적 티커" : "Tracked ticker"}</span>
                  <span className="badge border-line bg-panelAlt text-muted">{ticker.exchange}</span>
                  <span className="badge border-line bg-panelAlt text-muted">{ticker.assetType}</span>
                </div>
                <div className="mt-1 flex min-w-0 flex-wrap items-end gap-x-3 gap-y-1">
                  <h1 className="truncate text-xl font-bold leading-tight sm:text-2xl md:text-3xl">{ticker.displaySymbol}</h1>
                  <span className="min-w-0 max-w-full truncate text-sm font-semibold leading-6 text-muted md:text-lg">{ticker.name}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <FreshnessPill freshness={freshness} locale={locale} />
                  <span className="badge hidden border-line bg-panelAlt text-muted sm:inline-flex">{freshness.providerLabel}</span>
                  <span className="badge hidden border-line bg-panelAlt text-muted sm:inline-flex">{indicators.latestPoint?.date ?? "date pending"}</span>
                </div>
              </div>

              <div className="rounded-md border border-line bg-panelAlt px-2.5 py-2 sm:px-3">
                <div className="text-[11px] font-semibold uppercase leading-4 text-muted">
                  {quoteKicker}
                </div>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <div className="text-xl font-bold leading-none sm:text-2xl md:text-3xl">{quoteValue}</div>
                  <div className={`text-sm font-semibold ${quoteTone}`}>{quoteChange}</div>
                </div>
              </div>
            </div>

            <div
              className="scroll-fade-x flex min-w-0 items-center justify-start gap-2 overflow-x-auto lg:justify-end"
              data-allow-horizontal-scroll
              aria-label={isKo ? "티커 작업" : "Ticker actions"}
            >
              <HeaderAction disabled label={isKo ? "관심" : "Watch"} icon={<PlusCircle className="h-4 w-4" />} />
              <HeaderAction disabled label={isKo ? "알림" : "Alert"} icon={<Bell className="h-4 w-4" />} />
              <HeaderAction disabled label={isKo ? "노트" : "Note"} icon={<StickyNote className="h-4 w-4" />} />
              <a className="secondary-action h-11 min-h-11 shrink-0 px-2.5 py-2 sm:px-3" href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ticker.tradingViewSymbol)}`} target="_blank" rel="noreferrer" aria-label="TradingView">
                <ExternalLink className="h-4 w-4" />
                <span className="hidden sm:inline">TradingView</span>
              </a>
              <a className="secondary-action h-11 min-h-11 shrink-0 px-2.5 py-2 sm:px-3" href={secUrl} target="_blank" rel="noreferrer" aria-label="SEC filings">
                <FileText className="h-4 w-4" />
                SEC
              </a>
              <button type="button" className="secondary-action h-11 min-h-11 shrink-0 px-2.5 py-2 sm:px-3" onClick={() => void historyQuery.refetch()} aria-label={isKo ? "갱신" : "Refresh"}>
                <RefreshCw className="h-4 w-4" />
                <span className="hidden sm:inline">{isKo ? "갱신" : "Refresh"}</span>
              </button>
              <HeaderAction disabled label={isKo ? "비교" : "Compare"} icon={<GitCompare className="h-4 w-4" />} />
              <button
                type="button"
                className="secondary-action h-11 min-h-11 shrink-0 px-2.5 py-2 sm:px-3"
                onClick={() => void navigator.clipboard?.writeText(globalThis.window.location.href)}
                aria-label={isKo ? "공유" : "Share"}
              >
                <Copy className="h-4 w-4" />
                <span className="hidden sm:inline">{isKo ? "공유" : "Share"}</span>
              </button>
            </div>
          </div>

          <div className="grid border-t border-line bg-panel/80 lg:grid-cols-[minmax(0,1fr)_auto]">
            <div
              className="scroll-fade-x flex min-w-0 gap-1 overflow-x-auto px-2 py-2"
              role="tablist"
              aria-label={isKo ? "티커 상세 탭" : "Ticker detail tabs"}
              data-allow-horizontal-scroll
            >
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  className={`focus-ring inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md px-3 text-sm font-semibold ${
                    activeTab === tab.key ? "bg-accentSoft text-accent" : "text-muted hover:bg-panelAlt hover:text-ink"
                  }`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  {tab.icon}
                  {isKo ? tab.labelKo : tab.labelEn}
                </button>
              ))}
            </div>
            <div
              className="scroll-fade-x flex min-w-0 gap-2 overflow-x-auto border-t border-line px-2 py-2 lg:border-l lg:border-t-0"
              data-allow-horizontal-scroll
              aria-label={isKo ? "티커 미니 통계" : "Ticker mini stats"}
            >
              <MiniStat label={isKo ? "상태" : "Data"} value={dataStatValue} />
              <MiniStat label={isKo ? "기술" : "Score"} value={scoreStatValue} />
              <MiniStat label="RSI" value={rsiStatValue} />
              <MiniStat label={isKo ? "생성" : "Generated"} value={snapshot?.generated_at ? formatDateTime(snapshot.generated_at) : "pending"} className="hidden sm:block" />
            </div>
          </div>
        </section>

        <section className="grid min-w-0 gap-3 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="grid min-w-0 content-start gap-3">
          {activeTab === "overview" ? (
            <OverviewPanel
              ticker={ticker}
              indicators={indicators}
              shortItems={shortItems}
              newsItems={newsItems}
              filings={filings}
              transactions={transactions}
              canDisplayMarketData={canDisplayMarketData}
              locale={locale}
            />
          ) : null}
          {activeTab === "chart" ? (
            <>
              <TradingViewWidget ticker={ticker} preset={chartPreset} locale={locale} />
              <ChartPanel
                ticker={ticker}
                preset={chartPreset}
                onPresetChange={setChartPreset}
                points={sortedPoints}
                freshness={freshness}
                canDisplayMarketData={canDisplayMarketData}
                locale={locale}
              />
            </>
          ) : null}
          {activeTab === "technicals" ? <TechnicalsPanel indicators={indicators} ticker={ticker} freshness={freshness} canDisplayMarketData={canDisplayMarketData} locale={locale} /> : null}
          {activeTab === "options" ? <OptionsPanel ticker={ticker} locale={locale} /> : null}
          {activeTab === "news" ? (
            <NewsPanel
              ticker={ticker}
              tickerNews={tickerNewsQuery.data?.data}
              newsLoading={tickerNewsQuery.isLoading}
              newsError={tickerNewsQuery.error}
              trumpItems={trumpItems}
              locale={locale}
            />
          ) : null}
          {activeTab === "shorts" ? <ShortsPanel ticker={ticker} shortItems={shortItems} locale={locale} /> : null}
          {activeTab === "filings" ? (
            <FilingsPanel
              ticker={ticker}
              filings={filings}
              transactions={transactions}
              insiders={insiders}
              filingsError={filingsQuery.error}
              transactionsError={transactionsQuery.error}
              locale={locale}
            />
          ) : null}
          {activeTab === "fundamentals" ? <FundamentalsPanel ticker={ticker} locale={locale} /> : null}
          {activeTab === "notes" ? <NotesPanel ticker={ticker} locale={locale} /> : null}
        </div>

        <ResearchSidebar
          ticker={ticker}
          snapshot={snapshot}
          indicators={indicators}
          transactions={transactions}
          freshness={freshness}
          canDisplayMarketData={canDisplayMarketData}
          locale={locale}
        />
      </section>

      {historyWarnings.length ? (
        <section className="signal-warning p-4 text-sm leading-6">
          {historyWarnings.map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </section>
      ) : null}
      </div>
    </div>
  );
}

function UnknownTicker({ symbol, locale }: Readonly<{ symbol?: string; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  const entity = resolveTrackedEntity(symbol);
  const unknownMessage =
    entity?.routeKind === "reference_entity"
      ? localeText(locale, "This tracked item is a reference entity, not a tradable ticker.", "이 항목은 거래 티커가 아니라 참고 엔티티입니다.")
      : localeText(locale, "The detail page is intentionally limited to approved tracked tickers.", "현재 상세 페이지는 승인된 추적 티커만 엽니다.");
  const referenceLinkLabel = localeText(locale, "Open reference entity page", "참고 엔티티 페이지 열기");
  return (
    <div className="grid gap-5">
      <section className="panel p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-warning">
          <AlertTriangle className="h-4 w-4" />
          {isKo ? "추적하지 않는 티커" : "Ticker Not Tracked"}
        </div>
        <h1 className="mt-3 text-3xl font-bold">{symbol || "unknown"}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
          {unknownMessage}
        </p>
        {entity?.routeKind === "reference_entity" && (
          <EntityLink value={entity} locale={locale} className="primary-action mt-4">
            {referenceLinkLabel}
          </EntityLink>
        )}
      </section>
      <TickerStrip activeSymbol="" locale={locale} />
    </div>
  );
}

function TickerStrip({ activeSymbol, locale }: Readonly<{ activeSymbol: string; locale: "en" | "ko" }>) {
  return (
    <nav className="panel min-w-0 overflow-hidden p-2" aria-label={locale === "ko" ? "추적 티커" : "Tracked tickers"}>
      <div
        className="scroll-fade-x flex gap-2 overflow-x-auto"
        data-allow-horizontal-scroll
        aria-label={locale === "ko" ? "추적 티커 목록" : "Tracked ticker list"}
      >
        {trackedTickers.map((ticker) => (
          <Link
            key={ticker.symbol}
            to="/$locale/tickers/$symbol"
            params={{ locale, symbol: ticker.routeKey }}
            aria-label={`${ticker.symbol} ${ticker.name}`}
            className={`focus-ring inline-flex min-h-11 shrink-0 items-center gap-2 rounded-md border px-3 text-sm font-semibold ${
              (ticker.symbol === activeSymbol || ticker.routeKey === activeSymbol)
                ? "border-accent bg-accentSoft text-accent"
                : "border-line bg-panelAlt text-muted hover:border-accent hover:text-ink"
            }`}
          >
            {ticker.displaySymbol}
            {" "}
            <span className="max-w-[160px] truncate text-xs font-medium">{ticker.name}</span>
          </Link>
        ))}
      </div>
    </nav>
  );
}

function TradingViewWidget({
  ticker,
  preset,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  preset: ChartPresetKey;
  locale: "en" | "ko";
}>) {
  const [shouldShowFrame, setShouldShowFrame] = useState(false);
  const [frameReady, setFrameReady] = useState(false);
  const isSafeSymbol = safeTradingViewSymbol.test(ticker.tradingViewSymbol);
  const embedUrl = useMemo(
    () => (isSafeSymbol ? tradingViewEmbedUrl(ticker, preset, locale) : ""),
    [isSafeSymbol, locale, preset, ticker]
  );
  const loadingTitle = localeText(locale, "Load Interactive Chart", "인터랙티브 차트 로드");
  const loadingDetail = localeText(locale, "The chart opens automatically in a moment, or you can load it now.", "차트는 잠시 후 자동으로 열립니다. 바로 열 수도 있습니다.");
  const openChartLabel = localeText(locale, "Open chart", "차트 열기");
  const widgetLabel = localeText(locale, "External display widget", "외부 표시 위젯");
  const invalidSymbolLabel = localeText(locale, "TradingView symbol validation failed.", "TradingView 심볼 검증에 실패했습니다.");
  let chartBody: ReactNode;

  if (isSafeSymbol) {
    chartBody = (
      <div className="relative h-[clamp(300px,45svh,390px)] w-full bg-[#050b14] md:h-[58vh] md:min-h-[640px] xl:h-[66vh] xl:max-h-[780px]">
        {shouldShowFrame && (
          <iframe
            key={embedUrl}
            title={`${ticker.displaySymbol} TradingView chart`}
            src={embedUrl}
            className="h-full w-full border-0 bg-[#050b14]"
            loading="eager"
            referrerPolicy="strict-origin-when-cross-origin"
            allowFullScreen
            onLoad={() => setFrameReady(true)}
          />
        )}
        {!frameReady && (
          <div
            className="absolute inset-0 grid place-items-center p-4 text-center"
            style={{
              background:
                "linear-gradient(rgba(82, 221, 255, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(82, 221, 255, 0.08) 1px, transparent 1px), #050b14",
              backgroundSize: "64px 64px"
            }}
          >
            <div className="max-w-md rounded-md border border-line bg-panel/95 p-5 shadow-2xl">
              <LineChartIcon className="mx-auto h-8 w-8 text-accent" />
              <h3 className="mt-3 text-base font-semibold">{loadingTitle}</h3>
              <p className="mt-2 text-sm leading-6 text-muted">{loadingDetail}</p>
              <button type="button" className="primary-action mt-4" onClick={() => setShouldShowFrame(true)}>
                <LineChartIcon className="h-4 w-4" />
                {openChartLabel}
              </button>
            </div>
          </div>
        )}
        <div className="pointer-events-none absolute bottom-3 left-3 rounded border border-line bg-panel/90 px-2 py-1 text-[11px] font-semibold text-muted">
          {widgetLabel}
        </div>
      </div>
    );
  } else {
    chartBody = (
      <div className="grid h-[320px] place-items-center p-6 text-center text-sm leading-6 text-muted md:h-[420px]">
        {invalidSymbolLabel}
      </div>
    );
  }

  useEffect(() => {
    setFrameReady(false);
    setShouldShowFrame(false);
    if (!isSafeSymbol) return undefined;
    const loadTimer = globalThis.window.setTimeout(() => setShouldShowFrame(true), 450);
    return () => globalThis.window.clearTimeout(loadTimer);
  }, [isSafeSymbol, embedUrl]);

  return (
    <section className="panel min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold leading-5">{ticker.displaySymbol} {locale === "ko" ? "차트" : "Chart"}</h2>
          <p className="text-xs leading-5 text-muted">
            {locale === "ko"
              ? "TradingView 표시 위젯, 데이터는 백엔드에 저장하지 않습니다."
              : "TradingView display widget; no backend ingestion from this frame."}
          </p>
        </div>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ticker.tradingViewSymbol)}`}
          target="_blank"
          rel="noreferrer"
          className="secondary-action h-11 min-h-11 px-3 py-2"
        >
          <ExternalLink className="h-4 w-4" />
          TradingView
        </a>
      </div>
      {chartBody}
    </section>
  );
}

function tradingViewEmbedUrl(ticker: TrackedTicker, preset: ChartPresetKey, locale: "en" | "ko") {
  const widgetLocale = locale === "ko" ? "kr" : "en";
  const config = {
    autosize: true,
    symbol: ticker.tradingViewSymbol,
    interval: "D",
    timezone: "Etc/UTC",
    theme: "dark",
    style: "1",
    locale: widgetLocale,
    enable_publishing: false,
    allow_symbol_change: true,
    save_image: true,
    calendar: false,
    hide_side_toolbar: false,
    hide_top_toolbar: false,
    withdateranges: true,
    studies: chartPresets[preset].studies,
    support_host: "https://www.tradingview.com",
    width: "100%",
    height: "100%"
  };
  return `https://www.tradingview-widget.com/embed-widget/advanced-chart/?locale=${widgetLocale}#${encodeURIComponent(JSON.stringify(config))}`;
}

function OverviewPanel({
  ticker,
  indicators,
  shortItems,
  newsItems,
  filings,
  transactions,
  canDisplayMarketData,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  indicators: IndicatorSet;
  shortItems: TickerSignal[];
  newsItems: TickerSignal[];
  filings: DisclosureFiling[];
  transactions: DisclosureTransaction[];
  canDisplayMarketData: boolean;
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  let marketMetrics: ReactNode;
  if (canDisplayMarketData) {
    marketMetrics = (
      <>
        <MetricCard label="RSI 14" value={formatFixed(indicators.rsi14, 1)} detail={indicatorHint("rsi", indicators.rsi14, locale)} />
        <MetricCard label="MACD" value={formatFixed(indicators.macd.histogram, 2)} detail={indicatorHint("macd", indicators.macd.histogram, locale)} />
        <MetricCard label={isKo ? "거래량" : "Volume"} value={formatNumber(indicators.latestVolume)} detail={volumeHint(indicators, locale)} />
      </>
    );
  } else {
    marketMetrics = (
      <div className="rounded-md border border-line bg-panelAlt p-4 text-sm leading-6 text-muted md:col-span-3">
        {localeText(
          locale,
          "Market-data values are withheld unless public display is explicitly permitted. Use the TradingView chart for visual market inspection.",
          "공개 표시 허가가 없는 시장 데이터는 가격/지표 값으로 표시하지 않습니다. TradingView 차트를 시각 확인용으로 사용하세요."
        )}
      </div>
    );
  }

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,0.62fr)_minmax(320px,0.38fr)]">
      <div className="panel p-5">
        <SectionHeader
          icon={<ListChecks className="h-5 w-5" />}
          title={isKo ? "투자 체크리스트" : "Research Checklist"}
          subtitle={isKo ? "강세/약세/무효화 조건을 한 화면에서 검토합니다." : "A compact bull, bear, and invalidation pass for this tracked ticker."}
        />
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <ThesisCard label={isKo ? "강세" : "Bull Case"} value={ticker.thesisBull} tone="green" />
          <ThesisCard label={isKo ? "약세" : "Bear Case"} value={ticker.thesisBear} tone="danger" />
          <ThesisCard label={isKo ? "무효화" : "Invalidation"} value={ticker.invalidation} tone="warning" />
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {marketMetrics}
        </div>
      </div>

      <div className="grid gap-4">
        <CompactList
          title={isKo ? "공매도 / 이벤트" : "Shorts / Events"}
          empty={isKo ? "현재 스냅샷에 이 티커 관련 공매도 행이 없습니다." : "No ticker-specific short row in the current snapshot."}
          items={[...shortItems, ...newsItems].slice(0, 4)}
          locale={locale}
        />
        <div className="panel p-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">{isKo ? "공시 요약" : "Filings Snapshot"}</h2>
            <span className="badge border-line bg-panelAlt text-muted">{filings.length + transactions.length}</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted">
            {isKo
              ? "SEC/OGE 원문 연결 행만 표시합니다. 추론된 사설 계좌 활동은 포함하지 않습니다."
              : "Only source-linked SEC/OGE rows are shown. Private brokerage activity is not inferred."}
          </p>
        </div>
      </div>
    </section>
  );
}

function ChartPanel({
  ticker,
  preset,
  onPresetChange,
  points,
  freshness,
  canDisplayMarketData,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  preset: ChartPresetKey;
  onPresetChange: (preset: ChartPresetKey) => void;
  points: MarketPoint[];
  freshness: FreshnessMeta;
  canDisplayMarketData: boolean;
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  const chartPoints = points.slice(-90).map((point) => ({ date: point.date, value: point.close }));
  let chartContent: ReactNode;
  if (canDisplayMarketData && chartPoints.length > 1) {
    chartContent = <LineChart points={chartPoints} label={`${ticker.symbol} daily close`} />;
  } else if (canDisplayMarketData) {
    chartContent = <EmptyState text={localeText(locale, "Daily history has not loaded yet.", "일봉 시계열을 아직 불러오지 못했습니다.")} />;
  } else {
    chartContent = <EmptyState text={localeText(locale, "App-computed price charts are hidden until public display is permitted.", "공개 표시 허가가 없어 앱 계산 가격 그래프를 숨깁니다.")} />;
  }

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="panel p-5">
        <SectionHeader
          icon={<LineChartIcon className="h-5 w-5" />}
          title={isKo ? "앱 계산 일봉 스냅샷" : "App-Computed Daily Snapshot"}
          subtitle={isKo ? "백엔드는 항상 무료 시계열에서 받은 일봉 종가만 사용합니다." : "The backend uses daily close history from always-free providers, not the TradingView widget."}
        />
        {chartContent}
        <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
          <div>{freshness.providerLabel}</div>
          <div>{freshness.delayLabel}</div>
          <div>{freshness.stalenessReason}</div>
        </div>
      </div>
      <div className="panel p-5">
        <h2 className="text-sm font-semibold">{isKo ? "차트 프리셋" : "Chart Presets"}</h2>
        <div className="mt-4 grid gap-2">
          {(Object.keys(chartPresets) as ChartPresetKey[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`focus-ring rounded-md border px-3 py-3 text-left ${
                preset === key ? "border-accent bg-accentSoft text-accent" : "border-line bg-panelAlt text-ink hover:border-accent"
              }`}
              onClick={() => onPresetChange(key)}
            >
              <div className="text-sm font-semibold">{isKo ? chartPresets[key].labelKo : chartPresets[key].labelEn}</div>
              <div className="mt-1 text-xs leading-5 text-muted">{isKo ? chartPresets[key].detailKo : chartPresets[key].detailEn}</div>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function TechnicalsPanel({
  indicators,
  ticker,
  freshness,
  canDisplayMarketData,
  locale
}: Readonly<{
  indicators: IndicatorSet;
  ticker: TrackedTicker;
  freshness: FreshnessMeta;
  canDisplayMarketData: boolean;
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  const scoreContent = canDisplayMarketData ? (
    <>
      <div className="mt-5 text-5xl font-bold">{indicators.score.total}</div>
      <p className="mt-2 text-sm font-semibold text-accent">{technicalBiasLabel(indicators.score.total, locale)}</p>
      <div className="mt-5 grid gap-3">
        {Object.entries(indicators.score.parts).map(([key, value]) => (
          <ScoreRow key={key} label={scoreLabel(key, locale)} value={value} max={scoreMax(key)} />
        ))}
      </div>
    </>
  ) : (
    <EmptyState text={localeText(locale, "Technical score is withheld by public-display policy.", "공개 표시 제한으로 기술 점수를 숨깁니다.")} />
  );
  let indicatorContent: ReactNode;
  if (canDisplayMarketData) {
    indicatorContent = (
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <IndicatorMetricCard label="Close" value={formatCurrency(indicators.latestClose, ticker.currency)} previous={formatCurrency(indicators.previousClose, ticker.currency)} signal={dailyChangeSignal(indicators.changePct, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="SMA 50" value={formatCurrency(indicators.sma50, ticker.currency)} previous="n/a" signal={distanceHint(indicators.latestClose, indicators.sma50, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="SMA 200" value={formatCurrency(indicators.sma200, ticker.currency)} previous="n/a" signal={distanceHint(indicators.latestClose, indicators.sma200, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="EMA 20" value={formatCurrency(indicators.ema20, ticker.currency)} previous="n/a" signal={distanceHint(indicators.latestClose, indicators.ema20, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="RSI 14" value={formatFixed(indicators.rsi14, 1)} previous={formatFixed(indicators.previousRsi14, 1)} signal={indicatorHint("rsi", indicators.rsi14, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="Stoch RSI" value={formatPercent((indicators.stochRsi ?? Number.NaN) * 100)} previous="n/a" signal={indicatorHint("stoch", indicators.stochRsi, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="MACD hist" value={formatFixed(indicators.macd.histogram, 2)} previous={formatFixed(indicators.previousMacdHistogram, 2)} signal={macdSignal(indicators, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="Bollinger pos" value={formatPercent(indicators.bollinger.position * 100)} previous="n/a" signal={bollingerHint(indicators, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="52W range" value={formatPercent(indicators.rangePosition * 100)} previous="n/a" signal={rangeHint(indicators, locale)} freshness={freshness} locale={locale} />
        <IndicatorMetricCard label="VWAP" value={localeText(locale, "Unavailable", "없음")} previous="n/a" signal={localeText(locale, "Intraday candles required.", "분봉 데이터가 필요합니다.")} freshness={freshness} locale={locale} disabled />
        <IndicatorMetricCard label="ATR" value={localeText(locale, "Unavailable", "없음")} previous="n/a" signal={localeText(locale, "High/low candles required.", "고가/저가 캔들이 필요합니다.")} freshness={freshness} locale={locale} disabled />
        <IndicatorMetricCard label="Volume SMA20" value={formatNumber(indicators.volumeSma20)} previous="n/a" signal={volumeHint(indicators, locale)} freshness={freshness} locale={locale} />
      </div>
    );
  } else {
    indicatorContent = (
      <EmptyState text={localeText(locale, "Price and indicator values are shown only when the provider permits public display.", "가격/지표 값은 공개 표시 허가가 있는 공급자에서만 표시합니다.")} />
    );
  }

  return (
    <section className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="panel p-5">
        <SectionHeader
          icon={<Sparkles className="h-5 w-5" />}
          title={isKo ? "기술 점수" : "Technical Score"}
          subtitle={isKo ? "무료 일봉 데이터로 앱이 직접 계산합니다." : "Calculated by the app from free daily candle history."}
        />
        {scoreContent}
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<BarChart3 className="h-5 w-5" />}
          title={isKo ? "계산 지표" : "Computed Indicators"}
          subtitle={isKo ? "VWAP/ATR은 필요한 분봉 또는 고가/저가가 없을 때 명시적으로 비활성화합니다." : "VWAP/ATR are explicitly disabled when intraday or high/low data is unavailable."}
        />
        {indicatorContent}
      </div>
    </section>
  );
}

function OptionsPanel({ ticker, locale }: Readonly<{ ticker: TrackedTicker; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  return (
    <section className="panel min-w-0 p-5">
      <SectionHeader
        icon={<Activity className="h-5 w-5" />}
        title={isKo ? "옵션 라이트" : "Options Lite"}
        subtitle={isKo ? "항상 무료 범위에서는 같은 날 옵션 체인을 표시하지 않습니다." : "Same-day option chains are not available under the always-free source policy."}
      />
      <div className="signal-warning mt-4 p-4 text-sm leading-6">
        {isKo
          ? "Same-day 옵션 체인은 항상 무료 공개 표시 소스가 아니므로 현재 값처럼 보이는 체인을 만들지 않습니다. MarketData.app 같은 이전 세션/24시간 지연 소스가 연결되면 모든 값에 지연 배지를 붙여 표시합니다."
          : "Same-day option chains are not available under the always-free public-display policy. When a previous-session or 24h-delayed source is connected, every value will be labeled with that delay."}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-4">
        {optionsSummaryFields(locale).map((field) => (
          <MetricCard key={field.label} label={field.label} value={field.value} detail={field.detail} />
        ))}
      </div>
      <div className="mt-5 table-surface" data-allow-horizontal-scroll aria-label={isKo ? "옵션 체인 표" : "Options chain table"}>
        <table className="min-w-full text-left text-sm">
          <thead className="table-head">
            <tr>
              {(isKo
                ? ["행사가", "콜 매수", "콜 매도", "콜 거래량", "콜 OI", "콜 IV", "콜 델타", "풋 매수", "풋 매도", "풋 거래량", "풋 OI", "풋 IV", "풋 델타"]
                : ["Strike", "Call bid", "Call ask", "Call vol", "Call OI", "Call IV", "Call delta", "Put bid", "Put ask", "Put vol", "Put OI", "Put IV", "Put delta"]
              ).map((heading) => (
                <th key={heading} className="px-3 py-3">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-line">
              <td className="px-3 py-4 text-muted" colSpan={13}>
                {isKo ? "체인 데이터 미연결: 24시간 지연/이전 세션 공급자 연결 대기" : "Chain unavailable: waiting for a 24h-delayed/previous-session provider connection"}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <a
        href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ticker.tradingViewSymbol)}`}
        target="_blank"
        rel="noreferrer"
        className="secondary-action mt-5"
      >
        <ExternalLink className="h-4 w-4" />
        {isKo ? "TradingView에서 확인" : "Open TradingView"}
      </a>
    </section>
  );
}

function NewsPanel({
  ticker,
  tickerNews,
  newsLoading,
  newsError,
  trumpItems,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  tickerNews?: NewsTickerSnapshotData;
  newsLoading: boolean;
  newsError: unknown;
  trumpItems: TickerSignal[];
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  const events = tickerNews?.events ?? [];
  let newsContent: ReactNode;
  if (newsLoading) {
    newsContent = <EmptyState text={localeText(locale, "Loading ticker news snapshot.", "티커 뉴스 스냅샷을 불러오는 중입니다.")} />;
  } else if (newsError) {
    newsContent = <EmptyState text={localeText(locale, "No ticker news snapshot is available for this symbol yet.", "이 티커의 뉴스 스냅샷이 아직 없습니다.")} />;
  } else if (events.length) {
    newsContent = events.map((event) => <TickerNewsEvent key={event.id} event={event} locale={locale} />);
  } else {
    newsContent = <EmptyState text={localeText(locale, "No directly matched news events in the current snapshot.", "현재 스냅샷에는 이 티커와 직접 연결된 뉴스가 없습니다.")} />;
  }
  let tickerSummary: ReactNode = null;
  if (tickerNews) {
    tickerSummary = (
      <div className="mt-3 rounded-md border border-line bg-panelAlt p-3 text-sm leading-6 text-muted">
        <div className="font-semibold text-ink">{tickerNews.summary}</div>
        <div className="mt-1 text-xs">{localeText(locale, "Generated", "생성")} {formatDateTime(tickerNews.generated_label)}</div>
      </div>
    );
  }
  let primarySources: ReactNode = null;
  if (events.length) {
    primarySources = (
      <div className="mt-4 grid gap-2">
        <h3 className="text-sm font-semibold">{localeText(locale, "Primary Sources", "주요 출처")}</h3>
        {events
          .flatMap((event) => event.source_links.filter((source) => source.is_primary))
          .slice(0, 4)
          .map((source) => <SourcePill key={`${source.source_key}-${source.url}`} source={source} />)}
      </div>
    );
  }
  let trumpBlock: ReactNode = null;
  if (trumpItems.length) {
    trumpBlock = (
      <div className="mt-4">
        <CompactList title={localeText(locale, "Trump-Related Items", "트럼프 관련 항목")} empty="" items={trumpItems} locale={locale} />
      </div>
    );
  }

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.42fr)]">
      <div className="panel p-5">
        <SectionHeader
          icon={<Newspaper className="h-5 w-5" />}
          title={isKo ? "티커 관련 뉴스" : "Ticker-Relevant News"}
          subtitle={isKo ? "출처, 시각, 관련 티커, 중요도 라벨을 함께 표시합니다." : "Source, time, related ticker, and importance labels stay visible."}
        />
        {tickerSummary}
        <div className="mt-4 grid gap-3">
          {newsContent}
        </div>
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<Newspaper className="h-5 w-5" />}
          title={isKo ? "수집 기준" : "Inclusion Rule"}
          subtitle={
            isKo
              ? "뉴스는 추적 티커, 회사명, 섹터 이벤트에 직접 연결될 때만 표시합니다."
              : "News appears here only when it directly matches the tracked ticker, company name, or sector event."
          }
        />
        <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
          <div>{ticker.tags.join(" / ")}</div>
          <div>{isKo ? "공개 페이지는 스냅샷만 읽고, 긴 문서 AI 요약은 사전 생성된 경우에만 표시합니다." : "The public page reads snapshots only; long-document AI summaries appear only after pre-publication generation."}</div>
        </div>
        {primarySources}
        {trumpBlock}
      </div>
    </section>
  );
}

function ShortsPanel({ ticker, shortItems, locale }: Readonly<{ ticker: TrackedTicker; shortItems: TickerSignal[]; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  const shortContent = shortItems.length
    ? shortItems.map((signal) => <SignalLink key={`${signal.group}-${signal.item.key}`} signal={signal} locale={locale} />)
    : <EmptyState text={localeText(locale, "No structured FINRA short row is available for this ticker in the current snapshot.", "이번 스냅샷에는 이 티커의 구조화된 FINRA 공매도 행이 없습니다.")} />;

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="panel p-5">
        <SectionHeader
          icon={<TrendingDown className="h-5 w-5" />}
          title={isKo ? "출처 기반 공매도" : "Source-backed shorts"}
          subtitle={
            isKo
              ? "공매도 잔고와 일별 공매도 거래량을 분리해 표시합니다. 텍스트 추측 매칭은 사용하지 않습니다."
              : "Short interest and daily short-volume flow are separated. Text-guess matches are not used."
          }
        />
        <div className="mt-4 grid gap-3">
          {shortContent}
        </div>
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<ShieldAlert className="h-5 w-5" />}
          title={isKo ? "해석 가드레일" : "Interpretation guardrails"}
          subtitle={isKo ? "공매도 데이터는 직접 매매 신호가 아닙니다." : "Short data is not a standalone trade signal."}
        />
        <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
          <div>{ticker.displaySymbol}</div>
          <div>{isKo ? "공매도 잔고는 미청산 포지션이고 보통 지연 공개됩니다." : "Short interest is an open-position figure and is usually published with delay."}</div>
          <div>{isKo ? "일별 공매도 거래량은 거래 흐름이며 잔고가 아닙니다." : "Daily short volume is transaction flow, not outstanding short interest."}</div>
          <Link className="focus-ring inline-flex min-h-11 items-center gap-1 rounded-md font-semibold text-accent hover:underline" to="/$locale/shorts" params={{ locale }}>
            {isKo ? "전체 공매도 탭" : "Open Shorts tab"}
            <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}

function TickerNewsEvent({ event, locale }: Readonly<{ event: NewsEventListItem; locale: "en" | "ko" }>) {
  return <NewsEventCard event={event} locale={locale} compact />;
}

function FilingsPanel({
  ticker,
  filings,
  transactions,
  insiders,
  filingsError,
  transactionsError,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  filings: DisclosureFiling[];
  transactions: DisclosureTransaction[];
  insiders: InsidersResponse["insiders"];
  filingsError: unknown;
  transactionsError: unknown;
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  const filingRows = filings.length
    ? filings.map((filing) => <FilingRow key={`${filing.source}-${filing.id}`} filing={filing} locale={locale} />)
    : <EmptyState text={localeText(locale, "No filing rows for this ticker yet.", "이 티커의 공시 행이 아직 없습니다.")} />;
  let insiderRows: ReactNode;
  if (insiders.length) {
    insiderRows = insiders.slice(0, 8).map((owner) => (
      <div key={owner.owner_name} className="rounded-md border border-line bg-panelAlt p-3">
        <div className="text-sm font-semibold">{owner.owner_name}</div>
        <div className="mt-1 text-xs leading-5 text-muted">
          {owner.transactions} {isKo ? "거래 행" : "rows"} / {owner.latest_transaction_date ?? "date pending"}
        </div>
      </div>
    ));
  } else {
    insiderRows = <EmptyState text={localeText(locale, "No SEC insider rows yet.", "SEC 내부자 행이 없습니다.")} />;
  }
  const transactionRows = transactions.length
    ? transactions.map((transaction) => <TransactionRow key={transaction.id} transaction={transaction} locale={locale} />)
    : <EmptyState text={localeText(locale, "No transaction rows yet.", "거래 행이 아직 없습니다.")} />;
  const hasDisclosureError = Boolean(filingsError || transactionsError);

  return (
    <section className="grid gap-5">
      {hasDisclosureError && (
        <div className="signal-warning p-4 text-sm leading-6">
          {isKo ? "공시 API를 읽지 못해 스냅샷 데이터만 사용할 수 있습니다." : "Disclosure API is unavailable; only snapshot data can be shown."}
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="panel p-5">
          <SectionHeader
            icon={<FileText className="h-5 w-5" />}
            title={isKo ? "원문 연결 공시" : "Source-Linked Filings"}
            subtitle={isKo ? "모든 행은 원문으로 이동합니다." : "Every row links back to the original filing."}
          />
          <div className="mt-4 grid gap-3">
            {filingRows}
          </div>
          <div className="mt-4 grid gap-2 rounded-md border border-line bg-panelAlt p-3 text-xs leading-5 text-muted">
            <div className="font-semibold text-ink">{isKo ? "고우선순위 공시 알림 기준" : "High-priority filing alert rules"}</div>
            <div>
              {isKo
                ? "증자, ATM, 워런트, 역분할, 계속기업, 내부자 매수/매도, 부채 약정, 주요 고객/계약, 정부 계약을 우선 표시 대상으로 둡니다."
                : "Share offerings, ATMs, warrants, reverse splits, going-concern language, insider buys/sells, debt covenants, major customers/contracts, and government contracts are priority topics."}
            </div>
            <a className="focus-ring inline-flex min-h-11 items-center gap-1 rounded-md font-semibold text-accent hover:underline" href={`https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker.symbol)}`} target="_blank" rel="noreferrer">
              SEC full-text search
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
        <div className="panel p-5">
          <SectionHeader
            icon={<Database className="h-5 w-5" />}
            title={isKo ? "내부자/소유자" : "Insiders / Owners"}
            subtitle={isKo ? "SEC 거래 행에서 집계합니다." : "Aggregated from SEC transaction rows."}
          />
          <div className="mt-4 grid gap-2">
            {insiderRows}
          </div>
        </div>
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<Activity className="h-5 w-5" />}
          title={isKo ? "거래 행" : "Transaction Rows"}
          subtitle={isKo ? "OGE 금액은 범위이며, SEC Form 144는 매도 의향이지 체결 증거가 아닙니다." : "OGE amounts are ranges; SEC Form 144 is sale intent, not proof of execution."}
        />
        <div className="mt-4 grid gap-3">
          {transactionRows}
        </div>
      </div>
    </section>
  );
}

function FundamentalsPanel({ ticker, locale }: Readonly<{ ticker: TrackedTicker; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  const equityFields = [
    "Market cap",
    "Revenue",
    "Revenue growth",
    "Gross margin",
    "Operating margin",
    "Net income",
    "Free cash flow",
    "Cash",
    "Debt",
    "Shares outstanding",
    "Dilution trend",
    "Price / sales",
    "EV / sales",
    "Price / book"
  ];
  const etfFields = ["NAV", "Expense ratio", "AUM", "Holdings", "Premium / discount", "Leverage factor", "Issuer", "Rebalance frequency"];
  const fields = ticker.assetType === "ETF" ? etfFields : equityFields;
  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="panel p-5">
        <SectionHeader
          icon={<Database className="h-5 w-5" />}
          title={isKo ? "펀더멘털" : "Fundamentals"}
          subtitle={
            isKo
              ? "공식 SEC company facts 또는 공개 표시 허가가 있는 참조 공급자가 연결되면 값을 표시합니다."
              : "Values appear after SEC company facts or a public-display-approved reference provider is connected."
          }
        />
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {fields.map((field) => (
            <MetricCard
              key={field}
              label={isKo ? translateFundamental(field) : field}
              value={isKo ? "대기" : "Pending"}
              detail={isKo ? "공개 표시 허가/공식 filings 필요" : "Requires official filings or display permission"}
            />
          ))}
        </div>
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<FileText className="h-5 w-5" />}
          title={isKo ? "소스 우선순위" : "Source Priority"}
          subtitle={isKo ? "라이선스 제한을 값과 분리해 둡니다." : "License constraints stay separate from values."}
        />
        <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
          <div>1. SEC company facts</div>
          <div>2. FMP Basic profile/reference when terms allow</div>
          <div>3. Finnhub profile when terms allow</div>
          <a className="focus-ring mt-2 inline-flex min-h-11 items-center gap-1 rounded-md font-semibold text-accent hover:underline" href={`https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker.symbol)}`} target="_blank" rel="noreferrer">
            SEC source
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
    </section>
  );
}

function NotesPanel({ ticker, locale }: Readonly<{ ticker: TrackedTicker; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  return (
    <section className="grid gap-5 lg:grid-cols-2">
      <div className="panel p-5">
        <SectionHeader
          icon={<Bell className="h-5 w-5" />}
          title={isKo ? "알림" : "Alerts"}
          subtitle={isKo ? "공개 익명 세션에서는 저장형 알림을 만들지 않습니다." : "Saved alerts are disabled for anonymous public sessions."}
        />
        <div className="mt-4 grid gap-3">
          {["Price break", "SEC filing", "Short interest update", "Ticker news"].map((item) => (
            <label key={item} className="flex items-center justify-between rounded-md border border-line bg-panelAlt px-3 py-2 text-sm text-muted">
              {isKo ? translateAlert(item) : item}
              <input type="checkbox" disabled className="h-4 w-4" />
            </label>
          ))}
        </div>
      </div>
      <div className="panel p-5">
        <SectionHeader
          icon={<FileText className="h-5 w-5" />}
          title={isKo ? "리서치 노트" : "Research Notes"}
          subtitle={isKo ? "서버 저장 기능이 생기면 티커별 노트를 연결합니다." : "Ticker-scoped notes can attach here once server persistence is enabled."}
        />
        <textarea
          className="input-control mt-4 min-h-[180px] w-full resize-y leading-6"
          disabled
          value={isKo ? `${ticker.symbol} 공개 노트는 아직 비활성화되어 있습니다.` : `${ticker.symbol} public notes are not enabled yet.`}
          readOnly
        />
      </div>
    </section>
  );
}

function ResearchSidebar({ // NOSONAR - sidebar groups watchlist, quick read, and source-backed research blocks.
  ticker,
  snapshot,
  indicators,
  transactions,
  freshness,
  canDisplayMarketData,
  locale
}: Readonly<{
  ticker: TrackedTicker;
  snapshot?: SnapshotEnvelope<HomeSnapshotData>;
  indicators: IndicatorSet;
  transactions: DisclosureTransaction[];
  freshness: FreshnessMeta;
  canDisplayMarketData: boolean;
  locale: "en" | "ko";
}>) {
  const isKo = locale === "ko";
  const railTickers = sidebarTickerList(ticker);
  return (
    <aside className="grid content-start gap-3 xl:sticky xl:top-24 xl:max-h-[calc(100vh-7rem)] xl:overflow-y-auto xl:pr-1">
      <div className="panel h-[300px] overflow-y-auto">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold">{isKo ? "관심 티커" : "Watchlist"}</h2>
          <span className="badge border-line bg-panelAlt text-muted">{railTickers.length}</span>
        </div>
        <div className="divide-y divide-line">
          {railTickers.map((item) => {
            const isActive = item.entityId === ticker.entityId;
            return (
              <EntityLink
                key={item.entityId}
                value={item}
                locale={locale}
                className={`focus-ring grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-sm hover:bg-panelAlt ${
                  isActive ? "bg-accentSoft text-accent" : "text-ink"
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-bold">{item.displaySymbol}</span>
                  <span className={`mt-0.5 block truncate text-xs ${isActive ? "text-accent" : "text-muted"}`}>{item.name}</span>
                </span>
                <ChevronRight className="h-4 w-4 shrink-0" />
              </EntityLink>
            );
          })}
        </div>
      </div>

      <div className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "빠른 판단" : "Quick Read"}</h2>
        <div className="mt-3 grid gap-2 text-sm leading-6 text-muted">
          <div>{canDisplayMarketData ? technicalBiasLabel(indicators.score.total, locale) : freshness.delayLabel}</div>
          <div>{isKo ? "데이터" : "Data"}: {freshness.licenseMode}</div>
          <div>RSI: {canDisplayMarketData ? formatFixed(indicators.rsi14, 1) : "withheld"}</div>
          <div>MACD: {canDisplayMarketData ? macdSignal(indicators, locale) : "withheld"}</div>
          <div>200D: {canDisplayMarketData ? distanceHint(indicators.latestClose, indicators.sma200, locale) : "withheld"}</div>
          <div>
            {isKo ? "스냅샷 생성" : "Snapshot generated"}: {snapshot?.generated_at ? formatDateTime(snapshot.generated_at) : "pending"}
          </div>
          <div>
            {isKo ? "거래/공시 행" : "Transaction rows"}: {transactions.length}
          </div>
        </div>
      </div>
      <div className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "논지" : "Thesis"}</h2>
        <div className="mt-3 grid gap-2 text-xs leading-5 text-muted">
          <div><span className="font-semibold text-success">{isKo ? "강세" : "Bull"}:</span> {ticker.thesisBull}</div>
          <div><span className="font-semibold text-danger">{isKo ? "약세" : "Bear"}:</span> {ticker.thesisBear}</div>
          <div><span className="font-semibold text-warning">{isKo ? "무효화" : "Invalidation"}:</span> {ticker.invalidation}</div>
          <div>{isKo ? "목표/포지션/확신도는 노트 저장 기능 연결 후 표시됩니다." : "Target, position, and conviction appear once notes/watchlist persistence is connected."}</div>
        </div>
      </div>
      <div className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "알림 / 예정 이벤트" : "Alerts / Upcoming Events"}</h2>
        <div className="mt-3 grid gap-2 text-xs leading-5 text-muted">
          <div>{isKo ? "가격, RSI, MACD, 거래량, SEC 공시, 뉴스 급증 알림 준비." : "Price, RSI, MACD, volume, SEC filing, and news-spike alerts are modeled here."}</div>
          <div>{isKo ? "옵션 알림은 same-day 옵션 데이터가 연결될 때까지 비활성화." : "Options alerts remain disabled until same-day options data is connected."}</div>
        </div>
      </div>
      <div className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "데이터 정책" : "Data Policy"}</h2>
        <div className="mt-3 grid gap-2 text-xs leading-5 text-muted">
          <div>{freshness.delayLabel}</div>
          <div>{freshness.stalenessReason}</div>
          <div>
            {isKo
              ? "공급자별 제한과 원문 정책은 관리자 상태 화면에서만 노출합니다."
              : "Provider limits and source-policy internals stay on the admin/status surface, not the public ticker page."}
          </div>
        </div>
      </div>
    </aside>
  );
}

function sidebarTickerList(ticker: TrackedTicker): TrackedEntity[] {
  const related = relatedTrackedEntities(ticker, 10);
  if (related.some((entity) => entity.entityId === ticker.entityId)) {
    return related;
  }
  return [ticker, ...related].slice(0, 10);
}

function CompactList({
  title,
  empty,
  items,
  locale
}: Readonly<{
  title: string;
  empty: string;
  items: TickerSignal[];
  locale: "en" | "ko";
}>) {
  return (
    <div className="panel p-4">
      <h2 className="text-sm font-semibold">{title}</h2>
      <div className="mt-3 grid gap-2">
        {items.length ? (
          items.map((signal) => <SignalLink key={`${signal.group}-${signal.item.key}`} signal={signal} locale={locale} />)
        ) : (
          <EmptyState text={empty} />
        )}
      </div>
    </div>
  );
}

function SignalLink({ signal, locale }: Readonly<{ signal: TickerSignal; locale: "en" | "ko" }>) {
  const sourceIcon = signal.item.source_url ? (
    <ExternalLink className="h-3.5 w-3.5 text-accent" aria-label={localeText(locale, "source", "원문")} />
  ) : null;
  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="safe-text min-w-0 text-sm font-semibold leading-5">{signal.item.label}</div>
        <span className="safe-text shrink-0 text-xs font-semibold text-accent">{signal.item.value}</span>
      </div>
      <p className="safe-text mt-1 text-xs leading-5 text-muted">{signal.item.detail}</p>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] leading-4 text-muted">
        <span className="safe-text min-w-0">{signal.context}</span>
        {sourceIcon}
      </div>
    </>
  );
  const className = "focus-ring block min-h-11 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent";
  if (signal.item.source_url) {
    return (
      <a className={className} href={signal.item.source_url} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <div className={className}>{content}</div>;
}

function SectionHeader({ icon, title, subtitle }: Readonly<{ icon: ReactNode; title: string; subtitle: string }>) {
  return (
    <div className="min-w-0">
      <h2 className="safe-text flex items-center gap-2 text-lg font-bold leading-7">
        <span className="text-accent">{icon}</span>
        {title}
      </h2>
      <p className="safe-text mt-1 text-sm leading-6 text-muted">{subtitle}</p>
    </div>
  );
}

function HeaderAction({ icon, label, disabled = false }: Readonly<{ icon: ReactNode; label: string; disabled?: boolean }>) {
  return (
    <button
      type="button"
      disabled={disabled}
      className="secondary-action h-11 min-h-11 shrink-0 px-2.5 py-2 disabled:cursor-not-allowed disabled:opacity-55 sm:px-3"
      title={disabled ? "Persistence pending" : label}
      aria-label={label}
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function MiniStat({ label, value, className = "" }: Readonly<{ label: string; value: string; className?: string }>) {
  return (
    <div className={`min-w-[92px] rounded-md border border-line bg-panelAlt px-3 py-2 ${className}`}>
      <div className="truncate text-[10px] font-semibold uppercase leading-4 text-muted">{label}</div>
      <div className="truncate text-sm font-bold leading-5">{value}</div>
    </div>
  );
}

function FreshnessPill({ freshness, locale }: Readonly<{ freshness: FreshnessMeta; locale: "en" | "ko" }>) {
  const tone = freshness.isPublicDisplayAllowed ? "border-success/50 bg-success/10 text-success" : "border-warning/50 bg-warning/10 text-warning";
  return (
    <span className={`badge ${tone}`} title={`${freshness.stalenessReason} / ${freshness.licenseMode}`}>
      {locale === "ko" && !freshness.isPublicDisplayAllowed ? "라이선스 제한" : freshness.delayLabel}
    </span>
  );
}

function ThesisCard({ label, value, tone }: Readonly<{ label: string; value: string; tone: "green" | "danger" | "warning" }>) {
  const toneClass = thesisToneClass(tone);
  return (
    <article className="rounded-md border border-line bg-panelAlt p-4">
      <div className={`text-sm font-semibold ${toneClass}`}>{label}</div>
      <p className="mt-2 text-sm leading-6 text-muted">{value}</p>
    </article>
  );
}

function thesisToneClass(tone: "green" | "danger" | "warning") {
  if (tone === "green") return "text-success";
  if (tone === "danger") return "text-danger";
  return "text-warning";
}

function IndicatorMetricCard({
  label,
  value,
  previous,
  signal,
  freshness,
  locale,
  disabled = false
}: Readonly<{
  label: string;
  value: string;
  previous: string;
  signal: string;
  freshness: FreshnessMeta;
  locale: "en" | "ko";
  disabled?: boolean;
}>) {
  const previousLabel = locale === "ko" ? "이전" : "Previous";
  const signalLabel = locale === "ko" ? "신호" : "Signal";
  const timestamp = freshness.providerTimestamp ?? (locale === "ko" ? "시각 대기" : "timestamp pending");
  return (
    <article
      className={`rounded-md border border-line bg-panelAlt p-4 ${disabled ? "opacity-75" : ""}`}
      title={`${label}: ${signal}. Data source ${freshness.providerLabel}. ${freshness.stalenessReason}`}
    >
      <div className="text-xs font-semibold uppercase leading-5 text-muted">{label}</div>
      <div className="mt-2 text-2xl font-bold leading-tight">{value}</div>
      <div className="mt-2 grid gap-1 text-xs leading-5 text-muted">
        <div>{previousLabel}: {previous}</div>
        <div>{signalLabel}: {signal}</div>
        <div>{timestamp}</div>
        <div>{freshness.providerLabel}</div>
        <FreshnessPill freshness={freshness} locale={locale} />
      </div>
    </article>
  );
}

function MetaTile({ icon, label, value, detail }: Readonly<{ icon: ReactNode; label: string; value: string; detail: string }>) {
  return (
    <article className="panel p-4">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase leading-5 text-muted">
        <span className="text-accent">{icon}</span>
        {label}
      </div>
      <div className="mt-2 text-lg font-bold leading-7">{value}</div>
      <p className="mt-1 text-xs leading-5 text-muted">{detail}</p>
    </article>
  );
}

function NewsSignalCard({ signal, ticker, locale }: Readonly<{ signal: TickerSignal; ticker: TrackedTicker; locale: "en" | "ko" }>) {
  const item = signal.item;
  const content = (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge border-line bg-panel">{item.source || signal.context}</span>
        <span className="badge border-line bg-panelAlt">{ticker.symbol}</span>
        <span className="badge border-warning/40 bg-warning/10 text-warning">{importanceLabel(item.severity, locale)}</span>
      </div>
      <h3 className="mt-3 text-sm font-semibold leading-5">{item.label}</h3>
      <p className="mt-2 text-sm leading-6 text-muted">{item.detail}</p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs leading-5 text-muted">
        <span>{item.updated_at || "time pending"}</span>
        <span>{locale === "ko" ? "감성" : "Sentiment"}: {sentimentFromSeverity(item.severity, locale)}</span>
        <span>{locale === "ko" ? "중요도" : "Importance"}: {importanceScore(item.severity)}/100</span>
      </div>
    </>
  );
  const className = "focus-ring block rounded-md border border-line bg-panelAlt p-4 hover:border-accent";
  if (item.source_url) {
    return (
      <a className={className} href={item.source_url} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <article className={className}>{content}</article>;
}

function MetricCard({ label, value, detail }: Readonly<{ label: string; value: string; detail: string }>) {
  return (
    <article className="rounded-md border border-line bg-panelAlt p-4">
      <div className="text-xs font-semibold uppercase leading-5 text-muted">{label}</div>
      <div className="mt-2 text-2xl font-bold leading-tight">{value}</div>
      <p className="mt-2 text-xs leading-5 text-muted">{detail}</p>
    </article>
  );
}

function ScoreRow({ label, value, max }: Readonly<{ label: string; value: number; max: number }>) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-xs font-semibold uppercase text-muted">
        <span>{label}</span>
        <span>
          {value}/{max}
        </span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-panelAlt">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function FilingRow({ filing, locale }: Readonly<{ filing: DisclosureFiling; locale: "en" | "ko" }>) {
  return (
    <a
      className="focus-ring block rounded-md border border-line bg-panelAlt p-4 hover:border-accent"
      href={filing.source_url}
      target="_blank"
      rel="noreferrer"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap gap-2">
            <span className="badge border-accent/40 bg-accentSoft text-accent">{filing.source}</span>
            <span className="badge border-line bg-panel">{filing.form_type}</span>
          </div>
          <h3 className="mt-3 truncate text-sm font-semibold">{filing.issuer_name || filing.filer_name || filing.accession_number || "Public filing"}</h3>
          <p className="mt-1 text-xs leading-5 text-muted">{filing.doc_date || filing.filed_at || (locale === "ko" ? "날짜 대기" : "date pending")}</p>
        </div>
        <div className="shrink-0 text-right text-xs leading-5 text-muted">
          <div>{filing.parse_status}</div>
          <div className="font-semibold text-ink">{filing.transaction_count ?? 0}</div>
        </div>
      </div>
    </a>
  );
}

function TransactionRow({ transaction, locale }: Readonly<{ transaction: DisclosureTransaction; locale: "en" | "ko" }>) {
  const label = disclosureTransactionLabel(transaction, locale);
  const bucket = disclosureTransactionBucket(transaction, locale);
  const caveat = disclosureTransactionCaveat(transaction, locale);
  return (
    <a
      className="focus-ring grid gap-3 rounded-md border border-line bg-panelAlt p-4 hover:border-accent md:grid-cols-[minmax(0,1fr)_160px_150px]"
      href={transaction.source_url}
      target="_blank"
      rel="noreferrer"
    >
      <div className="min-w-0">
        <div className="flex flex-wrap gap-2">
          <span className="badge border-accent/40 bg-accentSoft text-accent">{transaction.source}</span>
          <span className="badge border-line bg-panel">{transaction.form_type}</span>
          {transaction.ticker ? <span className="badge border-line bg-panel">{transaction.ticker}</span> : null}
        </div>
        <h3 className="mt-3 truncate text-sm font-semibold">
          {transaction.issuer_name || transaction.asset_description || transaction.owner_name || "Disclosure row"}
        </h3>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted">{transaction.asset_description}</p>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase leading-5 text-muted">{locale === "ko" ? "거래" : "Transaction"}</div>
        <div className="mt-1 text-sm font-bold">{label}</div>
        <div className="mt-1 inline-flex rounded border border-line bg-panel px-2 py-1 text-[11px] font-semibold uppercase leading-4 text-muted">{bucket}</div>
        <div className="mt-1 text-xs leading-5 text-muted">{transaction.transaction_date || "date pending"}</div>
        {caveat ? <div className="mt-1 text-xs leading-5 text-warning">{caveat}</div> : null}
      </div>
      <div>
        <div className="text-xs font-semibold uppercase leading-5 text-muted">{locale === "ko" ? "규모" : "Size"}</div>
        <div className="mt-1 text-sm font-bold">{formatTransactionSize(transaction)}</div>
        <div className="mt-1 text-xs leading-5 text-muted">{transaction.owner_name || transaction.person_name || "owner pending"}</div>
      </div>
    </a>
  );
}

function EmptyState({ text }: Readonly<{ text: string }>) {
  return <div className="rounded-md border border-dashed border-line p-4 text-sm leading-6 text-muted">{text}</div>;
}

interface TickerSignal {
  item: AlternativeSignalItem;
  context: string;
  group: "shorts" | "news" | "event" | "trump";
}

function collectTickerSignals(data: HomeSnapshotData, ticker: TrackedTicker): TickerSignal[] {
  const groups = new Map<string, TickerSignal["group"]>([
    ["highest_short_interest", "shorts"],
    ["short_volume_monitor", "shorts"],
    ["breaking_market_news", "news"],
    ["trump_filings", "trump"]
  ]);

  return data.alternative_signals.flatMap((lane) => {
    const group = groups.get(lane.key) ?? (lane.key.includes("news") ? "news" : "event");
    return lane.items
      .filter((item) => matchesTicker(item, ticker))
      .map((item) => ({ item, context: lane.title || lane.cadence, group }));
  });
}

function matchesTicker(item: AlternativeSignalItem, ticker: TrackedTicker) {
  const itemSymbols = item.symbols?.map((symbol) => symbol.toUpperCase()) ?? [];
  if (itemSymbols.length) {
    return itemSymbols.includes(ticker.symbol.toUpperCase());
  }
  const keySymbol = newsSymbolKey(ticker.symbol).toLowerCase();
  return item.key.toLowerCase().endsWith(`_${keySymbol}`);
}

function newsSymbolKey(symbol: string) {
  let routeKey = "";
  for (const char of symbol.toUpperCase()) {
    if (isUpperAsciiAlphaNumeric(char)) {
      routeKey += char;
    } else if (routeKey.length > 0 && !routeKey.endsWith("_")) {
      routeKey += "_";
    }
  }
  return routeKey.endsWith("_") ? routeKey.slice(0, -1) : routeKey;
}

function isUpperAsciiAlphaNumeric(char: string): boolean {
  const code = char.codePointAt(0) ?? 0;
  return (code >= 48 && code <= 57) || (code >= 65 && code <= 90);
}

interface FreshnessMeta {
  providerLabel: string;
  delayLabel: string;
  stalenessReason: string;
  ageLabel: string;
  sameDayValid: boolean;
  isPublicDisplayAllowed: boolean;
  licenseMode: string;
  providerTimestamp: string | null;
  fetchedAt: string | null;
}

function buildFreshnessMeta(payload: MarketHistoryResponse | undefined, updatedAt: number, latestPoint?: MarketPoint): FreshnessMeta {
  if (payload?.data_freshness) {
    const sourceTime =
      payload.data_freshness.source_observed_at ??
      payload.data_freshness.market_session_date ??
      payload.data_freshness.provider_timestamp ??
      payload.data_freshness.fetched_at;
    const staleness = payload.data_freshness.staleness_state;
    return {
      providerLabel: `provider: ${payload.data_freshness.provider}`,
      delayLabel: staleness === "stale_fallback" ? "stale fallback" : payload.data_freshness.delay_label,
      stalenessReason: payload.data_freshness.staleness_reason,
      ageLabel: relativeAge(new Date(sourceTime).getTime()),
      sameDayValid: payload.data_freshness.is_same_day_valid,
      isPublicDisplayAllowed: payload.data_freshness.is_public_display_allowed,
      licenseMode: payload.data_freshness.license_mode,
      providerTimestamp: payload.data_freshness.complete_through ?? payload.data_freshness.provider_timestamp,
      fetchedAt: payload.data_freshness.fetched_at
    };
  }
  const provider = payload?.provider ?? "provider pending";
  const latestDate = latestPoint?.date ?? "date pending";
  const today = isoDate(new Date());
  const sameDayValid = latestDate === today;
  return {
    providerLabel: `provider: ${provider}`,
    delayLabel: sameDayValid ? "current-day daily snapshot, not realtime" : "daily / previous-session snapshot",
    stalenessReason: payload?.source_note || `latest candle ${latestDate}; no intraday redistribution claimed`,
    ageLabel: updatedAt ? relativeAge(updatedAt) : "pending",
    sameDayValid,
    isPublicDisplayAllowed: true,
    licenseMode: "legacy",
    providerTimestamp: latestDate,
    fetchedAt: null
  };
}

interface IndicatorSet {
  latestPoint?: MarketPoint;
  latestClose: number;
  previousClose: number;
  change: number;
  changePct: number;
  latestVolume: number;
  volumeSma20: number;
  volumeRatio: number;
  sma50: number;
  sma200: number;
  ema20: number;
  rsi14: number;
  previousRsi14: number;
  stochRsi: number;
  macd: {
    line: number;
    signal: number;
    histogram: number;
  };
  previousMacdHistogram: number;
  bollinger: {
    lower: number;
    middle: number;
    upper: number;
    position: number;
  };
  rangeHigh: number;
  rangeLow: number;
  rangePosition: number;
  score: {
    total: number;
    parts: {
      trend: number;
      momentum: number;
      volume: number;
      volatility: number;
      relative: number;
    };
  };
}

function computeIndicatorSet(points: MarketPoint[]): IndicatorSet {
  const clean = normalizePoints(points);
  const closes = clean.map((point) => point.close);
  const volumes = clean.map((point) => Number(point.volume ?? Number.NaN)).filter(Number.isFinite);
  const latestPoint = clean.at(-1);
  const latestClose = latestPoint?.close ?? Number.NaN;
  const previousClose = clean.at(-2)?.close ?? Number.NaN;
  const change = finite(latestClose - previousClose);
  const changePct = finite((change / previousClose) * 100);
  const latestVolume = Number(latestPoint?.volume ?? Number.NaN);
  const volumeSma20 = average(volumes.slice(-20));
  const volumeRatio = finite(latestVolume / volumeSma20);
  const sma50 = average(closes.slice(-50));
  const sma200 = average(closes.slice(-200));
  const ema20 = lastFinite(emaSeries(closes, 20));
  const rsiValues = rsiSeries(closes, 14);
  const rsi14 = lastFinite(rsiValues);
  const previousRsi14 = previousFinite(rsiValues);
  const rsiWindow = rsiValues.filter(Number.isFinite).slice(-14);
  const rsiMin = Math.min(...rsiWindow);
  const rsiMax = Math.max(...rsiWindow);
  const stochRsi = finite((rsi14 - rsiMin) / (rsiMax - rsiMin || 1));
  const macd = computeMacd(closes);
  const previousMacdHistogram = computePreviousMacdHistogram(closes);
  const bandWindow = closes.slice(-20);
  const bollingerMiddle = average(bandWindow);
  const bandStd = stdDev(bandWindow);
  const bollingerLower = bollingerMiddle - bandStd * 2;
  const bollingerUpper = bollingerMiddle + bandStd * 2;
  const bollingerPosition = finite((latestClose - bollingerLower) / (bollingerUpper - bollingerLower || 1));
  const rangeWindow = closes.slice(-252);
  const rangeHigh = Math.max(...rangeWindow);
  const rangeLow = Math.min(...rangeWindow);
  const rangePosition = finite((latestClose - rangeLow) / (rangeHigh - rangeLow || 1));
  const score = technicalScore({
    latestClose,
    previousClose,
    sma50,
    sma200,
    ema20,
    rsi14,
    stochRsi,
    macdHistogram: macd.histogram,
    volumeRatio,
    bollingerPosition,
    changePct,
    rangePosition
  });

  return {
    latestPoint,
    latestClose,
    previousClose,
    change,
    changePct,
    latestVolume,
    volumeSma20,
    volumeRatio,
    sma50,
    sma200,
    ema20,
    rsi14,
    previousRsi14,
    stochRsi,
    macd,
    previousMacdHistogram,
    bollinger: {
      lower: bollingerLower,
      middle: bollingerMiddle,
      upper: bollingerUpper,
      position: bollingerPosition
    },
    rangeHigh,
    rangeLow,
    rangePosition,
    score
  };
}

function technicalScore(input: { // NOSONAR - scoring thresholds are intentionally colocated for formula review.
  latestClose: number;
  previousClose: number;
  sma50: number;
  sma200: number;
  ema20: number;
  rsi14: number;
  stochRsi: number;
  macdHistogram: number;
  volumeRatio: number;
  bollingerPosition: number;
  changePct: number;
  rangePosition: number;
}) {
  const parts = {
    trend: 0,
    momentum: 0,
    volume: 0,
    volatility: 0,
    relative: 0
  };
  if (input.latestClose > input.sma50) parts.trend += 12;
  if (input.latestClose > input.sma200) parts.trend += 12;
  if (input.ema20 > input.sma50) parts.trend += 6;
  if (input.latestClose > input.previousClose) parts.trend += 5;
  if (input.rsi14 >= 45 && input.rsi14 <= 65) parts.momentum += 8;
  if (input.rsi14 > 55 && input.rsi14 < 75) parts.momentum += 7;
  if (input.macdHistogram > 0) parts.momentum += 7;
  if (input.stochRsi > 0.2 && input.stochRsi < 0.85) parts.momentum += 3;
  if (input.volumeRatio >= 0.8 && input.volumeRatio <= 1.8) parts.volume += 8;
  if (input.volumeRatio > 1 && input.latestClose > input.previousClose) parts.volume += 8;
  if (input.volumeRatio < 2.5) parts.volume += 4;
  if (input.bollingerPosition > 0.15 && input.bollingerPosition < 0.9) parts.volatility += 6;
  if (Math.abs(input.changePct) < 8) parts.volatility += 4;
  if (input.rangePosition > 0.45) parts.relative += 6;
  if (input.rangePosition < 0.92) parts.relative += 4;
  return {
    total: Object.values(parts).reduce((sum, value) => sum + value, 0),
    parts
  };
}

function normalizePoints(points: MarketPoint[]) {
  return points
    .filter((point) => Number.isFinite(point.close))
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));
}

function rsiSeries(values: number[], period: number) {
  const result = new Array<number>(values.length).fill(Number.NaN);
  if (values.length <= period) return result;
  let gain = 0;
  let loss = 0;
  for (let index = 1; index <= period; index += 1) {
    const delta = values[index] - values[index - 1];
    if (delta >= 0) gain += delta;
    else loss += Math.abs(delta);
  }
  let averageGain = gain / period;
  let averageLoss = loss / period;
  result[period] = 100 - 100 / (1 + averageGain / (averageLoss || 1e-9));
  for (let index = period + 1; index < values.length; index += 1) {
    const delta = values[index] - values[index - 1];
    const currentGain = Math.max(delta, 0);
    const currentLoss = Math.max(-delta, 0);
    averageGain = (averageGain * (period - 1) + currentGain) / period;
    averageLoss = (averageLoss * (period - 1) + currentLoss) / period;
    result[index] = 100 - 100 / (1 + averageGain / (averageLoss || 1e-9));
  }
  return result;
}

function emaSeries(values: number[], period: number) {
  const result = new Array<number>(values.length).fill(Number.NaN);
  if (values.length < period) return result;
  const multiplier = 2 / (period + 1);
  let ema = average(values.slice(0, period));
  result[period - 1] = ema;
  for (let index = period; index < values.length; index += 1) {
    ema = (values[index] - ema) * multiplier + ema;
    result[index] = ema;
  }
  return result;
}

function computeMacd(values: number[]) {
  const ema12 = emaSeries(values, 12);
  const ema26 = emaSeries(values, 26);
  const lineValues = values.map((_, index) => finite(ema12[index] - ema26[index]));
  const compactLine = lineValues.filter(Number.isFinite);
  const signal = lastFinite(emaSeries(compactLine, 9));
  const line = lastFinite(lineValues);
  return {
    line,
    signal,
    histogram: finite(line - signal)
  };
}

function computePreviousMacdHistogram(values: number[]) {
  if (values.length < 35) return Number.NaN;
  return computeMacd(values.slice(0, -1)).histogram;
}

function average(values: number[]) {
  const clean = values.filter(Number.isFinite);
  if (!clean.length) return Number.NaN;
  return clean.reduce((sum, value) => sum + value, 0) / clean.length;
}

function stdDev(values: number[]) {
  const avg = average(values);
  if (!Number.isFinite(avg)) return Number.NaN;
  return Math.sqrt(average(values.map((value) => (value - avg) ** 2)));
}

function lastFinite(values: number[]) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (Number.isFinite(values[index])) return values[index];
  }
  return Number.NaN;
}

function previousFinite(values: number[]) {
  let seenLast = false;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (!Number.isFinite(values[index])) continue;
    if (seenLast) return values[index];
    seenLast = true;
  }
  return Number.NaN;
}

function finite(value: number) {
  return Number.isFinite(value) ? value : Number.NaN;
}

function tickerDateRange() {
  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setFullYear(startDate.getFullYear() - 1);
  return {
    start: isoDate(startDate),
    end: isoDate(endDate)
  };
}

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function relativeAge(timestampMs: number) {
  const minutes = Math.max(0, Math.round((Date.now() - timestampMs) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function formatCurrency(value: number, currency: string) {
  if (!Number.isFinite(value)) return "pending";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: value >= 100 ? 2 : 3
  }).format(value);
}

function formatSigned(value: number, currency: string) {
  if (!Number.isFinite(value)) return "pending";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatCurrency(value, currency)}`;
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "pending";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatFixed(value: number, digits: number) {
  return Number.isFinite(value) ? value.toFixed(digits) : "pending";
}

function formatNumber(value: number) {
  if (!Number.isFinite(value)) return "pending";
  return new Intl.NumberFormat("en-US", { notation: value >= 1_000_000 ? "compact" : "standard", maximumFractionDigits: 2 }).format(value);
}

function formatTransactionSize(transaction: DisclosureTransaction) {
  if (transaction.source === "OGE") {
    if (transaction.amount_min == null && transaction.amount_max == null) return "range pending";
    if (transaction.amount_max == null) return `>${formatCurrency(transaction.amount_min ?? 0, "USD")}`;
    return `${formatCurrency(transaction.amount_min ?? 0, "USD")}-${formatCurrency(transaction.amount_max, "USD")}`;
  }
  const shares = transaction.shares == null ? "" : `${formatNumber(transaction.shares)} sh`;
  const price = transaction.price == null ? "" : `@ ${formatCurrency(transaction.price, "USD")}`;
  return [shares, price].filter(Boolean).join(" ") || transaction.transaction_code || "reported";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function technicalBiasLabel(score: number, locale: "en" | "ko") {
  if (score >= 72) return locale === "ko" ? "강한 추세 확인" : "Strong trend confirmation";
  if (score >= 55) return locale === "ko" ? "건설적이지만 확인 필요" : "Constructive, needs confirmation";
  if (score >= 40) return locale === "ko" ? "중립/혼재" : "Neutral or mixed";
  return locale === "ko" ? "취약한 기술 상태" : "Technically fragile";
}

function dailyChangeSignal(changePct: number, locale: "en" | "ko") {
  if (!Number.isFinite(changePct)) return localeText(locale, "Change pending", "변동률 대기");
  const signal = [
    { test: changePct >= 5, en: "Strong up day", ko: "강한 상승일" },
    { test: changePct >= 1.5, en: "Positive session", ko: "상승 우위" },
    { test: changePct <= -5, en: "Strong down day", ko: "강한 하락일" },
    { test: changePct <= -1.5, en: "Negative session", ko: "하락 우위" }
  ].find((item) => item.test);
  return localeText(locale, signal?.en ?? "Narrow move", signal?.ko ?? "좁은 변동");
}

function macdSignal(indicators: IndicatorSet, locale: "en" | "ko") {
  const current = indicators.macd.histogram;
  const previous = indicators.previousMacdHistogram;
  if (!Number.isFinite(current)) return localeText(locale, "MACD pending", "MACD 계산 대기");
  const direction = macdDirectionLabel(current, previous, locale);
  if (current > 0) return localeText(locale, `Positive histogram, ${direction}`, `양의 히스토그램, ${direction}`);
  if (current < 0) return localeText(locale, `Negative histogram, ${direction}`, `음의 히스토그램, ${direction}`);
  return localeText(locale, `Neutral histogram, ${direction}`, `중립 히스토그램, ${direction}`);
}

function macdDirectionLabel(current: number, previous: number, locale: "en" | "ko") {
  if (!Number.isFinite(previous)) return localeText(locale, "flat", "횡보");
  if (current > previous) return localeText(locale, "rising", "확대");
  if (current < previous) return localeText(locale, "falling", "축소");
  return localeText(locale, "flat", "횡보");
}

function optionsSummaryFields(locale: "en" | "ko") { // NOSONAR - static bilingual option placeholders are kept auditable together.
  const isKo = locale === "ko";
  return [
    {
      label: isKo ? "데이터 신선도" : "Data freshness",
      value: isKo ? "미연결" : "Not connected",
      detail: isKo ? "same-day 공개 표시 소스 없음" : "No same-day public-display source"
    },
    {
      label: isKo ? "만기" : "Expiration",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "체인 연결 후 선택 가능" : "Selectable after chain data is connected"
    },
    {
      label: isKo ? "만기까지" : "Days to expiry",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "선택 만기 기준" : "Based on selected expiration"
    },
    {
      label: "ATM IV",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "24시간 지연이면 명시" : "Labeled if 24h delayed"
    },
    {
      label: isKo ? "ATM 스트래들" : "ATM straddle",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "실제 bid/ask 연결 필요" : "Requires real bid/ask source"
    },
    {
      label: isKo ? "예상 변동" : "Expected move",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "스트래들 기반 계산" : "Computed from straddle when available"
    },
    {
      label: isKo ? "콜 거래량 / OI" : "Call volume / OI",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "체인 연결 후 집계" : "Aggregated after chain data is connected"
    },
    {
      label: isKo ? "풋 거래량 / OI" : "Put volume / OI",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "체인 연결 후 집계" : "Aggregated after chain data is connected"
    },
    {
      label: isKo ? "P/C 비율" : "Put/call ratios",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "거래량과 OI를 분리 표시" : "Volume and OI ratios stay separate"
    },
    {
      label: isKo ? "최대 거래량 행사가" : "Highest-volume strikes",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "콜/풋 각각 표시" : "Shown separately for calls and puts"
    },
    {
      label: isKo ? "최대 OI 행사가" : "Highest-OI strikes",
      value: isKo ? "대기" : "Pending",
      detail: isKo ? "콜/풋 각각 표시" : "Shown separately for calls and puts"
    },
    {
      label: isKo ? "계산 금지" : "No synthetic chain",
      value: isKo ? "명시" : "Explicit",
      detail: isKo ? "실제 체인처럼 보이는 임의 값을 만들지 않음" : "No generated values that look like a live chain"
    }
  ];
}

function translateFundamental(field: string) {
  const values: Record<string, string> = {
    "Market cap": "시가총액",
    Revenue: "매출",
    "Revenue growth": "매출 성장률",
    "Gross margin": "매출총이익률",
    "Operating margin": "영업이익률",
    "Net income": "순이익",
    "Free cash flow": "잉여현금흐름",
    Cash: "현금",
    Debt: "부채",
    "Shares outstanding": "발행주식수",
    "Dilution trend": "희석 추세",
    "Price / sales": "주가/매출",
    "EV / sales": "EV/매출",
    "Price / book": "주가/장부가",
    NAV: "순자산가치",
    "Expense ratio": "보수율",
    AUM: "운용자산",
    Holdings: "보유종목",
    "Premium / discount": "프리미엄/할인",
    "Leverage factor": "레버리지 배수",
    Issuer: "운용사",
    "Rebalance frequency": "리밸런싱 주기"
  };
  return values[field] ?? field;
}

function importanceLabel(severity: string | undefined, locale: "en" | "ko") {
  const key = (severity || "medium").toLowerCase();
  if (key === "critical") return locale === "ko" ? "긴급" : "critical";
  if (key === "high") return locale === "ko" ? "높음" : "high";
  if (key === "low") return locale === "ko" ? "낮음" : "low";
  return locale === "ko" ? "중간" : "medium";
}

function sentimentFromSeverity(severity: string | undefined, locale: "en" | "ko") {
  const key = (severity || "medium").toLowerCase();
  if (key === "critical" || key === "high") return locale === "ko" ? "시장 민감" : "market-sensitive";
  if (key === "low") return locale === "ko" ? "관찰" : "watch";
  return locale === "ko" ? "맥락 필요" : "context-needed";
}

function importanceScore(severity: string | undefined) {
  const key = (severity || "medium").toLowerCase();
  if (key === "critical") return 95;
  if (key === "high") return 82;
  if (key === "low") return 35;
  return 60;
}

function indicatorHint(kind: "rsi" | "macd" | "stoch", value: number, locale: "en" | "ko") {
  if (!Number.isFinite(value)) return localeText(locale, "Not enough data", "계산할 데이터 부족");
  if (kind === "rsi") {
    if (value > 70) return localeText(locale, "Overbought zone", "과열권");
    if (value < 30) return localeText(locale, "Oversold zone", "과매도권");
    return localeText(locale, "Neutral band", "중립권");
  }
  if (kind === "macd") {
    return value > 0 ? localeText(locale, "Positive momentum", "상방 모멘텀") : localeText(locale, "Negative momentum", "하방 모멘텀");
  }
  if (value > 0.8) return localeText(locale, "Upper band", "상단부");
  if (value < 0.2) return localeText(locale, "Lower band", "하단부");
  return localeText(locale, "Neutral band", "중립권");
}

function volumeHint(indicators: IndicatorSet, locale: "en" | "ko") {
  if (!Number.isFinite(indicators.volumeRatio)) return locale === "ko" ? "거래량 데이터 없음" : "No volume data";
  return locale === "ko"
    ? `20일 평균 대비 ${indicators.volumeRatio.toFixed(2)}배`
    : `${indicators.volumeRatio.toFixed(2)}x 20-day average`;
}

function distanceHint(value: number, reference: number, locale: "en" | "ko") {
  if (!Number.isFinite(value) || !Number.isFinite(reference)) return locale === "ko" ? "계산 대기" : "Calculation pending";
  const distance = ((value - reference) / reference) * 100;
  return locale === "ko" ? `기준 대비 ${formatPercent(distance)}` : `${formatPercent(distance)} versus reference`;
}

function bollingerHint(indicators: IndicatorSet, locale: "en" | "ko") {
  const position = indicators.bollinger.position;
  if (!Number.isFinite(position)) return locale === "ko" ? "계산 대기" : "Calculation pending";
  if (position > 1) return locale === "ko" ? "상단 밴드 위" : "Above upper band";
  if (position < 0) return locale === "ko" ? "하단 밴드 아래" : "Below lower band";
  return locale === "ko" ? "밴드 내부" : "Inside bands";
}

function rangeHint(indicators: IndicatorSet, locale: "en" | "ko") {
  if (!Number.isFinite(indicators.rangePosition)) return locale === "ko" ? "계산 대기" : "Calculation pending";
  return locale === "ko"
    ? `52주 범위: ${formatFixed(indicators.rangeLow, 2)} - ${formatFixed(indicators.rangeHigh, 2)}`
    : `52W range: ${formatFixed(indicators.rangeLow, 2)} - ${formatFixed(indicators.rangeHigh, 2)}`;
}

function scoreLabel(key: string, locale: "en" | "ko") {
  const labels: Record<string, [string, string]> = {
    trend: ["Trend", "추세"],
    momentum: ["Momentum", "모멘텀"],
    volume: ["Volume", "거래량"],
    volatility: ["Volatility", "변동성"],
    relative: ["Range", "범위"]
  };
  return locale === "ko" ? labels[key]?.[1] ?? key : labels[key]?.[0] ?? key;
}

function scoreMax(key: string) {
  const max: Record<string, number> = {
    trend: 35,
    momentum: 25,
    volume: 20,
    volatility: 10,
    relative: 10
  };
  return max[key] ?? 1;
}

function translateAlert(item: string) {
  const values: Record<string, string> = {
    "Price break": "가격 돌파",
    "SEC filing": "SEC 공시",
    "Short interest update": "공매도 잔고 갱신",
    "Ticker news": "티커 뉴스"
  };
  return values[item] ?? item;
}
