import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { HomeSnapshotData, MetricTile, SnapshotEnvelope } from "@frw/shared-types";
import { ExternalLink, LineChart, SlidersHorizontal, Table2, TrendingDown, TrendingUp } from "lucide-react";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

type CurveObservation = {
  date: string;
  value: number;
};

type CurvePoint = {
  key: string;
  label: string;
  years: number;
  value: number;
  updatedAt: string;
  source: string;
  sourceUrl?: string;
  freshness: MetricTile["freshness"];
  history: CurveObservation[];
};

type CurveSeries = {
  id: string;
  label: string;
  shortLabel: string;
  detail: string;
  color: string;
  latestDate: string | null;
  source: string;
  sourceUrl?: string;
  points: CurvePoint[];
};

type CurveViewKey = "compare" | "us-history" | "japan-history";

type CurveView = {
  key: CurveViewKey;
  label: string;
  detail: string;
  series: CurveSeries[];
};

type ChartSize = {
  width: number;
  height: number;
};

type HoveredCurvePoint = {
  id: string;
  curveLabel: string;
  point: CurvePoint;
  x: number;
  y: number;
  color: string;
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

const CURRENT_COLORS = ["#2f80ed", "#18c964", "#f59e0b", "#ec4899"] as const;
const HISTORY_COLORS = ["#2f80ed", "#18c964", "#f59e0b"] as const;
const TRADINGVIEW_ALL_CURVES_URL = "https://www.tradingview.com/markets/bonds/yield-curve-all/";
const TRADINGVIEW_US_CURVE_URL = "https://www.tradingview.com/markets/bonds/yield-curve-united-states/";
const TRADINGVIEW_JAPAN_CURVE_URL = "https://www.tradingview.com/markets/bonds/yield-curve-japan/";

export function YieldCurvesPage() { // NOSONAR - page coordinates snapshot-backed curve views, controls, and source panels.
  const locale = useLocale();
  const [activeViewKey, setActiveViewKey] = useState<CurveViewKey>("compare");
  const query = useQuery({
    queryKey: ["snapshot", "home", locale, "yield-curves"],
    queryFn: () => snapshotQueries.home(locale)
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <ErrorState error={query.error} />;

  const usCurve = buildCurve(query.data, US_TERMS);
  const japanCurve = buildCurve(query.data, JAPAN_TERMS);
  const comparisonDate = latestSharedObservationDate([usCurve, japanCurve]);
  const currentSeries = buildAlignedCurrentSeries(
    [
      {
        id: "us-current",
        label: localeText(locale, "USA", "미국"),
        shortLabel: "USA",
        detail: localeText(locale, "U.S. Treasury XML feed", "미국 재무부 XML 피드"),
        color: CURRENT_COLORS[0],
        points: usCurve
      },
      {
        id: "japan-current",
        label: localeText(locale, "Japan", "일본"),
        shortLabel: "Japan",
        detail: localeText(locale, "Japan MOF JGB yield curve", "일본 재무성 JGB 수익률 곡선"),
        color: CURRENT_COLORS[1],
        points: japanCurve
      }
    ],
    comparisonDate
  );
  const views: CurveView[] = [
    {
      key: "compare",
      label: localeText(locale, "Compare countries", "국가 비교"),
      detail: localeText(
        locale,
        comparisonDate
          ? `Latest common official observation date: ${comparisonDate}. The snapshot keeps up to 24 monthly points sampled from daily official observations.`
          : "No shared observation date is available yet, so the chart falls back to each country's latest official point.",
        comparisonDate
          ? `공통 공식 관측일: ${comparisonDate}. 스냅샷은 일별 공식 관측치에서 월별로 샘플링한 최대 24개 지점을 보관합니다.`
          : "아직 공통 관측일이 없어 각 국가의 최신 공식 지점으로 표시합니다."
      ),
      series: currentSeries
    },
    {
      key: "us-history",
      label: localeText(locale, "US 24m range", "미국 24개월 범위"),
      detail: localeText(
        locale,
        "Latest, about 12 months back, and the start of the 24-month monthly U.S. Treasury sample.",
        "미국 재무부 24개월 월별 샘플의 최신, 약 12개월 전, 시작 지점입니다."
      ),
      series: buildHistoricalSeries(locale, "us", localeText(locale, "USA", "미국"), usCurve)
    },
    {
      key: "japan-history",
      label: localeText(locale, "Japan 24m range", "일본 24개월 범위"),
      detail: localeText(
        locale,
        "Latest, about 12 months back, and the start of the 24-month monthly Japan MOF sample.",
        "일본 재무성 24개월 월별 샘플의 최신, 약 12개월 전, 시작 지점입니다."
      ),
      series: buildHistoricalSeries(locale, "japan", localeText(locale, "Japan", "일본"), japanCurve)
    }
  ];
  const activeView = views.find((view) => view.key === activeViewKey && view.series.length > 0)
    ?? views.find((view) => view.series.length > 0)
    ?? views[0];

  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="panel grid gap-5 p-4 md:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
              <LineChart className="h-4 w-4" />
              {localeText(locale, "Yield Curves", "수익률 곡선")}
            </div>
            <h1 className="safe-text mt-2 text-3xl font-bold leading-tight md:text-5xl">
              {localeText(locale, "Government Yield Curves", "국채 수익률 곡선")}
            </h1>
            <p className="safe-text mt-3 max-w-5xl text-sm leading-6 text-muted md:text-base md:leading-7">
              {localeText(
                locale,
                "Reconstructed from official daily rate feeds in the public snapshot. Country comparisons use the latest shared observation date when possible, and history views use monthly samples over the last 24 months.",
                "공개 스냅샷의 공식 일별 금리 피드에서 재구성합니다. 국가 비교는 가능한 경우 최신 공통 관측일을 사용하고, 이력 보기는 최근 24개월 월별 샘플을 사용합니다."
              )}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[520px]">
            <StatusPill label={localeText(locale, "US points", "미국 구간")} value={String(usCurve.length)} />
            <StatusPill label={localeText(locale, "Japan points", "일본 구간")} value={String(japanCurve.length)} />
            <StatusPill label={localeText(locale, "Shared date", "공통일")} value={comparisonDate ?? "n/a"} />
            <StatusPill label={localeText(locale, "Realtime", "실시간")} value={localeText(locale, "no", "아님")} />
          </div>
        </div>
      </section>

      <CurveWorkbench
        activeView={activeView}
        activeViewKey={activeViewKey}
        locale={locale}
        views={views}
        onActiveViewChange={setActiveViewKey}
      />

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <SpreadPanel title="US 10Y-2Y" points={usCurve} longLabel="10Y" shortLabel="2Y" />
        <SpreadPanel title="Japan 10Y-2Y" points={japanCurve} longLabel="10Y" shortLabel="2Y" />
        <CoveragePanel locale={locale} usCurve={usCurve} japanCurve={japanCurve} comparisonDate={comparisonDate} />
        <TradingViewReference locale={locale} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <CurvePanel
          title={localeText(locale, "US Treasury observations", "미국 국채 관측치")}
          detail={localeText(locale, "Source-backed 2Y, 3Y, 5Y, and 10Y tenors.", "공식 출처 기반 2년, 3년, 5년, 10년 구간입니다.")}
          points={usCurve}
        />
        <CurvePanel
          title={localeText(locale, "Japan government bond observations", "일본 국채 관측치")}
          detail={localeText(locale, "Source-backed 2Y, 5Y, and 10Y tenors.", "공식 출처 기반 2년, 5년, 10년 구간입니다.")}
          points={japanCurve}
        />
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
      freshness: tile.freshness,
      history: normalizeHistory(tile.points, tile.updated_at, value)
    });
  }
  return points.sort((left, right) => left.years - right.years);
}

