import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, Database, ExternalLink, FileSpreadsheet } from "lucide-react";
import type { ReactNode } from "react";
import { SourceBadge } from "../components/Badge";
import { getFundLinkByKey } from "../lib/fundLinks";
import { useLocale } from "../lib/locale";

export function FundPortfolioPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = useParams({ strict: false }) as { fundKey?: string };
  const entry = getFundLinkByKey(params.fundKey ?? "situational-awareness");

  return (
    <div className="grid min-w-0 gap-6">
      <section className="panel p-5">
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
              <FileSpreadsheet className="h-4 w-4" />
              {isKo ? "외부 펀드 트래커" : "External fund tracker"}
            </div>
            <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl">
              {entry?.fund_name ?? (isKo ? "펀드 링크" : "Fund link")}
            </h1>
            <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted">
              {isKo
                ? "이전 내부 13F 포트폴리오 화면은 정확도 혼선을 피하기 위해 외부 링크 디렉터리로 대체되었습니다."
                : "The previous internal 13F portfolio view has been replaced by the external links directory to avoid implying a precise live portfolio representation."}
            </p>
            <div className="mt-4 flex min-w-0 flex-wrap gap-2">
              <SourceBadge label={isKo ? "외부 링크 전용" : "outbound links only"} />
              <SourceBadge label={isKo ? "실시간 아님" : "not realtime"} />
              <SourceBadge label={isKo ? "스크래핑 없음" : "no scraping"} />
            </div>
          </div>
          <div className="flex min-w-[240px] flex-wrap content-start gap-2">
            <Link className="secondary-action min-h-11 px-3 py-2" to="/$locale/funds" params={{ locale }}>
              <ArrowLeft className="h-4 w-4" />
              {isKo ? "펀드 디렉터리" : "Funds directory"}
            </Link>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(340px,0.45fr)]">
        <article className="panel min-w-0 p-5">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
            <Database className="h-4 w-4" />
            {isKo ? "추천 외부 링크" : "Recommended external link"}
          </div>
          {entry ? (
            <div className="mt-4 grid gap-4">
              <div>
                <h2 className="safe-text text-2xl font-bold">{entry.human_name}</h2>
                <p className="safe-text mt-1 text-sm leading-6 text-muted">{entry.fund_name}</p>
              </div>
              <p className="safe-text text-sm leading-6 text-muted">{entry.note}</p>
              <SafeExternalAnchor className="secondary-action min-h-11 px-3 py-2" href={entry.primary_url}>
                {isKo ? "HedgeFollow에서 열기" : `Open ${entry.source_label}`}
                <ExternalLink className="h-4 w-4" />
              </SafeExternalAnchor>
            </div>
          ) : (
            <div className="mt-4 rounded-md border border-dashed border-line p-4 text-sm leading-6 text-muted">
              {isKo
                ? "이 펀드 키에 대한 큐레이션 링크가 없습니다. 전체 디렉터리에서 사용 가능한 링크를 확인하세요."
                : "No curated link exists for this fund key. Use the full directory to browse available links."}
            </div>
          )}
        </article>

        <aside className="signal-warning p-4">
          <p className="safe-text text-sm leading-6">
            {isKo
              ? "Stonks Radar는 외부 펀드 테이블을 복사하지 않습니다. 13F 지연, 옵션 표시 방식, AUM 계산 방식은 외부 사이트에서 확인하세요."
              : "Stonks Radar does not copy external fund tables. Check the external site for 13F lag, options treatment, and AUM methodology."}
          </p>
        </aside>
      </section>
    </div>
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
