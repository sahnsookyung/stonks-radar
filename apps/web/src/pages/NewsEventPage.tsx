import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, FileSearch, Newspaper } from "lucide-react";
import { NewsEventCard, NewsScoreBadge, SourcePill, formatNewsDate, marketDirectionLabel, regionRelationLabel } from "../components/NewsEventCard";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

export function NewsEventPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = useParams({ strict: false }) as { eventId?: string };
  const eventId = params.eventId ?? "";
  const query = useQuery({
    queryKey: ["snapshot", "news-event", eventId, locale],
    queryFn: () => snapshotQueries.newsEvent(eventId, locale),
    enabled: Boolean(eventId),
    retry: false
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const event = query.data.data;

  return (
    <div className="grid min-w-0 gap-5">
      <SnapshotBanner snapshot={query.data} />
      <Link to="/$locale/news" params={{ locale }} className="secondary-action w-fit">
        <ArrowLeft className="h-4 w-4" />
        {isKo ? "뉴스로 돌아가기" : "Back to news"}
      </Link>

      <section className="panel min-w-0 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Newspaper className="h-4 w-4" />
          {event.event_type}
        </div>
        <h1 className="safe-text mt-3 text-3xl font-bold leading-tight sm:text-4xl">{event.title}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{event.one_sentence_summary}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <NewsScoreBadge label={isKo ? "속보" : "Breaking"} value={event.breaking_score} />
          <NewsScoreBadge label={isKo ? "신뢰" : "Trust"} value={event.trust_score} />
          <span className="badge border-line bg-panelAlt text-muted">{event.severity}</span>
          <span className="badge border-line bg-panelAlt text-muted">{Math.round(event.confidence * 100)}%</span>
          <span className="badge border-line bg-panelAlt text-muted">{formatNewsDate(event.last_seen_at)}</span>
        </div>
      </section>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 gap-5">
          <DetailBlock title={isKo ? "무슨 일이 있었나" : "What Happened"} items={event.what_happened} />
          <DetailBlock title={isKo ? "왜 중요한가" : "Why It Matters"} items={event.why_it_matters} />
          <DetailBlock title={isKo ? "확인된 사실" : "Known Facts"} items={event.known_facts} />
          <DetailBlock title={isKo ? "불확실성" : "Uncertainties"} items={event.uncertainties} />
          {event.conflicting_reports.length ? <DetailBlock title={isKo ? "상충 보고" : "Conflicting Reports"} items={event.conflicting_reports} /> : null}
        </div>

        <aside className="grid content-start gap-5">
          <section className="panel p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileSearch className="h-4 w-4 text-accent" />
              {isKo ? "시장 관련성" : "Market Relevance"}
            </div>
            <div className="mt-3 text-lg font-bold">{marketDirectionLabel(event.market_relevance.direction, locale)}</div>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">{event.market_relevance.reasoning}</p>
            <span className="badge mt-3 border-line bg-panelAlt text-muted">{event.market_relevance.confidence}</span>
          </section>
          <section className="panel p-4">
            <h2 className="text-sm font-semibold">{isKo ? "영향 티커" : "Affected Tickers"}</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {event.tickers.length ? event.tickers.map((ticker) => (
                <Link key={ticker.symbol} to="/$locale/tickers/$symbol" params={{ locale, symbol: ticker.symbol }} className="badge min-h-11 border-accent/40 bg-accentSoft text-accent">
                  {ticker.symbol} · {Math.round(ticker.confidence * 100)}%
                </Link>
              )) : <span className="text-sm text-muted">{isKo ? "직접 티커 없음" : "No direct ticker"}</span>}
            </div>
          </section>
          <section className="panel p-4">
            <h2 className="text-sm font-semibold">{isKo ? "지역 관계" : "Region Relations"}</h2>
            <div className="mt-3 grid gap-2">
              {event.regions.map((region) => (
                <div key={`${region.key}-${region.relation}`} className="rounded-md border border-line bg-panelAlt p-3 text-sm">
                  <div className="font-semibold">{region.name}</div>
                  <div className="mt-1 text-xs text-muted">{regionRelationLabel(region.relation, locale)} · {Math.round(region.confidence * 100)}%</div>
                </div>
              ))}
            </div>
          </section>
          <section className="panel p-4">
            <h2 className="text-sm font-semibold">{isKo ? "출처" : "Sources"}</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {event.source_links.map((source) => <SourcePill key={`${source.source_key}-${source.url}`} source={source} />)}
            </div>
          </section>
        </aside>
      </section>

      <section className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "방법론" : "Methodology"}</h2>
        <p className="safe-text mt-2 text-sm leading-6 text-muted">{event.methodology}</p>
        <p className="safe-text mt-3 text-sm leading-6 text-warning">{event.disclaimer}</p>
      </section>

      {event.related_events.length ? (
        <section className="grid gap-3">
          <h2 className="text-xl font-bold">{isKo ? "관련 이벤트" : "Related Events"}</h2>
          {event.related_events.map((related) => <NewsEventCard key={related.id} event={related} locale={locale} compact />)}
        </section>
      ) : null}
    </div>
  );
}

function DetailBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="panel min-w-0 p-5">
      <h2 className="text-lg font-bold">{title}</h2>
      <ul className="mt-3 grid gap-2 text-sm leading-6 text-muted">
        {items.map((item) => (
          <li key={item} className="safe-text rounded-md border border-line bg-panelAlt p-3">
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
