import { useQuery } from "@tanstack/react-query";
import type { HomeSnapshotData, MetricTile, SnapshotEnvelope } from "@frw/shared-types";
import { ExternalLink, LineChart, TrendingDown, TrendingUp } from "lucide-react";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

type CurvePoint = {
  key: string;
  label: string;
  years: number;
  value: number;
  updatedAt: string;
  source: string;
  sourceUrl?: string;
  freshness: MetricTile["freshness"];
};

const US_TERMS = [
  ["us_2y", "2Y", 2],
  ["us_3y", "3Y", 3],
  ["us_5y", "5Y", 5],
  ["us_10y", "10Y", 10]
] as const;

const JAPAN_TERMS = [
  ["japan_2y", "2Y", 2],
  ["japan_5y", "5Y", 5],
  ["japan_10y", "10Y", 10]
] as const;

export function YieldCurvesPage() {
  const locale = useLocale();
  const query = useQuery({
    queryKey: ["snapshot", "home", locale, "yield-curves"],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const usCurve = buildCurve(query.data, US_TERMS);
  const japanCurve = buildCurve(query.data, JAPAN_TERMS);

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="panel grid gap-5 p-4 md:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
              <LineChart className="h-4 w-4" />
              {locale === "ko" ? "수익률 곡선" : "Yield Curves"}
            </div>
            <h1 className="safe-text mt-2 text-3xl font-bold leading-tight md:text-5xl">
              {locale === "ko" ? "국채 수익률 곡선" : "Government Yield Curves"}
            </h1>
            <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
              {locale === "ko"
                ? "공개 스냅샷에 저장된 공식 금리 타일을 곡선으로 재구성합니다. 실시간 거래 데이터가 아니라 최근 공개 관측치입니다."
                : "Reconstructed from official rates already present in the public snapshot. This is recent public observation data, not realtime trading data."}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[520px]">
            <StatusPill label={locale === "ko" ? "미국 구간" : "US points"} value={String(usCurve.length)} />
            <StatusPill label={locale === "ko" ? "일본 구간" : "Japan points"} value={String(japanCurve.length)} />
            <StatusPill label={locale === "ko" ? "자료" : "Data"} value={locale === "ko" ? "스냅샷" : "snapshot"} />
            <StatusPill label={locale === "ko" ? "실시간" : "Realtime"} value={locale === "ko" ? "아님" : "no"} />
          </div>
        </div>
      </section>

      <div className="grid min-w-0 gap-6 xl:grid-cols-[1fr_360px]">
        <div className="grid min-w-0 gap-6">
          <CurvePanel
            title={locale === "ko" ? "미국 국채" : "US Treasury"}
            detail={locale === "ko" ? "2Y, 3Y, 5Y, 10Y 공개 관측치" : "2Y, 3Y, 5Y, and 10Y public observations"}
            points={usCurve}
          />
          <CurvePanel
            title={locale === "ko" ? "일본 국채" : "Japan Government Bonds"}
            detail={locale === "ko" ? "MOF/JGB 공개 관측치 기반" : "Based on MOF/JGB public observations"}
            points={japanCurve}
          />
        </div>
        <aside className="grid content-start gap-4">
          <SpreadPanel title="US 10Y-2Y" points={usCurve} longLabel="10Y" shortLabel="2Y" />
          <SpreadPanel title="Japan 10Y-2Y" points={japanCurve} longLabel="10Y" shortLabel="2Y" />
          <section className="panel p-4">
            <h2 className="text-base font-semibold">{locale === "ko" ? "TradingView 참고" : "TradingView Reference"}</h2>
            <p className="safe-text mt-2 text-sm leading-6 text-muted">
              {locale === "ko"
                ? "TradingView는 공식 수익률 곡선 임베드 위젯을 제공하지 않아 앱 내 표시는 네이티브 스냅샷 차트로 유지합니다."
                : "TradingView does not expose a dedicated official embeddable yield-curve widget, so this app keeps the in-page view native and snapshot-first."}
            </p>
            <a
              href="https://www.tradingview.com/search/?query=yield%20curve"
              target="_blank"
              rel="noreferrer"
              className="secondary-action mt-4 justify-center"
            >
              <ExternalLink className="h-4 w-4" />
              {locale === "ko" ? "TradingView 검색" : "Open TradingView search"}
            </a>
          </section>
        </aside>
      </div>
    </div>
  );
}

function buildCurve(
  snapshot: SnapshotEnvelope<HomeSnapshotData>,
  terms: readonly (readonly [string, string, number])[]
): CurvePoint[] {
  const tiles = new Map(snapshot.data.macro_tiles.map((tile) => [tile.key, tile]));
  const points: CurvePoint[] = [];
  for (const [key, label, years] of terms) {
      const tile = tiles.get(key);
      const value = tile ? parseMetricValue(tile.value) : null;
      if (!tile || value == null) continue;
      points.push({
        key,
        label,
        years,
        value,
        updatedAt: tile.updated_at,
        source: tile.source,
        sourceUrl: tile.source_url,
        freshness: tile.freshness
      });
    }
  return points;
}

function CurvePanel({ title, detail, points }: { title: string; detail: string; points: CurvePoint[] }) {
  const latest = latestDate(points);
  return (
    <section className="panel min-w-0 overflow-hidden p-4 md:p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 className="text-xl font-bold">{title}</h2>
          <p className="safe-text mt-1 text-sm leading-6 text-muted">{detail}</p>
        </div>
        <div className="rounded-md border border-line bg-panelAlt px-3 py-2 text-xs font-semibold text-muted">
          {latest ? `latest ${latest}` : "no current snapshot"}
        </div>
      </div>
      {points.length >= 2 ? (
        <YieldCurveChart points={points} />
      ) : (
        <div className="mt-4 rounded-md border border-dashed border-line p-6 text-sm text-muted">
          No source-backed curve points are available in this snapshot.
        </div>
      )}
      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {points.map((point) => (
          <a
            key={point.key}
            href={point.sourceUrl || "#"}
            target={point.sourceUrl ? "_blank" : undefined}
            rel={point.sourceUrl ? "noreferrer" : undefined}
            className="rounded-md border border-line bg-panelAlt p-3 hover:border-accent"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-muted">{point.label}</span>
              <span className="text-xs uppercase text-muted">{point.freshness}</span>
            </div>
            <div className="mt-2 text-2xl font-bold">{point.value.toFixed(2)}%</div>
            <div className="safe-text mt-1 text-xs leading-5 text-muted">{point.source}</div>
          </a>
        ))}
      </div>
    </section>
  );
}

function YieldCurveChart({ points }: { points: CurvePoint[] }) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const yMin = Math.floor((min - 0.25) * 4) / 4;
  const yMax = Math.ceil((max + 0.25) * 4) / 4;
  const width = 720;
  const height = 260;
  const padding = { top: 22, right: 24, bottom: 42, left: 48 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const maxYears = Math.max(...points.map((point) => point.years));
  const range = yMax - yMin || 1;
  const coords = points.map((point) => {
    const x = padding.left + (point.years / maxYears) * innerWidth;
    const y = padding.top + (1 - (point.value - yMin) / range) * innerHeight;
    return { ...point, x, y };
  });
  const path = coords.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
  return (
    <svg className="mt-4 h-[260px] w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Yield curve" preserveAspectRatio="none">
      {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
        const y = padding.top + tick * innerHeight;
        const value = yMax - tick * range;
        return (
          <g key={tick}>
            <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(147, 163, 183, 0.18)" />
            <text x={padding.left - 10} y={y + 4} textAnchor="end" fontSize="11" fill="#93a3b7">
              {value.toFixed(1)}%
            </text>
          </g>
        );
      })}
      <path d={path} fill="none" stroke="#67d8ef" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />
      {coords.map((point) => (
        <g key={point.key}>
          <circle cx={point.x} cy={point.y} r="5" fill="#67d8ef" stroke="#0b1118" strokeWidth="2" />
          <text x={point.x} y={height - 18} textAnchor="middle" fontSize="12" fill="#dfe8f5">
            {point.label}
          </text>
          <text x={point.x} y={point.y - 10} textAnchor="middle" fontSize="12" fontWeight="700" fill="#dfe8f5">
            {point.value.toFixed(2)}
          </text>
        </g>
      ))}
    </svg>
  );
}

