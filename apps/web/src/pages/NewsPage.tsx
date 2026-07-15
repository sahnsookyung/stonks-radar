import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, SlidersHorizontal } from "lucide-react";
import type { NewsEventListItem } from "@frw/shared-types";
import { NewsEventCard } from "../components/NewsEventCard";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";
import { tickerMatchesFilterValue, trackedTickerFilterOptions } from "../lib/trackedTickers";

type TimeRange = "all" | "24h" | "7d" | "30d";

export function NewsPage() { // NOSONAR - filter state, URL sync, and snapshot rendering intentionally live in one page.
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = new URLSearchParams(globalThis.window.location.search);
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [ticker, setTicker] = useState(params.get("ticker") ?? "");
  const [region, setRegion] = useState(params.get("region") ?? "");
  const [topic, setTopic] = useState(params.get("topic") ?? "");
  const [trustTier, setTrustTier] = useState(params.get("trust") ?? "");
  const [timeRange, setTimeRange] = useState<TimeRange>(
    (params.get("range") as TimeRange) || "all",
  );
  const [breakingOnly, setBreakingOnly] = useState(
    params.get("breaking") === "1",
  );
  const [officialOnly, setOfficialOnly] = useState(
    params.get("official") === "1",
  );
  const [filtersExpanded, setFiltersExpanded] = useState(false);

  const newsQuery = useQuery({
    queryKey: ["snapshot", "news-index", locale],
    queryFn: () => snapshotQueries.newsIndex(locale),
  });

  const events = newsQuery.data?.data.events ?? [];
  const liveDataUnavailable = Boolean(
    newsQuery.data?.warnings.some(
      (warning) => warning.code === "live_data_unavailable",
    ),
  );
  const searchableEvents = useMemo(
    () =>
      events.map((event) => ({ event, searchableText: searchableText(event) })),
    [events],
  );

  useEffect(() => {
    const nextParams = new URLSearchParams();
    if (query.trim()) nextParams.set("q", query.trim());
    if (ticker) nextParams.set("ticker", ticker);
    if (region) nextParams.set("region", region);
    if (topic) nextParams.set("topic", topic);
    if (trustTier) nextParams.set("trust", trustTier);
    if (timeRange !== "all") nextParams.set("range", timeRange);
    if (breakingOnly) nextParams.set("breaking", "1");
    if (officialOnly) nextParams.set("official", "1");
    const nextSearch = nextParams.toString();
    const searchSuffix = nextSearch ? `?${nextSearch}` : "";
    const nextUrl = `${globalThis.window.location.pathname}${searchSuffix}${globalThis.window.location.hash}`;
    if (
      nextUrl !==
      `${globalThis.window.location.pathname}${globalThis.window.location.search}${globalThis.window.location.hash}`
    ) {
      globalThis.window.history.replaceState(null, "", nextUrl);
    }
  }, [
    breakingOnly,
    officialOnly,
    query,
    region,
    ticker,
    timeRange,
    topic,
    trustTier,
  ]);

  const filteredEvents = useMemo(() => {
    return searchableEvents
      .map((row) => row.event)
      .filter(
        (event, index) =>
          matchesKeyword(searchableEvents[index].searchableText, query) &&
          matchesTicker(event, ticker) &&
          matchesRegion(event, region) &&
          matchesTopic(event, topic) &&
          matchesTrust(event, trustTier) &&
          matchesTime(event, timeRange) &&
          (!breakingOnly || matchesBreaking(event)) &&
          (!officialOnly ||
            event.source_links.some((source) =>
              ["T0_OFFICIAL", "T1_REGULATED_FILING"].includes(
                source.trust_tier,
              ),
            )),
      );
  }, [
    breakingOnly,
    officialOnly,
    query,
    region,
    searchableEvents,
    ticker,
    timeRange,
    topic,
    trustTier,
  ]);

  if (newsQuery.isLoading) return <LoadingState />;
  if (newsQuery.isError || !newsQuery.data)
    return <ErrorState error={newsQuery.error} />;

  const filters = newsQuery.data.data.filters;
  const tickerOptions = trackedTickerFilterOptions(filters.tickers);
  const activeFilterCount = [
    query.trim(),
    ticker,
    region,
    topic,
    trustTier,
    timeRange === "all" ? "" : timeRange,
    breakingOnly ? "breaking" : "",
    officialOnly ? "official" : "",
  ].filter(Boolean).length;
  const resetFilters = () => {
    setQuery("");
    setTicker("");
    setRegion("");
    setTopic("");
    setTrustTier("");
    setTimeRange("all");
    setBreakingOnly(false);
    setOfficialOnly(false);
  };
  return (
    <div className="grid min-w-0 gap-5">
      <SnapshotBanner snapshot={newsQuery.data} />
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Search className="h-4 w-4" />
          {isKo ? "글로벌 뉴스 레이더" : "Global News Radar"}
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">
          {isKo ? "출처 연결 뉴스 레이더" : "Source-Linked News Radar"}
        </h1>
        <p className="safe-text mt-3 max-w-4xl text-sm leading-6 text-muted sm:text-base">
          {isKo
            ? "공개 페이지는 라이브 뉴스 API나 LLM을 호출하지 않고 승인된 스냅샷만 검색합니다."
            : "Public news search reads approved snapshots only. It does not call live news providers or LLMs from the browser."}
        </p>
      </section>

      <section className="panel min-w-0 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-semibold md:hidden"
              aria-controls="news-filters-panel"
              aria-expanded={filtersExpanded}
              onClick={() => setFiltersExpanded((expanded) => !expanded)}
            >
              <SlidersHorizontal className="h-4 w-4 text-accent" />
              {isKo ? "필터" : "Filters"}
              <span className="badge border-line bg-panelAlt text-muted">
                {activeFilterCount || (isKo ? "전체" : "All")}
              </span>
            </button>
            <div className="hidden min-h-11 items-center gap-2 text-sm font-semibold md:inline-flex">
              <SlidersHorizontal className="h-4 w-4 text-accent" />
              {isKo ? "필터" : "Filters"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="badge border-line bg-panelAlt text-muted">
              {filteredEvents.length} / {events.length}
            </span>
            {activeFilterCount > 0 && (
              <button
                type="button"
                className="secondary-action min-h-11 px-3 py-1.5 text-xs"
                onClick={resetFilters}
              >
                {isKo ? "초기화" : "Reset"}
              </button>
            )}
          </div>
        </div>
        <div
          id="news-filters-panel"
          className={`${filtersExpanded ? "grid" : "hidden"} mt-4 min-w-0 gap-3 md:grid md:grid-cols-3 xl:grid-cols-6`}
        >
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted md:col-span-2 xl:col-span-2">
            {isKo ? "검색어" : "Keyword"}
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="focus-ring min-h-11 rounded-md border border-line bg-paper px-3 text-sm font-medium text-ink"
              placeholder={isKo ? "티커, 지역, 주제" : "ticker, region, topic"}
            />
          </label>
          <FilterSelect
            label={isKo ? "티커" : "Ticker"}
            value={ticker}
            onChange={setTicker}
            options={tickerOptions}
            allLabel={isKo ? "모든 티커" : "All tickers"}
          />
          <FilterSelect
            label={isKo ? "지역" : "Region"}
            value={region}
            onChange={setRegion}
            options={filters.regions}
            allLabel={isKo ? "모든 지역" : "All regions"}
          />
          <FilterSelect
            label={isKo ? "주제" : "Topic"}
            value={topic}
            onChange={setTopic}
            options={filters.topics}
            allLabel={isKo ? "모든 주제" : "All topics"}
          />
          <FilterSelect
            label={isKo ? "신뢰" : "Trust"}
            value={trustTier}
            onChange={setTrustTier}
            options={filters.trust_tiers}
            allLabel={isKo ? "모든 출처" : "All trust"}
          />
          <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
            {isKo ? "기간" : "Range"}
            <select
              value={timeRange}
              onChange={(event) =>
                setTimeRange(event.target.value as TimeRange)
              }
              className="focus-ring min-h-11 rounded-md border border-line bg-paper px-3 text-sm font-medium text-ink"
            >
              <option value="all">{isKo ? "전체" : "All"}</option>
              <option value="24h">24h</option>
              <option value="7d">7d</option>
              <option value="30d">30d</option>
            </select>
          </label>
        </div>
        <div
          className={`${filtersExpanded ? "flex" : "hidden"} mt-4 flex-wrap gap-3 md:flex`}
        >
          <Toggle
            checked={breakingOnly}
            onChange={setBreakingOnly}
            label={isKo ? "속보만" : "Breaking only"}
          />
          <Toggle
            checked={officialOnly}
            onChange={setOfficialOnly}
            label={isKo ? "공식/공시 출처만" : "Official/filing only"}
          />
        </div>
      </section>

      <section className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold">{isKo ? "출처 연결 항목" : "Source-linked items"}</h2>
          <span className="badge border-line bg-panelAlt text-muted">
            {isKo
              ? `${filteredEvents.length}개 표시`
              : `${filteredEvents.length} shown`}
          </span>
        </div>
        {filteredEvents.length > 0 && (
          filteredEvents.map((event) => (
            <NewsEventCard key={event.id} event={event} locale={locale} />
          ))
        )}
        {filteredEvents.length === 0 && (
          <div className="panel border-dashed p-5 text-sm leading-6 text-muted">
            {newsEmptyMessage(liveDataUnavailable, events.length, isKo)}
          </div>
        )}
      </section>

      <section className="signal-warning p-4 text-sm leading-6">
        {isKo
          ? "뉴스 요약은 출처 연결 리서치 맥락이며 개인화된 투자 조언이 아닙니다."
          : "News summaries are source-linked research context, not personalized investment advice."}
      </section>
    </div>
  );
}

function newsEmptyMessage(
  liveDataUnavailable: boolean,
  eventCount: number,
  isKo: boolean,
) {
  if (liveDataUnavailable && eventCount === 0) {
    return isKo
      ? "현재 출처 기반 뉴스 데이터를 사용할 수 없습니다. 정적 예시 뉴스는 표시하지 않습니다."
      : "Current source-backed news is unavailable. Static example news is not displayed.";
  }

  return isKo
    ? "선택한 필터와 일치하는 출처 연결 항목이 없습니다."
    : "No source-linked items match the selected filters.";
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: Readonly<{
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { key: string; label: string; count: number }[];
  allLabel: string;
}>) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="focus-ring min-h-11 min-w-0 rounded-md border border-line bg-paper px-3 text-sm font-medium text-ink"
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label} ({option.count})
          </option>
        ))}
      </select>
    </label>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: Readonly<{
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}>) {
  return (
    <label className="focus-within:ring-focus inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border border-line bg-panelAlt px-3 text-sm font-semibold">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

function searchableText(event: NewsEventListItem) {
  return [
    event.title,
    event.summary,
    event.event_type,
    ...event.tickers.flatMap((ticker) => [ticker.symbol, ticker.name]),
    ...event.regions.map((region) => region.name),
    ...event.topics.map((topic) => topic.label),
    ...event.source_links.flatMap((source) => [source.label, source.title]),
  ]
    .join(" ")
    .toLowerCase();
}

function matchesKeyword(haystack: string, value: string) {
  const query = value.trim().toLowerCase();
  if (!query) return true;
  return haystack.includes(query);
}

function matchesTicker(event: NewsEventListItem, value: string) {
  if (!value) return true;
  return event.tickers.some((ticker) => tickerMatchesFilterValue(ticker.symbol, value));
}

function matchesRegion(event: NewsEventListItem, value: string) {
  if (!value) return true;
  return event.regions.some((region) => region.key === value);
}

function matchesTopic(event: NewsEventListItem, value: string) {
  if (!value) return true;
  return event.topics.some((topic) => topic.key === value);
}

function matchesTrust(event: NewsEventListItem, value: string) {
  if (!value) return true;
  return event.source_links.some((source) => source.trust_tier === value);
}

function matchesTime(event: NewsEventListItem, value: TimeRange) {
  if (value === "all") return true;
  const timestamp = new Date(event.last_seen_at).getTime();
  if (!Number.isFinite(timestamp)) return true;
  const hours = hoursForTimeRange(value);
  return Date.now() - timestamp <= hours * 60 * 60 * 1000;
}

function matchesBreaking(event: NewsEventListItem) {
  const claimLevel = event.claim_level ?? "source_only";
  const itemKind = event.item_kind ?? "source_discovery";

  return event.breaking_score >= 70 && claimLevel !== "source_only" && itemKind !== "source_discovery";
}

function hoursForTimeRange(value: Exclude<TimeRange, "all">) {
  if (value === "24h") return 24;
  if (value === "7d") return 24 * 7;
  return 24 * 30;
}
