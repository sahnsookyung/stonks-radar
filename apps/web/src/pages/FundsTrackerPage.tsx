import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowRight,
  Database,
  FileSpreadsheet,
} from "lucide-react";
import type { ReactNode } from "react";
import type { FundPortfolioSnapshotData, Locale } from "@frw/shared-types";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { LoadingState } from "../components/LoadingState";
import { TermTooltip } from "../components/TermTooltip";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function FundsTrackerPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const fundQuery = useQuery({
    queryKey: ["snapshot", "fund-portfolio", "situational-awareness", locale],
    queryFn: () => snapshotQueries.fundPortfolio("situational-awareness", locale)
  });

  const fundData = fundQuery.data?.data;

  if (fundQuery.isLoading) return <LoadingState />;

  return (
    <div className="grid min-w-0 gap-7">
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <Database className="h-4 w-4" />
            {isKo ? "공개 펀드 및 공시 추적" : "Public funds and disclosure tracker"}
          </div>
          <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">
            Funds Tracker
          </h1>
          <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
            {isKo
              ? "분기 13F 포트폴리오와 최신 Schedule 13G 수익소유 공시를 함께 보는 공개 파일링 화면입니다. 실시간 포트폴리오나 투자 복제 도구가 아닙니다."
              : "A public-filing surface for delayed 13F portfolios plus newer Schedule 13G beneficial-ownership rows. This is not a real-time portfolio, not a live holdings feed, and not a copy-trading product."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label={isKo ? "공개 원문 연결" : "source-linked public filings"} />
          <SourceBadge label={isKo ? "지연 데이터" : "delayed data"} />
          <FreshnessBadge value={fundData?.freshness ?? "watch"} />
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,0.45fr)]">
        <LeopoldFundCard data={fundData} locale={locale} loading={fundQuery.isLoading} error={fundQuery.error} />
        <section className="panel content-start p-5">
          <h2 className="safe-text text-lg font-bold">
            {isKo ? "출처와 한계" : "Source and limits"}
          </h2>
          <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
            {(fundData?.caveats ?? []).map((caveat) => (
              <p key={caveat} className="safe-text rounded-md border border-line bg-panelAlt px-3 py-2">
                {caveat}
              </p>
            ))}
          </div>
        </section>
      </section>
    </div>
  );
}

function LeopoldFundCard({
  data,
  locale,
  loading,
  error
}: Readonly<{
  data?: FundPortfolioSnapshotData;
  locale: Locale;
  loading: boolean;
  error: unknown;
}>) {
  const isKo = locale === "ko";
  return (
    <article className="panel min-w-0 p-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
            <FileSpreadsheet className="h-4 w-4" />
            {isKo ? "공개 펀드 공시" : "Public fund filings"}
          </div>
          <h2 className="safe-text mt-3 text-2xl font-bold">
            {data?.display_name ?? (isKo ? "레오폴드 아셴브레너" : "Leopold Aschenbrenner")}
          </h2>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label="SEC EDGAR 13F" />
          <SourceBadge label="Schedule 13G" />
          <SourceBadge label={isKo ? "분기 지연" : "quarterly lag"} />
        </div>
      </div>
      {loading && <p className="mt-4 text-sm text-muted">{isKo ? "불러오는 중..." : "Loading..."}</p>}
      {Boolean(error) && (
        <p className="safe-text mt-4 rounded-md border border-line bg-panelAlt p-3 text-sm leading-6 text-muted">
          {isKo ? "13F 스냅샷을 읽지 못했습니다." : "Could not load the 13F snapshot."}
        </p>
      )}
      {data && (
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
      )}
      <Link className="secondary-action mt-5 min-h-11 px-3 py-2" to="/$locale/funds/$fundKey" params={{ locale, fundKey: "situational-awareness" }}>
        {isKo ? "13F 상세 보기" : "Open 13F details"}
        <ArrowRight className="h-4 w-4" />
      </Link>
    </article>
  );
}

function Metric({ label, value, termKey }: Readonly<{ label: string; value: string; termKey?: string }>) {
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

function SafeExternalAnchor({ href, className, children }: Readonly<{ href: string; className: string; children: ReactNode }>) {
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

function safeExternalHref(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
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