function SpreadPanel({ title, points, longLabel, shortLabel }: { title: string; points: CurvePoint[]; longLabel: string; shortLabel: string }) {
  const longPoint = points.find((point) => point.label === longLabel);
  const shortPoint = points.find((point) => point.label === shortLabel);
  const spread = longPoint && shortPoint ? longPoint.value - shortPoint.value : null;
  const inverted = spread != null && spread < 0;
  return (
    <section className="panel p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{title}</h2>
        {spread == null ? null : inverted ? <TrendingDown className="h-5 w-5 text-warning" /> : <TrendingUp className="h-5 w-5 text-success" />}
      </div>
      <div className={`mt-3 text-3xl font-bold ${inverted ? "text-warning" : "text-success"}`}>
        {spread == null ? "n/a" : `${(spread * 100).toFixed(0)} bp`}
      </div>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">
        {spread == null
          ? "Spread cannot be computed until both curve points are present."
          : inverted
            ? "Curve is inverted at this spread."
            : "Curve is positively sloped at this spread."}
      </p>
    </section>
  );
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panelAlt px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="safe-text mt-1 text-sm font-bold text-ink">{value}</div>
    </div>
  );
}

function parseMetricValue(value: string) {
  const normalized = value.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!normalized) return null;
  const parsed = Number(normalized[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function latestDate(points: CurvePoint[]) {
  return points.map((point) => point.updatedAt?.slice(0, 10)).filter(Boolean).sort().at(-1) ?? null;
}