function CurveWorkbench({
  activeView,
  activeViewKey,
  locale,
  views,
  onActiveViewChange
}: Readonly<{
  activeView: CurveView;
  activeViewKey: CurveViewKey;
  locale: string;
  views: CurveView[];
  onActiveViewChange: (view: CurveViewKey) => void;
}>) {
  return (
    <section className="panel min-w-0 overflow-hidden">
      <div className="grid gap-4 border-b border-line p-4 md:p-5 xl:grid-cols-[1fr_auto] xl:items-start">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <SlidersHorizontal className="h-4 w-4" />
            {localeText(locale, "Curve workbench", "곡선 워크벤치")}
          </div>
          <h2 className="safe-text mt-2 text-2xl font-bold md:text-3xl">{activeView.label}</h2>
          <p className="safe-text mt-2 max-w-4xl text-sm leading-6 text-muted">{activeView.detail}</p>
        </div>
        <div className="flex flex-wrap gap-2 xl:justify-end" role="tablist" aria-label={localeText(locale, "Curve views", "곡선 보기")}>
          {views.map((view) => {
            const isActive = view.key === activeView.key || (view.key === activeViewKey && activeView.series.length === 0);
            const disabled = view.series.length === 0;
            return (
              <button
                key={view.key}
                type="button"
                role="tab"
                aria-selected={isActive}
                disabled={disabled}
                className={`focus-ring inline-flex min-h-10 items-center rounded-md border px-3 text-sm font-semibold transition ${
                  isActive
                    ? "border-accent bg-accentSoft text-accent"
                    : "border-line bg-panelAlt text-muted hover:border-accent hover:text-ink"
                } disabled:cursor-not-allowed disabled:opacity-50`}
                onClick={() => onActiveViewChange(view.key)}
              >
                {view.label}
              </button>
            );
          })}
        </div>
      </div>
      {activeView.series.length > 0 ? (
        <>
          <YieldCurveChart series={activeView.series} />
          <CurveLegend series={activeView.series} />
          <CurveDataTable locale={locale} series={activeView.series} />
        </>
      ) : (
        <div className="grid min-h-[360px] place-items-center p-6 text-center text-sm leading-6 text-muted">
          {localeText(locale, "No source-backed curve points are available in this snapshot.", "이 스냅샷에는 출처 기반 수익률 곡선 구간이 없습니다.")}
        </div>
      )}
    </section>
  );
}

