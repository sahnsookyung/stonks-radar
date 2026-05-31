import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Database,
  ExternalLink,
  FileSpreadsheet,
  PieChart,
  Table2,
} from "lucide-react";
import type { FundPortfolioHolding, FundHoldingKind } from "@frw/shared-types";
import type { ReactNode } from "react";
import { EntityLink } from "../components/EntityLink";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

type HoldingFilter = "stocks" | "options" | "all";

const filterLabels: Record<HoldingFilter, { en: string; ko: string }> = {
  stocks: { en: "Stocks", ko: "주식" },
  options: { en: "Options", ko: "옵션" },
  all: { en: "All rows", ko: "전체" },
};

export function FundPortfolioPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = useParams({ strict: false }) as { fundKey?: string };
  const fundKey = params.fundKey ?? "situational-awareness";
  const [filter, setFilter] = useState<HoldingFilter>("stocks");
  const query = useQuery({
    queryKey: ["snapshot", "fund-portfolio", fundKey, locale],
    queryFn: () => snapshotQueries.fundPortfolio(fundKey, locale),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const data = query.data.data;
  const holdings =
    filter === "stocks"
      ? data.holdings.filter((holding) => holding.holding_kind === "stock")
      : filter === "options"
        ? data.option_holdings
        : data.holdings;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />

      <section className="panel p-5">
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
              <FileSpreadsheet className="h-4 w-4" />
              {isKo ? "공개 13F 포트폴리오" : "Public 13F portfolio"}
            </div>
            <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl">
              {data.display_name}
            </h1>
            <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted">
              {isKo
                ? `${data.fund_name}의 SEC 13F XML 정보표를 기반으로 한 출처 연결형 스냅샷입니다. HedgeFollow HTML은 자동 수집하지 않습니다.`
                : `A source-linked snapshot built from the SEC 13F XML information table for ${data.fund_name}. HedgeFollow HTML is not scraped in production.`}
            </p>
            <div className="mt-4 flex min-w-0 flex-wrap gap-2">
              <Badge>{data.manager_name}</Badge>
              <Badge>CIK {data.cik}</Badge>
              <Badge>{data.source_strength}</Badge>
              {data.filing ? <Badge>{data.filing.report_date}</Badge> : null}
            </div>
          </div>
          <div className="grid min-w-[260px] gap-2 sm:grid-cols-2 xl:min-w-[520px]">
            <Metric
              label={isKo ? "롱 주식" : "Long equity"}
              value={formatUsd(data.summary_metrics.long_equity_value_usd)}
            />
            <Metric
              label={isKo ? "옵션 공시가" : "Option value"}
              value={formatUsd(data.summary_metrics.option_notional_value_usd)}
            />
            <Metric
              label={isKo ? "보유 행" : "Rows"}
              value={String(data.summary_metrics.holding_count)}
            />
            <Metric
              label={isKo ? "공시일" : "Filed"}
              value={data.filing?.filed_at ?? "pending"}
            />
          </div>
        </div>
      </section>

      <section className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
        <div className="panel min-w-0 p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-bold">
              <PieChart className="h-5 w-5 text-accent" />
              {isKo ? "상위 롱 주식 비중" : "Top long-equity allocation"}
            </h2>
            {data.filing ? (
              <a
                className="secondary-action min-h-11 px-3 py-2"
                href={data.filing.information_table_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-4 w-4" />
                SEC XML
              </a>
            ) : null}
          </div>
          {data.top_equity_holdings.length ? (
            <AllocationGrid holdings={data.top_equity_holdings.slice(0, 14)} />
          ) : (
            <EmptyState
              text={
                isKo
                  ? "13F 보유 행을 아직 가져오지 못했습니다."
                  : "No 13F holding rows are available yet."
              }
            />
          )}
        </div>

        <aside className="grid content-start gap-4">
          <section className="panel p-5">
            <h2 className="flex items-center gap-2 text-lg font-bold">
              <Database className="h-5 w-5 text-accent" />
              {isKo ? "출처와 한계" : "Source and limits"}
            </h2>
            <div className="mt-4 grid gap-2 text-sm leading-6 text-muted">
              {data.caveats.map((caveat) => (
                <p
                  key={caveat}
                  className="safe-text rounded-md border border-line bg-panelAlt px-3 py-2"
                >
                  {caveat}
                </p>
              ))}
            </div>
          </section>
          <section className="signal-warning p-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-1 h-4 w-4 shrink-0" />
              <p className="safe-text text-sm leading-6">
                {isKo
                  ? "13F는 투자 아이디어 복제 도구가 아니라 공개 공시 리서치 화면입니다. 분기 지연과 누락 범위를 항상 함께 읽어야 합니다."
                  : "This is a public-filing research view, not a copy-trading tool. Read every row with quarterly lag and reporting-scope gaps in mind."}
              </p>
            </div>
          </section>
        </aside>
      </section>

      <section className="panel min-w-0 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-bold">
            <Table2 className="h-5 w-5 text-accent" />
            {isKo ? "13F 행" : "13F rows"}
          </h2>
          <div
            className="flex rounded-md border border-line bg-panelAlt p-1"
            role="tablist"
            aria-label={isKo ? "보유 필터" : "Holding filter"}
          >
            {(Object.keys(filterLabels) as HoldingFilter[]).map((key) => (
              <button
                key={key}
                type="button"
                className={`min-h-11 rounded px-3 text-sm font-semibold ${filter === key ? "bg-accentSoft text-accent" : "text-muted hover:text-ink"}`}
                aria-selected={filter === key}
                role="tab"
                onClick={() => setFilter(key)}
              >
                {filterLabels[key][locale]}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-4 grid gap-2 md:hidden">
          {holdings.map((holding) => (
            <HoldingCard key={holding.id} holding={holding} locale={locale} />
          ))}
        </div>
        <div
          className="mt-4 hidden overflow-x-auto rounded-md border border-line md:block"
          data-allow-horizontal-scroll
        >
          <table className="min-w-[900px] w-full text-left text-sm">
            <thead className="bg-panelAlt text-xs uppercase text-muted">
              <tr>
                <th className="px-3 py-3">{isKo ? "티커" : "Ticker"}</th>
                <th className="px-3 py-3">{isKo ? "발행사" : "Issuer"}</th>
                <th className="px-3 py-3">{isKo ? "종류" : "Type"}</th>
                <th className="px-3 py-3 text-right">
                  {isKo ? "가치" : "Value"}
                </th>
                <th className="px-3 py-3 text-right">
                  {isKo ? "주식 수" : "Shares"}
                </th>
                <th className="px-3 py-3 text-right">
                  {isKo ? "비중" : "Weight"}
                </th>
                <th className="px-3 py-3">CUSIP</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((holding) => (
                <tr key={holding.id} className="border-t border-line">
                  <td className="px-3 py-3 font-semibold">
                    <TickerCell holding={holding} locale={locale} />
                  </td>
                  <td className="safe-text px-3 py-3">{holding.issuer_name}</td>
                  <td className="px-3 py-3">
                    {holdingKindLabel(holding.holding_kind, locale)}
                  </td>
                  <td className="px-3 py-3 text-right font-semibold">
                    {formatUsd(holding.value_usd)}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {holding.shares ? formatNumber(holding.shares) : "-"}
                  </td>
                  <td className="px-3 py-3 text-right">
                    {formatPercent(holding.portfolio_weight)}
                  </td>
                  <td className="px-3 py-3 text-muted">{holding.cusip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="flex flex-wrap gap-2">
        <Link
          className="secondary-action min-h-11 px-3 py-2"
          to="/$locale/portfolio"
          params={{ locale }}
        >
          {isKo ? "포트폴리오 실험실" : "Portfolio lab"}
        </Link>
        <Link
          className="secondary-action min-h-11 px-3 py-2"
          to="/$locale/trump-filings"
          params={{ locale }}
        >
          {isKo ? "트럼프 공시" : "Trump filings"}
        </Link>
      </section>
    </div>
  );
}

function AllocationGrid({ holdings }: { holdings: FundPortfolioHolding[] }) {
  const total = holdings.reduce((sum, holding) => sum + holding.value_usd, 0);
  return (
    <div className="grid min-h-[360px] grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {holdings.map((holding, index) => {
        const weight = total > 0 ? holding.value_usd / total : 0;
        const rowSpan = index < 2 ? "sm:row-span-2" : "";
        return (
          <a
            key={holding.id}
            className={`focus-ring grid min-h-[96px] rounded-md border border-line bg-success/15 p-3 hover:border-accent ${rowSpan}`}
            href={holding.source_url}
            target="_blank"
            rel="noreferrer"
            style={{ opacity: Math.max(0.42, Math.min(1, 0.5 + weight * 1.8)) }}
          >
            <span className="safe-text text-2xl font-bold leading-tight">
              {holding.symbol ?? compactIssuerName(holding.issuer_name)}
            </span>
            <span className="safe-text text-xs leading-5 text-muted">
              {holding.symbol ? holding.issuer_name : `CUSIP ${holding.cusip}`}
            </span>
            <span className="mt-auto text-sm font-semibold">
              {formatPercent(weight)}
            </span>
          </a>
        );
      })}
    </div>
  );
}

function HoldingCard({
  holding,
  locale,
}: {
  holding: FundPortfolioHolding;
  locale: "en" | "ko";
}) {
  const isKo = locale === "ko";
  return (
    <div className="grid gap-2 rounded-md border border-line bg-panelAlt p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="safe-text text-base font-bold">
            <TickerCell holding={holding} locale={locale} />
          </div>
          <div className="safe-text text-sm leading-6 text-muted">
            {holding.issuer_name}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-bold">
            {formatUsd(holding.value_usd)}
          </div>
          <div className="text-xs text-muted">
            {formatPercent(holding.portfolio_weight)}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-muted">
        <span>{holdingKindLabel(holding.holding_kind, locale)}</span>
        <span>
          {isKo ? "주식 수" : "shares"}{" "}
          {holding.shares ? formatNumber(holding.shares) : "-"}
        </span>
        <span>CUSIP {holding.cusip}</span>
      </div>
      <a
        className="focus-ring inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-accent"
        href={holding.source_url}
        target="_blank"
        rel="noreferrer"
      >
        <ExternalLink className="h-4 w-4" />
        {isKo ? "SEC 원문" : "SEC source"}
      </a>
    </div>
  );
}

function TickerCell({
  holding,
  locale,
}: {
  holding: FundPortfolioHolding;
  locale: "en" | "ko";
}) {
  if (!holding.symbol) return <span>{holding.cusip}</span>;
  return (
    <EntityLink
      value={holding.symbol}
      locale={locale}
      className="focus-ring inline-flex min-h-11 min-w-11 items-center hover:text-accent"
    />
  );
}

function compactIssuerName(value: string) {
  return (
    value
      .replace(
        /\b(CORPORATION|CORP|INCORPORATED|INC|LIMITED|LTD|COMPANY|CO|NEW)\b/gi,
        "",
      )
      .replace(/\s+/g, " ")
      .trim() || value
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panelAlt p-3">
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className="safe-text mt-1 text-xl font-bold">{value}</div>
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="badge border-line bg-panelAlt text-muted">{children}</span>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-line p-4 text-sm leading-6 text-muted">
      {text}
    </div>
  );
}

function holdingKindLabel(kind: FundHoldingKind, locale: "en" | "ko") {
  const labels: Record<FundHoldingKind, { en: string; ko: string }> = {
    stock: { en: "Stock", ko: "주식" },
    call: { en: "Call option", ko: "콜옵션" },
    put: { en: "Put option", ko: "풋옵션" },
    other: { en: "Other", ko: "기타" },
  };
  return labels[kind][locale];
}

function formatUsd(value: number) {
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  return `$${formatNumber(value)}`;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
    value,
  );
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(value >= 0.1 ? 1 : 2)}%`;
}
