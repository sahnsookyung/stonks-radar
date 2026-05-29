import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, CalendarDays, ChevronLeft, ChevronRight, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { MetricTile } from "@frw/shared-types";
import { LineChart } from "./LineChart";
import { useLocale } from "../lib/locale";

export const marketOrder = [
  "nasdaq_composite",
  "nasdaq_100",
  "kospi",
  "krx_300",
  "krx_300_it",
  "ewy_korea_proxy",
  "wti_crude",
  "vix",
  "usd_krw",
  "usd_jpy",
  "us_2y",
  "us_3y",
  "us_5y",
  "us_10y",
  "japan_policy_rate",
  "japan_2y",
  "japan_5y",
  "japan_10y",
  "pentagon_pizza_index"
];

export function sortMarketTiles(tiles: MetricTile[]) {
  return [...tiles].sort((left, right) => marketRank(left.key) - marketRank(right.key));
}

export function MarketPulseTickerBar({ tiles }: { tiles: MetricTile[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const locale = useLocale();
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const orderedTiles = useMemo(() => sortMarketTiles(tiles), [tiles]);
  const scroll = (direction: -1 | 1) => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollBy({
      left: direction * Math.max(360, container.clientWidth * 0.75),
      behavior: "smooth"
    });
  };

  return (
    <section className="panel min-w-0 overflow-hidden p-3" aria-labelledby="market-pulse-strip-title">
      <div className="mb-2 flex items-center justify-between gap-3">
        <Link
          id="market-pulse-strip-title"
          to="/$locale/market-pulse"
          params={{ locale }}
          className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md text-sm font-semibold text-accent hover:text-ink"
        >
          <TrendingUp className="h-4 w-4" />
          {t("marketPulse")}
        </Link>
        <div className="flex items-center gap-2">
          <Link to="/$locale/market-pulse" params={{ locale }} className="secondary-action min-h-11 px-3 py-1.5 text-xs">
            {locale === "ko" ? "전체" : "All"}
          </Link>
          <button type="button" className="secondary-action h-11 min-h-11 w-11 p-0" onClick={() => scroll(-1)} aria-label={t("scrollLeft")}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button type="button" className="secondary-action h-11 min-h-11 w-11 p-0" onClick={() => scroll(1)} aria-label={t("scrollRight")}>
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div
        ref={scrollRef}
        className="scroll-fade-x -mx-1 flex max-w-full snap-x gap-2 overflow-x-auto px-1 pb-4 sm:pb-5"
        data-testid="market-pulse-strip"
        data-allow-horizontal-scroll
        aria-label={locale === "ko" ? "시장 펄스 티커 스트립" : "Market pulse ticker strip"}
      >
        {orderedTiles.map((tile) => (
          <MarketPulseMiniTile key={tile.key} tile={tile} locale={locale} now={now} />
        ))}
      </div>
    </section>
  );
}

export function MarketPulseBoard({ tiles }: { tiles: MetricTile[] }) {
  const locale = useLocale();
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(interval);
  }, []);
  const groups = groupMarketTiles(sortMarketTiles(tiles), locale);

  return (
    <div className="grid min-w-0 gap-6">
      <section className="panel-raised p-4 sm:p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
              <TrendingUp className="h-4 w-4" />
              {t("marketPulse")}
            </div>
            <h1 className="mt-2 text-2xl font-bold leading-tight sm:text-3xl">{locale === "ko" ? "시장 펄스" : "Market Pulse"}</h1>
          </div>
          <p className="safe-text max-w-3xl text-sm leading-6 text-muted">
            {locale === "ko"
              ? "지연/참조 지표를 한 곳에 모았습니다. 항목을 클릭하면 원 출처로 이동하고, 화살표는 최근 관측치 대비 변화를 표시합니다."
              : "Delayed/reference indicators in one place. Click any item for the source; arrows show the change versus the previous observed point."}
          </p>
        </div>
      </section>
      {groups.map((group) => (
        <section key={group.key} className="min-w-0" aria-labelledby={`market-pulse-${group.key}`}>
          <h2 id={`market-pulse-${group.key}`} className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
            {group.title}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {group.tiles.map((tile) => (
              <MarketPulseCard key={tile.key} tile={tile} locale={locale} now={now} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function MarketPulseMiniTile({ tile, locale, now }: { tile: MetricTile; locale: "en" | "ko"; now: number }) {
  const delta = metricDelta(tile);
  const unavailable = isUnavailableTile(tile);
  const update = metricUpdate(tile.updated_at, tile.refresh_seconds, locale, now);
  const body = (
    <>
      <div className="h-8 w-16 shrink-0 sm:h-9 sm:w-20">
        <TinySparkline points={tile.points ?? []} unavailable={unavailable} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-semibold leading-4 text-muted">{tile.label}</div>
        <div className="mt-0.5 flex min-w-0 items-baseline gap-2">
          <span className="truncate text-base font-bold leading-6 text-ink sm:text-lg">
            {tile.value}
            {tile.unit ? <span className="ml-1 text-xs font-semibold text-muted">{tile.unit}</span> : null}
          </span>
          <DeltaBadge delta={delta} compact />
        </div>
        <div className={`mt-0.5 truncate text-[11px] font-medium leading-4 ${update.toneClass}`}>{update.label}</div>
      </div>
    </>
  );

  const className =
    "focus-ring flex h-[72px] w-[min(220px,75vw)] shrink-0 snap-start items-center gap-3 rounded-md border border-line bg-panelAlt px-3 py-2 transition-colors hover:border-accent sm:h-[78px] sm:w-[250px]";
  if (tile.source_url && !unavailable) {
    return (
      <a className={className} href={tile.source_url} target="_blank" rel="noreferrer" aria-label={`${tile.label} source`}>
        {body}
      </a>
    );
  }
  return <article className={className}>{body}</article>;
}

function MarketPulseCard({ tile, locale, now }: { tile: MetricTile; locale: "en" | "ko"; now: number }) {
  const unavailable = isUnavailableTile(tile);
  const delta = metricDelta(tile);
  const update = metricUpdate(tile.updated_at, tile.refresh_seconds, locale, now);
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm leading-5 text-muted">{tile.label}</div>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <span className="text-2xl font-bold leading-8 text-ink">
              {tile.value}
              {tile.unit ? <span className="ml-1 text-sm font-semibold text-muted">{tile.unit}</span> : null}
            </span>
            <DeltaBadge delta={delta} />
          </div>
        </div>
        {unavailable ? (
          <span className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] font-semibold uppercase leading-4 text-warning">
            {locale === "ko" ? "공백" : "gap"}
          </span>
        ) : null}
      </div>
      <div className="mt-3 h-24 shrink-0 sm:h-28">
        {tile.points && tile.points.length >= 2 ? (
          <LineChart points={tile.points} label={tile.label} />
        ) : (
          <div className="h-full rounded-md border border-line bg-paper/40" aria-hidden="true" />
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs leading-5 text-muted">
        <span className={`font-semibold ${update.toneClass}`}>{update.label}</span>
        {tile.refresh_seconds ? <span>{update.targetLabel}</span> : null}
        {update.isOverdue ? (
          <span className="rounded border border-warning/40 bg-warning/10 px-1.5 py-0.5 font-semibold text-warning">
            {locale === "ko" ? "목표 지연" : "target missed"}
          </span>
        ) : null}
      </div>
      {unavailable ? <p className="safe-text mt-2 text-xs leading-5 text-muted">{tile.delay_label}</p> : null}
      {tile.next_event ? (
        <div className="mt-auto flex items-start gap-2 pt-3 text-xs leading-5 text-muted">
          <CalendarDays className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="min-w-0">
            <span className="font-semibold text-ink">{locale === "ko" ? "다음:" : "Next:"}</span> {tile.next_event.title} ·{" "}
            {tile.next_event.date}
          </span>
        </div>
      ) : null}
    </>
  );
  const className = "panel focus-ring flex min-h-[230px] min-w-0 flex-col p-4 transition-colors hover:border-accent sm:min-h-[260px]";
  if (tile.source_url && !unavailable) {
    return (
      <a className={className} href={tile.source_url} target="_blank" rel="noreferrer" aria-label={`${tile.label} source`}>
        {body}
      </a>
    );
  }
  return <article className={className}>{body}</article>;
}

function DeltaBadge({ delta, compact = false }: { delta: number | null; compact?: boolean }) {
  if (delta === null) {
    return null;
  }
  if (Math.abs(delta) < 0.000001) {
    return <span className={`shrink-0 font-semibold text-muted ${compact ? "text-xs" : "text-sm"}`}>0</span>;
  }
  const positive = delta > 0;
  const Icon = positive ? ArrowUp : ArrowDown;
  const tone = positive ? "text-success" : "text-danger";
  return (
    <span className={`inline-flex shrink-0 items-center gap-0.5 font-semibold ${tone} ${compact ? "text-xs" : "text-sm"}`}>
      <Icon className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
      {formatDelta(delta)}
    </span>
  );
}

function TinySparkline({ points, unavailable }: { points: { date: string; value: number }[]; unavailable: boolean }) {
  if (points.length < 2) {
    return <div className="h-full rounded border border-line bg-paper/40" aria-hidden="true" />;
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 88;
  const height = 36;
  const coords = points.map((point, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = 3 + (1 - (point.value - min) / range) * (height - 6);
    return [x, y] as const;
  });
  const path = coords.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const stroke = unavailable ? "#93a3b7" : values[values.length - 1] >= values[0] ? "#55c58e" : "#ff6b70";
  return (
    <svg className="h-full w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="sparkline" preserveAspectRatio="none">
      <line x1="0" x2={width} y1={height - 3} y2={height - 3} stroke="rgba(147, 163, 183, 0.2)" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke={stroke} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" />
    </svg>
  );
}

function groupMarketTiles(tiles: MetricTile[], locale: "en" | "ko") {
  const labels = {
    equity: locale === "ko" ? "주식 / 변동성" : "Equity / Volatility",
    fx: locale === "ko" ? "환율 / 원자재" : "FX / Commodities",
    rates: locale === "ko" ? "금리" : "Rates",
    alternative: locale === "ko" ? "대체 지표" : "Alternative Signals"
  };
  const groups = [
    { key: "equity", title: labels.equity, tiles: [] as MetricTile[] },
    { key: "fx", title: labels.fx, tiles: [] as MetricTile[] },
    { key: "rates", title: labels.rates, tiles: [] as MetricTile[] },
    { key: "alternative", title: labels.alternative, tiles: [] as MetricTile[] }
  ];
  for (const tile of tiles) {
    if (tile.key.startsWith("us_") || tile.key.startsWith("japan_")) groups[2].tiles.push(tile);
    else if (tile.key.startsWith("usd_") || tile.key.includes("crude")) groups[1].tiles.push(tile);
    else if (tile.key.includes("pizza")) groups[3].tiles.push(tile);
    else groups[0].tiles.push(tile);
  }
  return groups.filter((group) => group.tiles.length > 0);
}

function metricRank(key: string) {
  const index = marketOrder.indexOf(key);
  return index === -1 ? marketOrder.length : index;
}

function marketRank(key: string) {
  return metricRank(key);
}

function metricDelta(tile: MetricTile) {
  if (Number.isFinite(tile.refresh_delta)) return tile.refresh_delta as number;
  if (!tile.points || tile.points.length < 2) return null;
  const previous = tile.points[tile.points.length - 2]?.value;
  const current = tile.points[tile.points.length - 1]?.value;
  if (!Number.isFinite(previous) || !Number.isFinite(current)) return null;
  return current - previous;
}

function formatDelta(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1000) return abs.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 100) return abs.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (abs >= 10) return abs.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return abs.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function formatRefreshInterval(seconds: number, locale: "en" | "ko") {
  if (seconds < 60) return locale === "ko" ? `${seconds}초마다` : `every ${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return locale === "ko" ? `${minutes}분마다` : `every ${minutes}m`;
  const hours = Math.round(minutes / 60);
  return locale === "ko" ? `${hours}시간마다` : `every ${hours}h`;
}

function isUnavailableTile(tile: MetricTile) {
  return (
    tile.coverage_status === "coverage_gap" ||
    tile.value.trim().toLowerCase() === "not connected" ||
    tile.freshness === "unsupported"
  );
}

function metricUpdate(value: string, refreshSeconds: number | undefined, locale: "en" | "ko", now: number) {
  const updatedAt = Date.parse(value);
  if (!Number.isFinite(updatedAt)) {
    return {
      label: locale === "ko" ? "갱신 시각 불명" : "Updated time unknown",
      targetLabel: refreshSeconds ? formatRefreshInterval(refreshSeconds, locale) : "",
      isOverdue: false,
      toneClass: "text-muted"
    };
  }
  const elapsedMinutes = Math.max(0, Math.floor((now - updatedAt) / 60_000));
  const isOverdue = typeof refreshSeconds === "number" && now - updatedAt > Math.max(refreshSeconds * 2 * 1000, 20 * 60_000);
  const label = formatMetricUpdateAge(elapsedMinutes, locale);
  return {
    label,
    targetLabel: refreshSeconds ? formatRefreshInterval(refreshSeconds, locale) : "",
    isOverdue,
    toneClass: isOverdue ? "text-warning" : "text-accent"
  };
}

function formatMetricUpdateAge(elapsedMinutes: number, locale: "en" | "ko") {
  if (elapsedMinutes < 1) return locale === "ko" ? "방금 갱신" : "Updated now";
  if (elapsedMinutes < 60) return locale === "ko" ? `${elapsedMinutes}분 전` : `${elapsedMinutes}m ago`;
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 48) return locale === "ko" ? `${elapsedHours}시간 전` : `${elapsedHours}h ago`;
  const elapsedDays = Math.floor(elapsedHours / 24);
  return locale === "ko" ? `${elapsedDays}일 전` : `${elapsedDays}d ago`;
}