function CurvePanel({ title, detail, points }: Readonly<{ title: string; detail: string; points: CurvePoint[] }>) {
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

function YieldCurveChart({ series }: Readonly<{ series: CurveSeries[] }>) {
  const [chartRef, chartSize] = useMeasuredChartSize({ width: 1280, height: 460 });
  const [hoveredPoint, setHoveredPoint] = useState<HoveredCurvePoint | null>(null);
  const allPoints = series.flatMap((curve) => curve.points);
  const values = allPoints.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const yMin = Math.max(0, Math.floor((min - 0.2) * 4) / 4);
  const yMax = Math.ceil((max + 0.2) * 4) / 4;
  const width = Math.max(760, chartSize.width);
  const height = Math.max(360, chartSize.height);
  const padding = { top: 36, right: 164, bottom: 66, left: 64 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const minYears = Math.min(...allPoints.map((point) => point.years));
  const maxYears = Math.max(...allPoints.map((point) => point.years));
  const yearRange = Math.max(maxYears - minYears, 1);
  const range = yMax - yMin || 1;
  const tenorTicks = uniqueTenors(allPoints);
  const coordinate = (point: CurvePoint) => {
    const x = padding.left + ((point.years - minYears) / yearRange) * innerWidth;
    const y = padding.top + (1 - (point.value - yMin) / range) * innerHeight;
    return { ...point, x, y };
  };
  const plottedSeries = series.map((curve) => ({
    curve,
    coords: curve.points.map(coordinate)
  }));
  const endpointLabels = endpointLabelPositions(
    plottedSeries
      .map(({ curve, coords }) => {
        const endpoint = coords.at(-1);
        return endpoint ? { id: curve.id, y: endpoint.y } : null;
      })
      .filter((item): item is { id: string; y: number } => item != null),
    padding.top,
    height - padding.bottom
  );

  return (
    <div className="px-2 pt-3 md:px-5 md:pt-5">
      <div
        ref={chartRef}
        className="relative min-h-[360px] overflow-hidden bg-[#050b14]"
        style={{ height: "clamp(360px, 28vw, 500px)" }}
        onPointerLeave={() => setHoveredPoint(null)}
      >
      <svg
        className="block h-full w-full"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Yield curve comparison chart"
      >
        <rect x="0" y="0" width={width} height={height} fill="#050b14" />
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = padding.top + tick * innerHeight;
          const value = yMax - tick * range;
          return (
            <g key={tick}>
              <line x1={padding.left} x2={width - padding.right} y1={y} y2={y} stroke="rgba(147, 163, 183, 0.16)" />
              <text x={padding.left - 12} y={y + 5} textAnchor="end" fontSize="13" fill="#93a3b7">
                {value.toFixed(1)}%
              </text>
            </g>
          );
        })}
        {tenorTicks.map((tick) => {
          const x = padding.left + ((tick.years - minYears) / yearRange) * innerWidth;
          return (
            <g key={tick.label}>
              <line x1={x} x2={x} y1={padding.top} y2={height - padding.bottom} stroke="rgba(147, 163, 183, 0.08)" />
              <text x={x} y={height - 25} textAnchor="middle" fontSize="14" fontWeight="700" fill="#dfe8f5">
                {tick.label}
              </text>
            </g>
          );
        })}
        {plottedSeries.map(({ curve, coords }) => {
          const path = coords.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ");
          const endpoint = coords.at(-1);
          const labelY = endpointLabels.get(curve.id) ?? endpoint?.y ?? padding.top;
          return (
            <g key={curve.id}>
              <path d={path} fill="none" stroke={curve.color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="4" />
              {coords.map((point) => (
                <g
                  key={`${curve.id}-${point.key}`}
                  aria-label={`${curve.label} ${point.label} ${point.value.toFixed(2)}%`}
                  tabIndex={0}
                  onBlur={() => setHoveredPoint(null)}
                  onFocus={() => setHoveredPoint({ id: `${curve.id}-${point.key}`, curveLabel: curve.label, point, x: point.x, y: point.y, color: curve.color })}
                  onPointerEnter={() => setHoveredPoint({ id: `${curve.id}-${point.key}`, curveLabel: curve.label, point, x: point.x, y: point.y, color: curve.color })}
                >
                  <circle cx={point.x} cy={point.y} r="15" fill="transparent" />
                  {hoveredPoint?.id === `${curve.id}-${point.key}` ? (
                    <circle cx={point.x} cy={point.y} r="9" fill="none" stroke={curve.color} strokeWidth="2" opacity="0.55" />
                  ) : null}
                  <circle cx={point.x} cy={point.y} r={hoveredPoint?.id === `${curve.id}-${point.key}` ? "6.5" : "5.5"} fill={curve.color} stroke="#050b14" strokeWidth="2.5">
                    <title>{`${curve.label} ${point.label}: ${point.value.toFixed(2)}% as of ${point.updatedAt.slice(0, 10)}`}</title>
                  </circle>
                </g>
              ))}
              {endpoint ? (
                <text x={Math.min(endpoint.x + 14, width - padding.right + 24)} y={labelY + 5} fontSize="13" fontWeight="700" fill={curve.color}>
                  {curve.shortLabel}
                </text>
              ) : null}
            </g>
          );
        })}
        {hoveredPoint ? (
          <YieldCurveTooltip hoveredPoint={hoveredPoint} width={width} height={height} padding={padding} />
        ) : null}
      </svg>
      </div>
    </div>
  );
}

