import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalItem } from "@frw/shared-types";
import { SeverityBadge, SourceBadge } from "../components/Badge";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function TrumpFilingsPage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["snapshot", "trump-filings", locale],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const lane = query.data.data.alternative_signals.find((item) => item.key === "trump_filings");
  const summaryItem = lane?.items.find((item) => item.key.endsWith("_ai_summary"));
  const filingItems = lane?.items.filter((item) => !item.key.endsWith("_ai_summary")) ?? [];

  return (
    <div className="grid min-w-0 gap-7">
      <SnapshotBanner snapshot={query.data} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-3xl font-bold leading-tight">
            <FileText className="h-6 w-6 text-accent" />
            {t("trumpFilings")}
          </h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted">
            {locale === "ko"
              ? "추적 중인 트럼프 관련 공개 엔티티의 SEC 공시와 엔티티 주의사항을 한 탭에 모읍니다."
              : "SEC filing digest and entity caveats for tracked Trump-related public entities, without sending users off-site first."}
          </p>
        </div>
        {lane ? <SourceBadge label={lane.cadence} /> : null}
      </section>

      {lane ? (
        <section className="panel p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold leading-5 text-muted">{lane.title}</h2>
              <div className="mt-1 text-2xl font-bold">{lane.value}</div>
            </div>
            <SeverityBadge value={lane.severity} />
          </div>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted">{lane.summary}</p>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {filingItems.map((item) => (
              <FilingCard key={item.key} item={item} locale={locale} />
            ))}
          </div>
        </section>
      ) : null}

      {summaryItem ? (
        <section className="panel p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <Sparkles className="h-4 w-4" />
            {summaryItem.label}
          </div>
          <p className="mt-2 text-sm leading-6 text-muted">{summaryItem.detail}</p>
          <div className="mt-3">
            <SeverityBadge value={summaryItem.severity} />
          </div>
        </section>
      ) : null}
    </div>
  );
}

function FilingCard({ item, locale }: { item: AlternativeSignalItem; locale: "en" | "ko" }) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-sm font-semibold leading-5">{item.label}</h3>
        <div className="shrink-0 text-xs font-semibold leading-5 text-accent">{item.value}</div>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted">{item.detail}</p>
      {item.source_url ? (
        <div className="mt-3 flex items-center gap-1 text-xs font-semibold leading-5 text-accent">
          {locale === "ko" ? "출처" : "Source"}
          <ExternalLink className="h-3.5 w-3.5" />
        </div>
      ) : null}
    </>
  );
  const className = "focus-ring block min-h-[160px] rounded-md border border-line bg-panelAlt p-4 hover:border-accent";
  if (item.source_url) {
    return (
      <a className={className} href={item.source_url} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <article className={className}>{content}</article>;
}
