import { useQuery } from "@tanstack/react-query";
import { Database, ExternalLink, FileText } from "lucide-react";
import { getTickerFundamentals, type FundamentalMetrics } from "../../lib/tickerApi";
import type { TrackedTicker } from "../../lib/trackedTickers";

export function TickerFundamentalsPanel({ ticker, locale }: Readonly<{ ticker: TrackedTicker; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  const query = useQuery({
    queryKey: ["ticker-fundamentals", ticker.symbol],
    queryFn: ({ signal }) => getTickerFundamentals(ticker.symbol, signal),
    staleTime: 15 * 60_000,
    retry: 1
  });
  const payload = query.data;
  const status = query.isLoading ? "loading" : query.isError ? "provider_error" : payload?.status ?? "unavailable";
  const fields = fundamentalFields(payload?.metrics, locale);

  return (
    <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]" aria-labelledby="ticker-fundamentals-heading">
      <div className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionTitle
            id="ticker-fundamentals-heading"
            icon={<Database className="h-5 w-5" />}
            title={isKo ? "공식 펀더멘털" : "Official Fundamentals"}
            subtitle={isKo ? "SEC CompanyFacts에서 예약 작업으로 정규화한 값입니다." : "Normalized by scheduled jobs from official SEC CompanyFacts."}
          />
          <StateBadge status={status} locale={locale} />
        </div>

        {status === "loading" ? <StateMessage text={isKo ? "공식 지표를 불러오는 중입니다." : "Loading official metrics."} /> : null}
        {status === "provider_error" ? <StateMessage tone="danger" text={isKo ? "펀더멘털 API를 읽지 못했습니다. 잠시 후 다시 시도하세요." : "The fundamentals API is unavailable. Try again shortly."} /> : null}
        {status === "unavailable" ? (
          <StateMessage text={coverageReason(payload?.coverage_reason, locale)} />
        ) : null}
        {status === "ready" || status === "stale" ? (
          <>
            {status === "stale" ? (
              <StateMessage tone="warning" text={isKo ? "새 SEC 제출을 기다리는 오래된 공식 값입니다." : "These official values are stale while the next SEC refresh is pending."} />
            ) : null}
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {fields.map((field) => (
                <article key={field.key} className="rounded-md border border-line bg-panelAlt p-4">
                  <div className="text-xs font-semibold uppercase leading-5 text-muted">{field.label}</div>
                  <div className="mt-2 text-2xl font-bold leading-tight">{field.value}</div>
                  <p className="mt-2 text-xs leading-5 text-muted">{field.detail}</p>
                </article>
              ))}
            </div>
          </>
        ) : null}
      </div>

      <aside className="panel p-5" aria-labelledby="ticker-fundamentals-source-heading">
        <SectionTitle
          id="ticker-fundamentals-source-heading"
          icon={<FileText className="h-5 w-5" />}
          title={isKo ? "기간과 출처" : "Period and Source"}
          subtitle={isKo ? "누락값은 추정하지 않습니다." : "Missing values are never fabricated."}
        />
        <dl className="mt-4 grid gap-3 text-sm leading-6">
          <Meta label={isKo ? "상태" : "Status"} value={status.replace("_", " ")} />
          <Meta label={isKo ? "기간" : "Period"} value={payload?.period_end ?? (isKo ? "없음" : "Unavailable")} />
          <Meta label={isKo ? "양식" : "Form"} value={payload?.form ?? (isKo ? "없음" : "Unavailable")} />
          <Meta label={isKo ? "제출 시각" : "Filed"} value={formatDate(payload?.source_filed_at, locale)} />
          <Meta label={isKo ? "수집 시각" : "Fetched"} value={formatDate(payload?.fetched_at, locale)} />
        </dl>
        {payload?.filing_url ? (
          <a className="secondary-action mt-4" href={payload.filing_url} target="_blank" rel="noreferrer">
            <ExternalLink className="h-4 w-4" />
            {isKo ? "SEC 원문" : "SEC source"}
          </a>
        ) : null}
      </aside>
    </section>
  );
}