function YieldCurveTooltip({
  hoveredPoint,
  width,
  height,
  padding
}: Readonly<{
  hoveredPoint: HoveredCurvePoint;
  width: number;
  height: number;
  padding: { top: number; right: number; bottom: number; left: number };
}>) {
  const tooltipWidth = 210;
  const tooltipHeight = 82;
  const x = clamp(hoveredPoint.x + 16, padding.left, width - tooltipWidth - 12);
  const y = clamp(hoveredPoint.y - tooltipHeight - 14, 12, height - padding.bottom - tooltipHeight);
  const date = hoveredPoint.point.updatedAt.slice(0, 10);

  return (
    <g role="tooltip" aria-label={`${hoveredPoint.curveLabel} ${hoveredPoint.point.label} ${hoveredPoint.point.value.toFixed(2)}%`}>
      <line x1={hoveredPoint.x} x2={hoveredPoint.x} y1={padding.top} y2={height - padding.bottom} stroke={hoveredPoint.color} strokeOpacity="0.32" strokeDasharray="4 5" />
      <rect x={x} y={y} width={tooltipWidth} height={tooltipHeight} rx="8" fill="#121c2a" stroke="rgba(103, 216, 239, 0.6)" />
      <text x={x + 12} y={y + 24} fontSize="12" fontWeight="700" fill={hoveredPoint.color}>
        {hoveredPoint.curveLabel}
      </text>
      <text x={x + 12} y={y + 48} fontSize="16" fontWeight="800" fill="#dfe8f5">
        {hoveredPoint.point.label}: {hoveredPoint.point.value.toFixed(2)}%
      </text>
      <text x={x + 12} y={y + 68} fontSize="11" fontWeight="600" fill="#93a3b7">
        as of {date}
      </text>
    </g>
  );
}

