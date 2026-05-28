import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ExternalLink, Radar, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalItem, AlternativeSignalLane } from "@frw/shared-types";
import { SeverityBadge, SourceBadge } from "../components/Badge";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

const shortLaneKeys = new Set(["highest_short_interest", "short_volume_monitor"]);
const trackedShortSymbols = ["DJT", "TSLA", "NVDA"];

export function ShortsPage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: ["snapshot", "shorts", locale],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const lanes = query.data.data.alternative_signals;
  const shortLanes = lanes.filter((lane) => shortLaneKeys.has(lane.key));
  const researchLane = lanes.find((lane) => lane.key === "short_research_reports");
  const tickerRows = trackedShortSymbols.map((symbol) => ({
    symbol,
    items: shortLanes.flatMap((lane) =>
      lane.items.filter((item) => item.label.toUpperCase().startsWith(`${symbol} `)).map((item) => ({ lane, item }))
    )
  }));

  return (
    <div className="grid min-w-0 gap-7">
      <SnapshotBanner snapshot={query.data} />
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-3xl font-bold leading-tight">
            <Radar className="h-6 w-6 text-accent" />
            {t("shorts")}
          </h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted">
            {locale === "ko"
              ? "추적 티커별 FINRA 공매도 잔고와 일별 공매도 거래량, 공개 숏 리서치 출처를 한 곳에서 봅니다."
              : "Ticker-level FINRA short interest, daily short-volume flow, and public short-research sources in one place."}
          </p>
        </div>
        <SourceBadge label={locale === "ko" ? "15분 이하 소스 점검 목표" : "15m-or-slower source checks"} />
      </section>

      <section className="grid gap-3 md:grid-cols-3" aria-label={locale === "ko" ? "티커별 공매도" : "Ticker shorts"}>
        {tickerRows.map((row) => (
          <article key={row.symbol} className="panel flex min-h-[260px] flex-col p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase leading-5 text-muted">
                  {locale === "ko" ? "추적 티커" : "Tracked ticker"}
                </div>
                <Link
                  to="/$locale/tickers/$symbol"
                  params={{ locale, symbol: row.symbol }}
                className="focus-ring mt-1 inline-flex min-h-11 items-center rounded-md text-2xl font-bold hover:text-accent"
                >
                  {row.symbol}
                </Link>
              </div>
              <SeverityBadge value="medium" />
            </div>
            <div className="mt-4 grid gap-2">
              {row.items.length ? (
                row.items.map(({ lane, item }) => <SignalItem key={item.key} item={item} context={lane.title} />)
              ) : (
                  <div className="safe-text min-h-11 rounded-md border border-line bg-panelAlt px-3 py-2 text-xs leading-5 text-muted">
                  {locale === "ko"
                    ? "이번 스냅샷에는 이 티커의 공식 공매도 행이 없습니다."
                    : "No official short row for this ticker in the current snapshot."}
                </div>
              )}
            </div>
          </article>
        ))}
      </section>

      <section className="grid gap-3 lg:grid-cols-[0.42fr_0.58fr]">
        <LaneCard lane={shortLanes.find((lane) => lane.key === "highest_short_interest")} />
        <LaneCard lane={shortLanes.find((lane) => lane.key === "short_volume_monitor")} />
      </section>

      {researchLane ? (
        <section aria-labelledby="short-research-title">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-warning">
            <Search className="h-4 w-4" />
            <h2 id="short-research-title">{researchLane.title}</h2>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {researchLane.items.map((item) => (
              <SignalItem key={item.key} item={item} context={researchLane.cadence} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function LaneCard({ lane }: { lane?: AlternativeSignalLane }) {
  if (!lane) return null;
  return (
    <article className="panel flex min-h-[260px] min-w-0 flex-col p-4 sm:min-h-[280px]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="safe-text text-sm font-semibold leading-5">{lane.title}</h2>
          <div className="safe-text mt-1 text-xl font-bold leading-7">{lane.value}</div>
        </div>
        <SeverityBadge value={lane.severity} />
      </div>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">{lane.summary}</p>
      <div className="mt-4 grid gap-2">
        {lane.items.slice(0, 6).map((item) => (
          <SignalItem key={item.key} item={item} context={lane.cadence} />
        ))}
      </div>
    </article>
  );
}

function SignalItem({ item, context }: { item: AlternativeSignalItem; context: string }) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <div className="safe-text min-w-0 text-sm font-semibold leading-5 text-ink">{item.label}</div>
        <div className="safe-text max-w-[45%] shrink-0 text-right text-xs font-semibold leading-5 text-accent">{item.value}</div>
      </div>
      <p className="safe-text mt-1 text-xs leading-5 text-muted">{item.detail}</p>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] leading-4 text-muted">
        <span className="safe-text min-w-0">{context}</span>
        {item.source_url ? <ExternalLink className="h-3.5 w-3.5 text-accent" /> : null}
      </div>
    </>
  );
  const className = "focus-ring min-h-11 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent";
  if (item.source_url) {
    return (
      <a className={className} href={item.source_url} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <div className={className}>{content}</div>;
}