function fundamentalFields(metrics: FundamentalMetrics | undefined, locale: "en" | "ko") {
  const isKo = locale === "ko";
  const rows: Array<[keyof FundamentalMetrics, string, "money" | "percent" | "number"]> = [
    ["revenue", isKo ? "매출" : "Revenue", "money"],
    ["revenue_growth", isKo ? "매출 성장률" : "Revenue growth", "percent"],
    ["operating_margin", isKo ? "영업이익률" : "Operating margin", "percent"],
    ["net_margin", isKo ? "순이익률" : "Net margin", "percent"],
    ["net_income", isKo ? "순이익" : "Net income", "money"],
    ["free_cash_flow", isKo ? "잉여현금흐름" : "Free cash flow", "money"],
    ["cash", isKo ? "현금" : "Cash", "money"],
    ["debt", isKo ? "부채" : "Debt", "money"],
    ["shares", isKo ? "발행주식수" : "Shares outstanding", "number"],
    ["dilution", isKo ? "희석률" : "Dilution", "percent"]
  ];
  return rows.map(([key, label, kind]) => {
    const value = metrics?.[key];
    const reason = metrics?.missing_reasons?.[String(key)];
    return {
      key,
      label,
      value: formatMetric(typeof value === "number" ? value : null, kind, locale),
      detail: reason || (isKo ? "공식 제출 기준" : "Official filing basis")
    };
  });
}

function formatMetric(value: number | null, kind: "money" | "percent" | "number", locale: "en" | "ko") {
  if (value == null || !Number.isFinite(value)) return locale === "ko" ? "없음" : "Unavailable";
  if (kind === "percent") return `${(Math.abs(value) <= 2 ? value * 100 : value).toFixed(1)}%`;
  return new Intl.NumberFormat(locale === "ko" ? "ko-KR" : "en-US", {
    notation: "compact",
    style: kind === "money" ? "currency" : "decimal",
    currency: kind === "money" ? "USD" : undefined,
    maximumFractionDigits: 2
  }).format(value);
}

function coverageReason(reason: string | null | undefined, locale: "en" | "ko") {
  if (reason === "issuer_not_cik_backed") return locale === "ko" ? "CIK가 연결된 미국 발행사가 아니어서 SEC CompanyFacts 범위 밖입니다." : "This issuer is outside SEC CompanyFacts coverage because no CIK is linked.";
  if (reason === "no_compatible_companyfacts") return locale === "ko" ? "호환되는 SEC CompanyFacts 개념이 없습니다." : "No compatible SEC CompanyFacts concepts are available.";
  return locale === "ko" ? "공식 펀더멘털 스냅샷이 아직 없습니다." : "No official fundamentals snapshot is available yet.";
}

function StateBadge({ status, locale }: Readonly<{ status: string; locale: "en" | "ko" }>) {
  const labels: Record<string, [string, string]> = {
    loading: ["Loading", "로딩"],
    ready: ["Ready", "준비"],
    stale: ["Stale", "오래됨"],
    unavailable: ["Unsupported", "미지원"],
    provider_error: ["Error", "오류"]
  };
  const label = labels[status] ?? [status, status];
  return <span className="badge border-line bg-panelAlt text-muted">{locale === "ko" ? label[1] : label[0]}</span>;
}

function StateMessage({ text, tone = "muted" }: Readonly<{ text: string; tone?: "muted" | "warning" | "danger" }>) {
  const className = tone === "danger" ? "signal-danger" : tone === "warning" ? "signal-warning" : "border-line bg-panelAlt text-muted";
  return <div className={`mt-4 rounded-md border p-4 text-sm leading-6 ${className}`}>{text}</div>;
}

function SectionTitle({ id, icon, title, subtitle }: Readonly<{ id: string; icon: React.ReactNode; title: string; subtitle: string }>) {
  return (
    <div className="min-w-0">
      <h2 id={id} className="flex items-center gap-2 text-lg font-bold leading-7"><span className="text-accent">{icon}</span>{title}</h2>
      <p className="mt-1 text-sm leading-6 text-muted">{subtitle}</p>
    </div>
  );
}

function Meta({ label, value }: Readonly<{ label: string; value: string }>) {
  return <div><dt className="text-xs font-semibold uppercase text-muted">{label}</dt><dd className="mt-1 break-words font-semibold">{value}</dd></div>;
}

function formatDate(value: string | null | undefined, locale: "en" | "ko") {
  if (!value) return locale === "ko" ? "없음" : "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale === "ko" ? "ko-KR" : "en-US");
}
