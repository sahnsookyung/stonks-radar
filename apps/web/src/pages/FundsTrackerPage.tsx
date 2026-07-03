import { Database, ExternalLink, Search } from "lucide-react";
import type { ReactNode } from "react";
import { SourceBadge } from "../components/Badge";
import { fundLinks, type FundLinkEntry } from "../lib/fundLinks";
import { useLocale } from "../lib/locale";

export function FundsTrackerPage() {
  const locale = useLocale();
  const isKo = locale === "ko";

  return (
    <div className="grid min-w-0 gap-7">
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <Database className="h-4 w-4" />
            {isKo ? "공개 펀드 링크 디렉터리" : "Public fund links directory"}
          </div>
          <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">
            Funds Tracker
          </h1>
          <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
            {isKo
              ? "지연된 13F 및 공개 공시 기반 외부 트래커로 이동하는 출처 링크 디렉터리입니다. 실시간 포트폴리오나 투자 복제 도구가 아닙니다."
              : "A source-linked directory to delayed 13F and public-filing trackers. This is not a live portfolio feed or a copy-trading product."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SourceBadge label={isKo ? "외부 링크 전용" : "outbound links only"} />
          <SourceBadge label={isKo ? "수집/스크래핑 없음" : "no scraping"} />
          <SourceBadge label={isKo ? "지연 공시" : "delayed filings"} />
        </div>
      </section>

      <section className="signal-warning p-4">
        <div className="flex items-start gap-3">
          <Search className="mt-1 h-4 w-4 shrink-0" />
          <p className="safe-text text-sm leading-6">
            {isKo
              ? "아래 링크는 외부 리서치 화면으로 이동합니다. Stonks Radar는 HedgeFollow 표를 복사하거나 수집하지 않으며, 각 외부 사이트의 지연/범위/계산 방식을 별도로 확인해야 합니다."
              : "These links open external research pages. Stonks Radar does not copy or ingest HedgeFollow tables; verify each external site's filing lag, coverage, and calculation policy."}
          </p>
        </div>
      </section>

      <section className="panel min-w-0 p-5">
        <div className="mb-4 flex min-w-0 flex-wrap items-center justify-between gap-3">
          <h2 className="safe-text text-lg font-bold">
            {isKo ? "큐레이션된 펀드 링크" : "Curated fund links"}
          </h2>
          <span className="badge border-line bg-panelAlt text-muted">
            {fundLinks.length} {isKo ? "개 링크" : "links"}
          </span>
        </div>

        <div className="grid gap-3 md:hidden">
          {fundLinks.map((entry) => (
            <FundLinkCard key={entry.key} entry={entry} locale={locale} />
          ))}
        </div>

        <div className="hidden overflow-x-auto rounded-md border border-line md:block" data-allow-horizontal-scroll aria-label={isKo ? "펀드 링크 표" : "fund links table"}>
          <table className="min-w-[920px] w-full text-left text-sm">
            <thead className="bg-panelAlt text-xs uppercase text-muted">
              <tr>
                <th className="px-3 py-3">{isKo ? "사람 / 매니저" : "Human / manager"}</th>
                <th className="px-3 py-3">{isKo ? "펀드" : "Fund"}</th>
                <th className="px-3 py-3">{isKo ? "주요 트래커" : "Primary tracker"}</th>
                <th className="px-3 py-3">{isKo ? "출처 유형" : "Source type"}</th>
                <th className="px-3 py-3">{isKo ? "메모" : "Notes"}</th>
              </tr>
            </thead>
            <tbody>
              {fundLinks.map((entry) => (
                <tr key={entry.key} className="border-t border-line">
                  <td className="safe-text px-3 py-3 font-semibold">{entry.human_name}</td>
                  <td className="safe-text px-3 py-3">{entry.fund_name}</td>
                  <td className="px-3 py-3">
                    <SafeExternalAnchor
                      className="focus-ring inline-flex min-h-11 items-center gap-2 font-semibold text-accent hover:text-ink"
                      href={entry.primary_url}
                    >
                      {entry.source_label}
                      <ExternalLink className="h-4 w-4" />
                    </SafeExternalAnchor>
                  </td>
                  <td className="px-3 py-3 text-muted">
                    {isKo ? "외부 13F 트래커" : "External 13F tracker"}
                  </td>
                  <td className="safe-text px-3 py-3 text-muted">{entry.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function FundLinkCard({ entry, locale }: Readonly<{ entry: FundLinkEntry; locale: "en" | "ko" }>) {
  const isKo = locale === "ko";
  return (
    <article className="grid gap-3 rounded-md border border-line bg-panelAlt p-4">
      <div className="min-w-0">
        <div className="safe-text text-base font-bold">{entry.human_name}</div>
        <div className="safe-text mt-1 text-sm leading-6 text-muted">{entry.fund_name}</div>
      </div>
      <div className="flex flex-wrap gap-2">
        <span className="badge border-line bg-panel text-muted">{entry.source_label}</span>
        <span className="badge border-line bg-panel text-muted">
          {isKo ? "외부 13F 트래커" : "External 13F tracker"}
        </span>
      </div>
      <p className="safe-text text-sm leading-6 text-muted">{entry.note}</p>
      <SafeExternalAnchor
        className="secondary-action min-h-11 px-3 py-2"
        href={entry.primary_url}
      >
        {isKo ? `${entry.source_label}에서 열기` : `Open ${entry.source_label}`}
        <ExternalLink className="h-4 w-4" />
      </SafeExternalAnchor>
    </article>
  );
}

function SafeExternalAnchor({ href, className, children }: Readonly<{ href: string; className: string; children: ReactNode }>) {
  const safeHref = safeExternalHref(href);
  if (!safeHref) {
    return (
      <span className={`${className} cursor-not-allowed opacity-80`} aria-disabled="true">
        {children}
      </span>
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
