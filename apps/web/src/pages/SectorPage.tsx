import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { CalendarClock, ExternalLink, Factory, Newspaper, ShieldAlert, TrendingDown } from "lucide-react";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { EntityLink } from "../components/EntityLink";
import { EventList } from "../components/EventList";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { NewsEventCard } from "../components/NewsEventCard";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { safeExternalUrl } from "../lib/safeExternalUrl";
import { snapshotQueries } from "../lib/snapshots";
import type { ShortFact, TickerCalendarItem } from "@frw/shared-types";

export function SectorPage() {
  const locale = useLocale();
  const params = useParams({ strict: false }) as { sectorKey?: string };
  const sectorKey = params.sectorKey ?? "semiconductors";
  const query = useQuery({
    queryKey: ["snapshot", "sector", sectorKey, locale],
    queryFn: () => snapshotQueries.sector(sectorKey, locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;
  const data = query.data.data;

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Factory className="h-4 w-4" />
          Sector module
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{data.name}</h1>
        <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted">{data.overview}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <FreshnessBadge value={data.freshness} />
          <SourceBadge label={data.source_strength} />
        </div>
      </section>
      <section className="panel min-w-0 p-4">
        <h2 className="text-sm font-semibold">{locale === "ko" ? "추적 엔티티" : "Tracked entities"}</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {data.tracked_entities.length > 0 && (
            data.tracked_entities.map((entity) => (
              <EntityLink key={entity.entity_id} value={entity.route_key} locale={locale} className="badge min-h-11 max-w-full border-line bg-panelAlt text-ink hover:border-accent hover:text-accent">
                <span className="flex min-w-0 flex-col items-start gap-0.5 leading-tight">
                  <span className="font-semibold">{entity.display_symbol}</span>
                  <span className="safe-text text-[11px] font-medium text-muted">{entity.name}</span>
                </span>
              </EntityLink>
            ))
          )}
          {data.tracked_entities.length === 0 && (
            <EmptyState text={locale === "ko" ? "이 섹터에 연결된 추적 엔티티가 없습니다." : "No tracked registry entities are linked to this sector yet."} />
          )}
        </div>
      </section>
      <section className="grid gap-4 lg:grid-cols-3">
        <InfoList title="Instruments" items={data.monitored_instruments} />
        <InfoList title="Country/region exposure" items={data.country_region_exposure} />
        <InfoList title="Sector drivers" items={data.macro_geopolitical_drivers} />
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">
          {locale === "ko" ? "최근 출처 연결 이벤트" : "Recent source-linked events"}
        </h2>
        {data.recent_events.length > 0 && <EventList events={data.recent_events} />}
        {data.recent_events.length === 0 && <EmptyState text={locale === "ko" ? "현재 이 섹터 전용 출처 연결 이벤트가 없습니다." : "No sector-specific source-linked events are available in this snapshot."} />}
      </section>
      <section className="grid gap-4 lg:grid-cols-[0.42fr_0.58fr]">
        <div className="panel min-w-0 p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <CalendarClock className="h-4 w-4 text-accent" />
            {locale === "ko" ? "티커별 촉매 일정" : "Ticker Catalyst Calendar"}
          </div>
          <div className="grid gap-2">
            {data.ticker_calendar_items.length > 0 && (
              data.ticker_calendar_items.map((item) => <TickerCalendarCard key={item.id} item={item} locale={locale} />)
            )}
            {data.ticker_calendar_items.length === 0 && (
              <EmptyState text={locale === "ko" ? "이 섹터에 연결된 티커별 예정 촉매가 없습니다. 거시 일정은 경제 캘린더에서 분리해 표시합니다." : "No ticker-specific upcoming catalysts are linked. Macro calendars stay on the Economic Calendar page."} />
            )}
          </div>
        </div>
        <div className="panel min-w-0 p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <Newspaper className="h-4 w-4 text-accent" />
            {locale === "ko" ? "섹터 뉴스" : "Sector News"}
          </div>
          <div className="grid gap-3">
            {data.sector_news.length > 0 && (
              data.sector_news.map((event) => <NewsEventCard key={event.id} event={event} locale={locale} compact />)
            )}
            {data.sector_news.length === 0 && (
              <EmptyState text={locale === "ko" ? "현재 이 섹터 티커와 직접 연결된 뉴스가 없습니다." : "No current news is directly linked to this sector's tracked tickers."} />
            )}
          </div>
        </div>
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <div className="panel min-w-0 p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <TrendingDown className="h-4 w-4 text-accent" />
            {locale === "ko" ? "출처 기반 공매도 사실" : "Source-backed short facts"}
          </div>
          <div className="grid gap-2">
            {data.sector_short_facts.length > 0 && (
              data.sector_short_facts.map((fact) => <ShortFactCard key={fact.id} fact={fact} locale={locale} />)
            )}
            {data.sector_short_facts.length === 0 && (
              <EmptyState text={locale === "ko" ? "이번 스냅샷에는 공식 FINRA 공매도 사실 행이 없습니다." : "No source-backed FINRA short fact rows are available in this snapshot."} />
            )}
          </div>
        </div>
        <div className="panel min-w-0 p-4">
          <div className="mb-3 flex items-center gap-2 font-semibold">
            <ShieldAlert className="h-4 w-4" />
            Risks and caveats
          </div>
          <ul className="grid gap-2 text-sm leading-6 text-muted">
            {data.risks_and_caveats.map((item) => (
              <li key={item} className="safe-text">{item}</li>
            ))}
          </ul>
        </div>
      </section>
      <section>
        <h2 className="mb-3 text-2xl font-bold">Scenario baskets</h2>
        <div className="grid gap-3 md:grid-cols-2">
          {data.scenario_baskets.map((basket) => (
            <Link
              key={basket.key}
              to="/$locale/scenario-baskets/$basketKey"
              params={{ locale, basketKey: basket.key }}
              className="panel focus-ring block p-4 hover:border-accent"
            >
              <div className="safe-text font-semibold">{basket.name}</div>
              <p className="safe-text mt-2 text-sm leading-6 text-muted">{basket.thesis}</p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function TickerCalendarCard({ item, locale }: Readonly<{ item: TickerCalendarItem; locale: "en" | "ko" }>) {
  const sourceHref = safeExternalUrl(item.source_url);
  return (
    <div className="grid min-h-11 gap-2 rounded-md border border-line bg-panelAlt px-3 py-2">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="safe-text text-sm font-semibold">{item.title}</div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted">
            <EntityLink value={item.symbol} locale={locale} />
            <span>{item.scheduled_local_date}</span>
            <span>{item.catalyst_type.replaceAll("_", " ")}</span>
          </div>
        </div>
        {sourceHref ? (
          <a className="focus-ring inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md text-xs font-semibold text-accent hover:underline" href={sourceHref} target="_blank" rel="noreferrer">
            {locale === "ko" ? "원문" : "Source"}
            <ExternalLink className="h-4 w-4" />
          </a>
        ) : (
          <SourceBadge label={item.source} />
        )}
      </div>
    </div>
  );
}

function ShortFactCard({ fact, locale }: Readonly<{ fact: ShortFact; locale: "en" | "ko" }>) {
  const label = shortFactLabel(fact.fact_type, locale);
  const sourceLabel = shortFactSourceLabel(fact, locale);
  const sourceHref = safeExternalUrl(fact.source_url);
  return (
    <div className="grid min-h-11 gap-1 rounded-md border border-line bg-panelAlt px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <EntityLink value={fact.symbol} locale={locale} />
            <span className="safe-text text-sm font-semibold">{label}</span>
          </div>
          <p className="safe-text mt-1 text-xs leading-5 text-muted">{fact.as_of_date} · {fact.caveat}</p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-bold text-accent">{formatShares(fact.value)}</div>
          <div className="text-[11px] text-muted">{fact.freshness}</div>
        </div>
      </div>
      {sourceHref ? (
        <a className="focus-ring inline-flex min-h-11 w-fit items-center gap-1 rounded-md text-xs font-semibold text-accent hover:underline" href={sourceHref} target="_blank" rel="noreferrer">
          {sourceLabel}
          <ExternalLink className="h-4 w-4" />
        </a>
      ) : (
        <SourceBadge label={sourceLabel} />
      )}
    </div>
  );
}

function shortFactSourceLabel(fact: ShortFact, locale: "en" | "ko") {
  const isFintelShortInterestLink = fact.fact_type === "short_interest" && fact.source_url.includes("fintel.io/ss/us/");
  if (isFintelShortInterestLink) return locale === "ko" ? "FINRA 데이터 / Fintel 링크" : "FINRA data / Fintel link";
  return locale === "ko" ? "FINRA 원문" : "FINRA source";
}

function shortFactLabel(factType: string, locale: "en" | "ko") {
  if (factType === "short_interest") return locale === "ko" ? "공매도 잔고" : "Short interest";
  return locale === "ko" ? "일별 공매도 거래량" : "Daily short volume";
}

function formatShares(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "pending";
  if (value >= 1_000_000) return `${trimFixedZeros((value / 1_000_000).toFixed(2))}M`;
  if (value >= 1_000) return `${trimFixedZeros((value / 1_000).toFixed(1))}K`;
  return value.toLocaleString();
}

function trimFixedZeros(value: string): string {
  let end = value.length;
  while (end > 0 && value[end - 1] === "0") end -= 1;
  if (end > 0 && value[end - 1] === ".") end -= 1;
  return value.slice(0, end);
}

function EmptyState({ text }: Readonly<{ text: string }>) {
  return <div className="safe-text min-h-11 rounded-md border border-dashed border-line px-3 py-2 text-sm leading-6 text-muted">{text}</div>;
}

function InfoList({ title, items }: Readonly<{ title: string; items: string[] }>) {
  return (
    <div className="panel min-w-0 p-4">
      <h2 className="font-semibold">{title}</h2>
      <ul className="mt-3 grid gap-2 text-sm text-muted">
        {items.map((item) => (
          <li key={item} className="safe-text">{item}</li>
        ))}
      </ul>
    </div>
  );
}
