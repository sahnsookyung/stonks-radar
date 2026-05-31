import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  Database,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  ShieldAlert
} from "lucide-react";
import type { ReactNode } from "react";
import type { FundPortfolioSnapshotData, Locale } from "@frw/shared-types";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { LoadingState } from "../components/LoadingState";
import { TermTooltip } from "../components/TermTooltip";
import { apiGet } from "../lib/api";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

interface DisclosureSummary {
  legal_use_warning: string;
  limitations: string[];
  filings: DisclosureFiling[];
  transactions: DisclosureTransaction[];
  watched_people: WatchedPerson[];
  open_review_items: number;
}

interface DisclosureFiling {
  id: number;
  source: "OGE" | "SEC";
  form_type: string;
  source_url: string;
  parse_status: string;
  transaction_count: number;
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
  post_transaction_shares?: number | null;
  confidence?: number | null;
  source_url: string;
  form_type: string;
  filed_at?: string | null;
  doc_date?: string | null;
}

interface WatchedPerson {
  canonical_name: string;
  category: string;
  tickers: string[];
  sec_ciks: string[];
}

export function FundsTrackerPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const fundQuery = useQuery({
    queryKey: ["snapshot", "fund-portfolio", "situational-awareness", locale],
    queryFn: () => snapshotQueries.fundPortfolio("situational-awareness", locale)
  });
  const disclosureQuery = useQuery({
    queryKey: ["trump-disclosures", "funds-tracker", locale],
    queryFn: () => apiGet<DisclosureSummary>("/api/public/trump-disclosures/summary?limit=80"),
    retry: false
  });

  const fundData = fundQuery.data?.data;
  const disclosure = disclosureQuery.data;
  const trumpHoldings = latestDisclosedHoldings(disclosure?.transactions ?? []);
  const ogeRangeCount = (disclosure?.transactions ?? []).filter(
    (transaction) => transaction.source === "OGE" && (transaction.amount_min != null || transaction.amount_max != null)
  ).length;
  const secExactCount = trumpHoldings.length;

  if (fundQuery.isLoading && disclosureQuery.isLoading) return <LoadingState />;

  return (
    <div className="grid min-w-0 gap-7">
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <Database className="h-4 w-4" />
            {isKo ? "공개 펀드 및 공시 추적" : "Public funds and disclosure tracker"}
          </div>
          <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">
            {isKo ? "Funds Tracker" : "Funds Tracker"}
          </h1>
          <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
            {isKo
              ? "분기 13F 포트폴리오와 트럼프 관련 공개 공시를 한 곳에 모읍니다. 이 화면은 실시간 포트폴리오나 투자 복제 도구가 아닙니다."
              : "A single public-filing surface for delayed 13F portfolios and Trump-related public disclosure exposure. This is not a real-time portfolio, not a live holdings feed, and not a copy-trading product."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label={isKo ? "공개 원문 연결" : "source-linked public filings"} />
          <SourceBadge label={isKo ? "지연 데이터" : "delayed data"} />
          <FreshnessBadge value={fundData?.freshness ?? "watch"} />
        </div>
      </section>

      <section className="signal-warning min-w-0 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0" />
          <p className="safe-text min-w-0 text-sm font-semibold leading-6">
            {isKo
              ? "강한 제한: 트럼프 노출은 공개 공시 기반 신뢰 구간입니다. 정확한 현재 포트폴리오, 실시간 추적, 사설 계좌, 가족 구성원의 비공개 거래를 의미하지 않습니다."
              : "Strong limitation: Trump exposure is a public-disclosure confidence interval. It is not an accurate current portfolio, not real-time tracking, and not evidence of private brokerage activity or undisclosed family trades."}
          </p>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <LeopoldFundCard data={fundData} locale={locale} loading={fundQuery.isLoading} error={fundQuery.error} />
        <TrumpDisclosureCard
          disclosure={disclosure}
          disclosureLoading={disclosureQuery.isLoading}
          disclosureError={disclosureQuery.error}
          secExactCount={secExactCount}
          ogeRangeCount={ogeRangeCount}
          holdings={trumpHoldings}
          locale={locale}
        />
      </section>

      <section className="panel p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-1 h-5 w-5 shrink-0 text-warning" />
          <div className="min-w-0">
            <h2 className="safe-text text-xl font-bold">
              {isKo ? "트럼프 공시와 13F 포트폴리오가 다른 이유" : "Why Trump disclosures are not the same as a 13F portfolio"}
            </h2>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">
              {isKo
                ? "13F는 특정 투자 매니저의 분기 말 장기 주식 보유를 표준화된 XML로 보여줍니다. OGE/SEC 트럼프 공시는 거래, 범위 금액, 내부자 보유량, 매도 의향 같은 서로 다른 공시 조각입니다."
                : "A 13F is a standardized quarterly XML view of a manager's long holdings. Trump-related OGE/SEC records are different disclosure fragments: transactions, amount ranges, insider holdings, or proposed sale intent."}
            </p>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <LimitTile
                title="SEC Form 4"
                value={isKo ? "정확한 행 가능" : "Exact rows possible"}
                detail={
                  isKo
                    ? "해당 내부자 행은 주식 수, 가격, 거래 후 보유량을 제공할 수 있습니다."
                    : "Covered insider rows can provide shares, price, and post-transaction holdings."
                }
              />
              <LimitTile
                title="OGE 278-T / 278e"
                value={isKo ? "범위 기반" : "Range-based"}
                detail={
                  isKo
                    ? "금액은 구간이고 최대 45일 이상 지연될 수 있습니다."
                    : "Amounts are bands and can be delayed; they are exposure intervals, not exact marks."
                }
              />
              <LimitTile
                title="Form 144 / 13D-G"
                value={isKo ? "맥락 공시" : "Context filings"}
                detail={
                  isKo
                    ? "매도 의향이나 대량 보유 공시이지 모든 거래 원장이 아닙니다."
                    : "Shows proposed sale intent or large ownership, not a full transaction ledger."
                }
              />
              <LimitTile
                title={isKo ? "비공개 영역" : "Unknown area"}
                value={isKo ? "재구성 불가" : "Not reconstructable"}
                detail={
                  isKo
                    ? "사설 계좌와 비공개 사업 가치는 공개 파일링만으로는 알 수 없습니다."
                    : "Private brokerage accounts and private business values cannot be reconstructed from public filings alone."
                }
              />
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function LeopoldFundCard({
  data,
  locale,
  loading,
  error
}: {
  data?: FundPortfolioSnapshotData;
  locale: Locale;
  loading: boolean;
  error: unknown;
}) {
  const isKo = locale === "ko";
  return (
    <article className="panel min-w-0 p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
            <FileSpreadsheet className="h-4 w-4" />
            {isKo ? "분기 13F 포트폴리오" : "Quarterly 13F portfolio"}
          </div>
          <h2 className="safe-text mt-3 text-2xl font-bold">
            {data?.display_name ?? (isKo ? "레오폴드 아셴브레너" : "Leopold Aschenbrenner")}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label="SEC EDGAR 13F" />
          <SourceBadge label={isKo ? "분기 지연" : "quarterly lag"} />
        </div>
      </div>
      {loading ? <p className="mt-4 text-sm text-muted">{isKo ? "불러오는 중..." : "Loading..."}</p> : null}
      {error ? (
        <p className="safe-text mt-4 rounded-md border border-line bg-panelAlt p-3 text-sm leading-6 text-muted">
          {isKo ? "13F 스냅샷을 읽지 못했습니다." : "Could not load the 13F snapshot."}
        </p>
      ) : null}
      {data ? (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <Metric label={isKo ? "롱 주식 가치" : "Long equity value"} value={formatUsd(data.summary_metrics.long_equity_value_usd)} termKey="portfolio_value" />
            <Metric label={isKo ? "보유 행" : "Holding rows"} value={String(data.summary_metrics.holding_count)} termKey="data_quality" />
            <Metric label={isKo ? "보고일" : "Report date"} value={data.filing?.report_date ?? "pending"} />
            <Metric label={isKo ? "공시일" : "Filed"} value={data.filing?.filed_at ?? "pending"} />
          </div>
          <div className="mt-5 grid gap-2">
            {data.top_equity_holdings.slice(0, 5).map((holding) => (
              <SafeExternalAnchor
                key={holding.id}
                className="focus-ring grid min-h-11 grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent"
                href={holding.source_url}
              >
                <div className="min-w-0">
                  <div className="safe-text text-sm font-bold">{holding.symbol ?? holding.cusip}</div>
                  <div className="safe-text text-xs leading-5 text-muted">{holding.issuer_name}</div>
                </div>
                <div className="text-right text-sm font-semibold">{formatPercent(holding.portfolio_weight)}</div>
              </SafeExternalAnchor>
            ))}
          </div>
        </>
      ) : null}
      <Link className="secondary-action mt-5 min-h-11 px-3 py-2" to="/$locale/funds/$fundKey" params={{ locale, fundKey: "situational-awareness" }}>
        {isKo ? "13F 상세 보기" : "Open 13F details"}
        <ArrowRight className="h-4 w-4" />
      </Link>
    </article>
  );
}

function TrumpDisclosureCard({
  disclosure,
  disclosureLoading,
  disclosureError,
  secExactCount,
  ogeRangeCount,
  holdings,
  locale
}: {
  disclosure?: DisclosureSummary;
  disclosureLoading: boolean;
  disclosureError: unknown;
  secExactCount: number;
  ogeRangeCount: number;
  holdings: DisclosedHolding[];
  locale: Locale;
}) {
  const isKo = locale === "ko";
  return (
    <article className="panel min-w-0 border-warning/50 p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-warning">
            <FileText className="h-4 w-4" />
            {isKo ? "신뢰 구간 공시 노출" : "Disclosure confidence interval"}
          </div>
          <h2 className="safe-text mt-3 text-2xl font-bold">
            {isKo ? "Donald J. Trump 공개 노출" : "Donald J. Trump public exposure"}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label={isKo ? "실시간 아님" : "not real-time"} />
          <SourceBadge label={isKo ? "실제 포트폴리오 아님" : "not actual portfolio"} />
        </div>
      </div>
      <p className="safe-text mt-4 text-sm font-semibold leading-6 text-warning">
        {isKo
          ? "정확 추적이 아니라 공개 파일링 기반 범위입니다. 행마다 원문을 확인해야 합니다."
          : "This is a range-based public-filing approximation, not exact tracking. Every row must be read with the source filing."}
      </p>
      {disclosureLoading ? <p className="mt-4 text-sm text-muted">{isKo ? "불러오는 중..." : "Loading..."}</p> : null}
      {disclosureError ? (
        <p className="safe-text mt-4 rounded-md border border-line bg-panelAlt p-3 text-sm leading-6 text-muted">
          {isKo ? "공시 API를 읽지 못했습니다. 상세 탭에서 스냅샷 대체 정보를 확인하세요." : "Could not load the disclosure API. The detail tab still shows static fallback context."}
        </p>
      ) : null}
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Metric label={isKo ? "SEC 보유량 행" : "SEC holding rows"} value={String(secExactCount)} termKey="complete_data" />
        <Metric label={isKo ? "OGE 범위 행" : "OGE range rows"} value={String(ogeRangeCount)} termKey="estimated_data" />
        <Metric label={isKo ? "검토 대기" : "Review queue"} value={String(disclosure?.open_review_items ?? 0)} termKey="data_quality" />
      </div>
      <div className="mt-5 grid gap-2">
        {holdings.slice(0, 5).map((holding) => (
          <SafeExternalAnchor
            key={holding.key}
            className="focus-ring grid min-h-11 grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent"
            href={holding.source_url}
          >
            <div className="min-w-0">
              <div className="safe-text text-xs font-semibold uppercase leading-5 text-muted">{holding.date}</div>
              <div className="safe-text text-sm font-bold">{holding.ticker} · {holding.owner}</div>
              <div className="safe-text text-xs leading-5 text-muted">{holding.issuer}</div>
            </div>
            <div className="text-right text-sm font-semibold">{formatNumber(holding.shares)} sh</div>
          </SafeExternalAnchor>
        ))}
        {!holdings.length ? (
          <div className="rounded-md border border-dashed border-line p-4 text-sm leading-6 text-muted">
            {isKo ? "공개 보유량으로 집계할 SEC 거래 후 보유 행이 아직 없습니다." : "No SEC post-transaction holding rows are currently available for roll-up."}
          </div>
        ) : null}
      </div>
      <Link className="secondary-action mt-5 min-h-11 px-3 py-2" to="/$locale/trump-filings" params={{ locale }}>
        {isKo ? "원문 공시 행 보기" : "Open source-linked disclosures"}
        <ExternalLink className="h-4 w-4" />
      </Link>
    </article>
  );
}

function Metric({ label, value, termKey }: { label: string; value: string; termKey?: string }) {
  return (
    <div className="rounded-md border border-line bg-panelAlt p-3">
      <div className="flex items-center gap-1 text-xs font-semibold uppercase text-muted">
        {label}
        {termKey ? <TermTooltip termKey={termKey} /> : null}
      </div>
      <div className="safe-text mt-1 text-xl font-bold">{value}</div>
    </div>
  );
}

function SafeExternalAnchor({ href, className, children }: { href: string; className: string; children: ReactNode }) {
  const safeHref = safeExternalHref(href);
  if (!safeHref) {
    return (
      <div className={`${className} cursor-not-allowed opacity-80`} aria-disabled="true">
        {children}
      </div>
    );
  }
  return (
    <a className={className} href={safeHref} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function LimitTile({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <article className="min-w-0 rounded-md border border-line bg-panelAlt p-4">
      <div className="safe-text text-xs font-semibold uppercase leading-5 text-muted">{title}</div>
      <h3 className="safe-text mt-1 text-base font-bold leading-6">{value}</h3>
      <p className="safe-text mt-2 text-xs leading-5 text-muted">{detail}</p>
    </article>
  );
}

interface DisclosedHolding {
  key: string;
  owner: string;
  issuer: string;
  ticker: string;
  shares: number;
  date: string;
  source_url: string;
  sort_key: string;
}

function latestDisclosedHoldings(transactions: DisclosureTransaction[]): DisclosedHolding[] {
  const holdings = new Map<string, DisclosedHolding>();
  for (const transaction of transactions) {
    if (transaction.source !== "SEC" || transaction.post_transaction_shares == null) continue;
    const owner = transaction.owner_name || transaction.person_name;
    const ticker = transaction.ticker;
    const issuer = transaction.issuer_name || transaction.asset_description;
    if (!owner || !ticker || !issuer) continue;
    const date = transaction.transaction_date || transaction.doc_date || formatDateTime(transaction.filed_at || "");
    const key = `${owner}|${ticker}|${issuer}`;
    const sortKey = `${date || ""}|${transaction.id}`;
    const current = holdings.get(key);
    if (current && current.sort_key >= sortKey) continue;
    holdings.set(key, {
      key,
      owner,
      issuer,
      ticker,
      shares: transaction.post_transaction_shares,
      date: date || "date pending",
      source_url: transaction.source_url,
      sort_key: sortKey
    });
  }
  return [...holdings.values()].sort((a, b) => b.sort_key.localeCompare(a.sort_key));
}

function safeExternalHref(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().slice(0, 10);
}

function formatUsd(value: number) {
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${formatNumber(value)}`;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(value >= 0.1 ? 1 : 2)}%`;
}