function CurveLegend({ series }: Readonly<{ series: CurveSeries[] }>) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 px-4 pb-4 text-sm text-muted">
      {series.map((curve) => (
        <div key={curve.id} className="inline-flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: curve.color }} />
          <span>{curve.label}</span>
          {curve.latestDate ? <span className="text-xs text-muted">({curve.latestDate})</span> : null}
        </div>
      ))}
    </div>
  );
}

function CurveDataTable({ locale, series }: Readonly<{ locale: string; series: CurveSeries[] }>) {
  const tenors = uniqueTenors(series.flatMap((curve) => curve.points));
  return (
    <div className="border-t border-line p-4 md:p-5">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
        <Table2 className="h-4 w-4" />
        {localeText(locale, "Snapshot curve table", "스냅샷 곡선 표")}
      </div>
      <div className="overflow-x-auto rounded-md border border-line" data-allow-horizontal-scroll>
        <table className="min-w-[760px] w-full border-collapse text-sm">
          <thead className="bg-panelAlt text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-3 font-semibold">{localeText(locale, "Curve", "곡선")}</th>
              <th className="px-3 py-3 font-semibold">{localeText(locale, "As of", "기준일")}</th>
              {tenors.map((tenor) => (
                <th key={tenor.label} className="px-3 py-3 text-right font-semibold">{tenor.label}</th>
              ))}
              <th className="px-3 py-3 font-semibold">{localeText(locale, "Source", "출처")}</th>
            </tr>
          </thead>
          <tbody>
            {series.map((curve) => (
              <tr key={curve.id} className="border-t border-line">
                <td className="px-3 py-3 font-semibold">
                  <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full align-middle" style={{ backgroundColor: curve.color }} />
                  {curve.label}
                </td>
                <td className="px-3 py-3 text-muted">{curve.latestDate ?? "n/a"}</td>
                {tenors.map((tenor) => {
                  const point = curve.points.find((candidate) => candidate.label === tenor.label);
                  return (
                    <td key={tenor.label} className="px-3 py-3 text-right font-semibold">
                      {point ? `${point.value.toFixed(2)}%` : "-"}
                    </td>
                  );
                })}
                <td className="px-3 py-3 text-muted">
                  {curve.sourceUrl ? (
                    <a href={curve.sourceUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                      {curve.source}
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  ) : (
                    curve.source
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SpreadPanel({ title, points, longLabel, shortLabel }: Readonly<{ title: string; points: CurvePoint[]; longLabel: string; shortLabel: string }>) {
  const longPoint = points.find((point) => point.label === longLabel);
  const shortPoint = points.find((point) => point.label === shortLabel);
  const spread = longPoint && shortPoint ? longPoint.value - shortPoint.value : null;
  const inverted = spread != null && spread < 0;
  return (
    <section className="panel p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <SpreadIcon spread={spread} inverted={inverted} />
      </div>
      <div className={`mt-3 text-3xl font-bold ${inverted ? "text-warning" : "text-success"}`}>
        {spread == null ? "n/a" : `${(spread * 100).toFixed(0)} bp`}
      </div>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">
        {spreadDescription(spread, inverted)}
      </p>
    </section>
  );
}

function CoveragePanel({
  comparisonDate,
  locale,
  usCurve,
  japanCurve
}: Readonly<{ comparisonDate: string | null; locale: string; usCurve: CurvePoint[]; japanCurve: CurvePoint[] }>) {
  const usMonths = monthlyCoverageCount(usCurve);
  const japanMonths = monthlyCoverageCount(japanCurve);

  return (
    <section className="panel p-4">
      <h2 className="text-base font-semibold">{localeText(locale, "Snapshot coverage", "스냅샷 커버리지")}</h2>
      <dl className="mt-3 grid gap-3 text-sm">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted">{localeText(locale, "Common date", "공통일")}</dt>
          <dd className="font-semibold">{comparisonDate ?? "n/a"}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted">USA</dt>
          <dd className="font-semibold">{usMonths} {localeText(locale, "months", "개월")}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted">Japan</dt>
          <dd className="font-semibold">{japanMonths} {localeText(locale, "months", "개월")}</dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-muted">{localeText(locale, "History mode", "이력 보기")}</dt>
          <dd className="font-semibold">{localeText(locale, "monthly sample", "월별 샘플")}</dd>
        </div>
      </dl>
    </section>
  );
}

function TradingViewReference({ locale }: Readonly<{ locale: string }>) {
  return (
    <section className="panel p-4">
      <h2 className="text-base font-semibold">{localeText(locale, "TradingView reference", "TradingView 참고")}</h2>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">
        {localeText(
          locale,
          "TradingView's yield-curve product is linked as an external reference. The in-page chart stays native because official embeddable widgets are symbol-chart oriented.",
          "TradingView 수익률 곡선 제품은 외부 참고 링크로 제공합니다. 공식 임베드 위젯은 심볼 차트 중심이므로 앱 내 차트는 네이티브로 유지합니다."
        )}
      </p>
      <div className="mt-4 grid gap-2">
        <a href={TRADINGVIEW_ALL_CURVES_URL} target="_blank" rel="noreferrer" className="secondary-action justify-center">
          <ExternalLink className="h-4 w-4" />
          {localeText(locale, "Open global curves", "글로벌 곡선 열기")}
        </a>
        <div className="grid grid-cols-2 gap-2">
          <a href={TRADINGVIEW_US_CURVE_URL} target="_blank" rel="noreferrer" className="secondary-action justify-center px-2 text-xs">
            USA
          </a>
          <a href={TRADINGVIEW_JAPAN_CURVE_URL} target="_blank" rel="noreferrer" className="secondary-action justify-center px-2 text-xs">
            Japan
          </a>
        </div>
      </div>
    </section>
  );
}

function SpreadIcon({ spread, inverted }: Readonly<{ spread: number | null; inverted: boolean }>) {
  if (spread == null) return null;
  if (inverted) return <TrendingDown className="h-5 w-5 text-warning" />;
  return <TrendingUp className="h-5 w-5 text-success" />;
}

function useMeasuredChartSize(fallback: ChartSize) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;

    const applySize = () => {
      const rect = element.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setSize({ width: Math.round(rect.width), height: Math.round(rect.height) });
      }
    };

    applySize();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", applySize);
      return () => window.removeEventListener("resize", applySize);
    }

    const observer = new ResizeObserver(applySize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, size] as const;
}

function endpointLabelPositions(endpoints: { id: string; y: number }[], minY: number, maxY: number) {
  const sorted = [...endpoints]
    .map((endpoint) => ({ ...endpoint, labelY: clamp(endpoint.y, minY + 14, maxY - 14) }))
    .sort((left, right) => left.labelY - right.labelY);
  const minGap = 18;

  for (let index = 1; index < sorted.length; index += 1) {
    sorted[index].labelY = Math.max(sorted[index].labelY, sorted[index - 1].labelY + minGap);
  }
  for (let index = sorted.length - 2; index >= 0; index -= 1) {
    sorted[index].labelY = Math.min(sorted[index].labelY, sorted[index + 1].labelY - minGap);
  }

  return new Map(sorted.map((endpoint) => [endpoint.id, clamp(endpoint.labelY, minY + 14, maxY - 14)]));
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function spreadDescription(spread: number | null, inverted: boolean) {
  if (spread == null) return "Spread cannot be computed until both curve points are present.";
  if (inverted) return "Curve is inverted at this spread.";
  return "Curve is positively sloped at this spread.";
}

function StatusPill({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="rounded-md border border-line bg-panelAlt px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="safe-text mt-1 text-sm font-bold text-ink">{value}</div>
    </div>
  );
}

function parseMetricValue(value: string) {
  const normalized = /-?\d+(?:\.\d+)?/.exec(value.replaceAll(",", ""));
  if (!normalized) return null;
  const parsed = Number(normalized[0]);
  return Number.isFinite(parsed) ? parsed : null;
}

function latestDate(points: CurvePoint[]) {
  return (
    points
      .map((point) => point.updatedAt?.slice(0, 10))
      .filter((date): date is string => Boolean(date))
      .sort((left, right) => left.localeCompare(right))
      .at(-1) ?? null
  );
}

function localeText(locale: string, en: string, ko: string) {
  return locale === "ko" ? ko : en;
}

function normalizeHistory(points: MetricTile["points"], fallbackUpdatedAt: string, fallbackValue: number): CurveObservation[] {
  const history = (points ?? [])
    .filter((point) => point.date && Number.isFinite(point.value))
    .map((point) => ({ date: point.date, value: point.value }))
    .sort((left, right) => left.date.localeCompare(right.date));
  const fallbackDate = fallbackUpdatedAt.slice(0, 10);
  if (!history.some((point) => point.date === fallbackDate)) {
    history.push({ date: fallbackDate, value: fallbackValue });
    history.sort((left, right) => left.date.localeCompare(right.date));
  }
  return history;
}

type CurrentCurveConfig = Readonly<{
  id: string;
  label: string;
  shortLabel: string;
  detail: string;
  color: string;
  points: CurvePoint[];
}>;

function buildCurrentSeries({
  id,
  label,
  shortLabel,
  detail,
  color,
  points
}: CurrentCurveConfig): CurveSeries | null {
  if (points.length < 2) return null;
  return {
    id,
    label,
    shortLabel,
    detail,
    color,
    latestDate: latestDate(points),
    source: sourceSummary(points),
    sourceUrl: points.find((point) => point.sourceUrl)?.sourceUrl,
    points
  };
}

function buildAlignedCurrentSeries(configs: CurrentCurveConfig[], date: string | null): CurveSeries[] {
  return configs
    .map((config) => (date ? buildCurrentSeriesAtDate(config, date) : buildCurrentSeries(config)))
    .filter(isCurveSeries);
}

function buildCurrentSeriesAtDate(config: CurrentCurveConfig, date: string): CurveSeries | null {
  const points = curvePointsAtDate(config.points, date);
  if (points.length < 2) return null;
  return {
    id: config.id,
    label: config.label,
    shortLabel: config.shortLabel,
    detail: config.detail,
    color: config.color,
    latestDate: date,
    source: sourceSummary(points),
    sourceUrl: points.find((point) => point.sourceUrl)?.sourceUrl,
    points
  };
}

function buildHistoricalSeries(locale: string, idPrefix: string, countryLabel: string, points: CurvePoint[]): CurveSeries[] {
  if (points.length < 2) return [];
  const dates = commonObservationDates(points);
  if (dates.length === 0) return [];
  const selectedDates = selectedHistoryDates(dates);
  const labels = [
    localeText(locale, "Latest", "최신"),
    localeText(locale, "About 12m ago", "약 12개월 전"),
    localeText(locale, "Window start", "구간 시작")
  ];
  return selectedDates.map((date, index) => {
    const curvePoints = curvePointsAtDate(points, date);
    return {
      id: `${idPrefix}-${date}`,
      label: `${countryLabel} ${labels[index] ?? date}`,
      shortLabel: labels[index] ?? date,
      detail: countryLabel,
      color: HISTORY_COLORS[index] ?? "#67d8ef",
      latestDate: date,
      source: sourceSummary(curvePoints),
      sourceUrl: curvePoints.find((point) => point.sourceUrl)?.sourceUrl,
      points: curvePoints
    };
  });
}

function isCurveSeries(series: CurveSeries | null): series is CurveSeries {
  return series != null;
}

function latestSharedObservationDate(curves: CurvePoint[][]) {
  const dateSets = curves
    .filter((curve) => curve.length >= 2)
    .map((curve) => new Set(commonObservationDates(curve)));
  if (dateSets.length < 2) return null;
  const [firstSet, ...restSets] = dateSets;
  return (
    [...firstSet]
      .filter((date) => restSets.every((set) => set.has(date)))
      .sort((left, right) => left.localeCompare(right))
      .at(-1) ?? null
  );
}

function curvePointsAtDate(points: CurvePoint[], date: string) {
  return points
    .map((point) => {
      const observation = point.history.find((candidate) => candidate.date === date);
      return observation ? { ...point, value: observation.value, updatedAt: `${date}T00:00:00Z` } : null;
    })
    .filter((point): point is CurvePoint => point != null);
}

function commonObservationDates(points: CurvePoint[]) {
  const [firstPoint, ...rest] = points;
  if (!firstPoint) return [];
  return firstPoint.history
    .map((point) => point.date)
    .filter((date) => rest.every((point) => point.history.some((candidate) => candidate.date === date)))
    .sort((left, right) => left.localeCompare(right));
}

function selectedHistoryDates(dates: string[]) {
  const latest = dates.at(-1);
  const earliest = dates[0];
  const oneYearBack = latest ? closestDateOnOrBefore(dates, addDays(latest, -365)) : undefined;
  return uniqueStrings([latest, oneYearBack, earliest]);
}

function closestDateOnOrBefore(dates: string[], target: string) {
  return dates.filter((date) => date <= target).at(-1) ?? dates[0];
}

function addDays(date: string, days: number) {
  const parsed = new Date(`${date}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

function monthlyCoverageCount(points: CurvePoint[]) {
  if (points.length === 0) return 0;
  return Math.min(...points.map((point) => new Set(point.history.map((observation) => observation.date.slice(0, 7))).size));
}

function uniqueStrings(values: (string | undefined)[]) {
  return values.filter((value, index): value is string => Boolean(value) && values.indexOf(value) === index);
}

function uniqueTenors(points: CurvePoint[]) {
  const tenors = new Map<string, { label: string; years: number }>();
  for (const point of points) {
    tenors.set(point.label, { label: point.label, years: point.years });
  }
  return [...tenors.values()].sort((left, right) => left.years - right.years);
}

function sourceSummary(points: CurvePoint[]) {
  const sources = [...new Set(points.map((point) => point.source).filter(Boolean))];
  if (sources.length === 0) return "Snapshot";
  if (sources.length === 1) return sources[0];
  return "Multiple official sources";
}
