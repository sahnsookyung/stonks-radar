import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, GitCompare, Plus, X } from "lucide-react";
import { getPrivateHistory, getTickerFundamentals, type PrivateHistoryResponse, type TickerFundamentals } from "../../lib/tickerApi";
import { getTrackedTicker, searchTrackedTickers } from "../../lib/trackedTickers";

export function TickerComparisonPanel({
  symbols,
  locale,
  isSignedIn,
  onSymbolsChange
}: Readonly<{
  symbols: string[];
  locale: "en" | "ko";
  isSignedIn: boolean;
  onSymbolsChange: (symbols: string[]) => void;
}>) {
  const isKo = locale === "ko";
  const [query, setQuery] = useState("");
  const normalizedSymbols = Array.from(new Set(symbols.map((symbol) => symbol.toUpperCase()))).slice(0, 4);
  const suggestions = useMemo(() => searchTrackedTickers(query, 8).filter((ticker) => !normalizedSymbols.includes(ticker.symbol)), [normalizedSymbols, query]);
  const fundamentalsQuery = useQuery({
    queryKey: ["ticker-comparison-fundamentals", normalizedSymbols],
    queryFn: ({ signal }) => Promise.all(normalizedSymbols.map((symbol) => getTickerFundamentals(symbol, signal))),
    enabled: normalizedSymbols.length > 0,
    retry: 1
  });
  const range = useMemo(() => comparisonRange(), []);
  const historyQuery = useQuery({
    queryKey: ["ticker-comparison-private-history", normalizedSymbols, range.from, range.to],
    queryFn: ({ signal }) => Promise.all(normalizedSymbols.map((symbol) => getPrivateHistory(symbol, range.from, range.to, signal))),
    enabled: isSignedIn && normalizedSymbols.length > 0,
    retry: false
  });

  function add(symbol: string) {
    if (normalizedSymbols.length >= 4) return;
    onSymbolsChange([...normalizedSymbols, symbol]);
    setQuery("");
  }

  return (
    <section className="panel p-5" aria-labelledby="ticker-comparison-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="ticker-comparison-heading" className="flex items-center gap-2 text-lg font-bold"><GitCompare className="h-5 w-5 text-accent" />{isKo ? "티커 비교" : "Ticker Comparison"}</h2>
          <p className="mt-1 text-sm leading-6 text-muted">{isKo ? "URL의 compare 상태로 최대 네 개 심볼을 공유합니다." : "Share up to four symbols through the URL compare state."}</p>
        </div>
        <span className="badge border-line bg-panelAlt text-muted">{normalizedSymbols.length}/4</span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {normalizedSymbols.map((symbol) => <span key={symbol} className="inline-flex min-h-11 items-center gap-1 rounded-md border border-accent/40 bg-accentSoft pl-3 font-semibold text-accent">{symbol}<button type="button" className="focus-ring grid min-h-11 min-w-11 place-items-center rounded" aria-label={`${isKo ? "비교에서 제거" : "Remove from comparison"} ${symbol}`} onClick={() => onSymbolsChange(normalizedSymbols.filter((item) => item !== symbol))}><X className="h-4 w-4" /></button></span>)}
      </div>
      {normalizedSymbols.length < 4 ? (
        <div className="relative mt-4 max-w-lg">
          <label htmlFor="ticker-comparison-search" className="grid gap-1 text-xs font-semibold uppercase text-muted">{isKo ? "비교 심볼 추가" : "Add comparison symbol"}<input id="ticker-comparison-search" className="input-control min-h-11" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={isKo ? "심볼 또는 회사 검색" : "Search symbol or company"} autoComplete="off" /></label>
          {query.trim() ? <div className="absolute z-10 mt-1 w-full rounded-md border border-line bg-panel p-1 shadow-xl" role="listbox" aria-label={isKo ? "비교 검색 결과" : "Comparison search results"}>{suggestions.length ? suggestions.map((ticker) => <button key={ticker.symbol} type="button" role="option" aria-selected="false" className="focus-ring flex min-h-11 w-full items-center justify-between rounded px-3 text-left hover:bg-panelAlt" onClick={() => add(ticker.symbol)}><span><span className="font-semibold">{ticker.displaySymbol}</span><span className="ml-2 text-xs text-muted">{ticker.name}</span></span><Plus className="h-4 w-4" /></button>) : <div className="p-3 text-sm text-muted">{isKo ? "일치하는 추적 티커가 없습니다." : "No tracked ticker matches."}</div>}</div> : null}
        </div>
      ) : null}

      {fundamentalsQuery.isLoading ? <State text={isKo ? "공식 펀더멘털을 불러오는 중입니다." : "Loading official fundamentals."} /> : null}
      {fundamentalsQuery.isError ? <State tone="danger" text={isKo ? "비교용 펀더멘털을 읽지 못했습니다." : "Comparison fundamentals are unavailable."} /> : null}
      {fundamentalsQuery.data ? <FundamentalsTable rows={fundamentalsQuery.data} locale={locale} /> : null}

      {!isSignedIn ? <State text={isKo ? "공개 사용자는 공식 펀더멘털과 공급자 소유 차트를 볼 수 있습니다. 정규화 성과와 기술 비교는 로그인 및 검증된 개인 연결이 필요합니다." : "Public users receive official fundamentals and provider-owned charts. Normalized performance and technical comparisons require sign-in and a verified private connection."} /> : null}
      {isSignedIn && historyQuery.isLoading ? <State text={isKo ? "개인 지연 이력을 불러오는 중입니다." : "Loading private delayed history."} /> : null}
      {isSignedIn && historyQuery.isError ? <State tone="warning" text={isKo ? "검증된 개인 공급자 연결이 없어 성과 비교를 표시할 수 없습니다." : "Performance comparison needs a verified private provider connection."} /> : null}
      {historyQuery.data ? <PerformanceTable rows={historyQuery.data} locale={locale} /> : null}

      <div className="mt-5 flex flex-wrap gap-2">{normalizedSymbols.map((symbol) => { const ticker = getTrackedTicker(symbol); return ticker ? <a key={symbol} className="secondary-action" target="_blank" rel="noreferrer" href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ticker.tradingViewSymbol)}`}><ExternalLink className="h-4 w-4" />{symbol} TradingView</a> : null; })}</div>
    </section>
  );
}

function FundamentalsTable({ rows, locale }: Readonly<{ rows: TickerFundamentals[]; locale: "en" | "ko" }>) {
  const fields: Array<[keyof TickerFundamentals["metrics"], string]> = [["revenue", locale === "ko" ? "매출" : "Revenue"], ["revenue_growth", locale === "ko" ? "성장률" : "Growth"], ["operating_margin", locale === "ko" ? "영업이익률" : "Operating margin"], ["net_income", locale === "ko" ? "순이익" : "Net income"], ["free_cash_flow", "FCF"], ["cash", locale === "ko" ? "현금" : "Cash"], ["debt", locale === "ko" ? "부채" : "Debt"]];
  return <div className="table-surface mt-5" data-allow-horizontal-scroll aria-label={locale === "ko" ? "공식 펀더멘털 비교 표" : "Official fundamentals comparison table"}><table className="min-w-full text-left text-sm"><caption className="sr-only">{locale === "ko" ? "공식 펀더멘털 비교" : "Official fundamentals comparison"}</caption><thead className="table-head"><tr><th scope="col" className="px-3 py-3">Metric</th>{rows.map((row) => <th key={row.symbol} scope="col" className="px-3 py-3">{row.symbol}<span className="ml-2 text-xs text-muted">{row.status}</span></th>)}</tr></thead><tbody>{fields.map(([key, label]) => <tr key={key} className="border-t border-line"><th scope="row" className="px-3 py-3">{label}</th>{rows.map((row) => <td key={row.symbol} className="px-3 py-3">{formatMetric(row.metrics[key])}</td>)}</tr>)}</tbody></table></div>;
}

function PerformanceTable({ rows, locale }: Readonly<{ rows: PrivateHistoryResponse[]; locale: "en" | "ko" }>) {
  const metrics = rows.map(comparisonMetrics);
  return <div className="table-surface mt-5" data-allow-horizontal-scroll aria-label={locale === "ko" ? "개인 지연 이력 성과 비교 표" : "Private delayed-history performance comparison table"}><table className="min-w-full text-left text-sm"><caption className="sr-only">{locale === "ko" ? "개인 지연 이력 성과 비교" : "Private delayed-history performance comparison"}</caption><thead className="table-head"><tr><th scope="col" className="px-3 py-3">Metric</th>{metrics.map((row) => <th key={row.symbol} scope="col" className="px-3 py-3">{row.symbol}</th>)}</tr></thead><tbody><ComparisonRow label={locale === "ko" ? "기간 수익률" : "Period return"} rows={metrics.map((row) => row.returnPct)} percent /><ComparisonRow label="RSI (14)" rows={metrics.map((row) => row.rsi)} /><ComparisonRow label={locale === "ko" ? "50일선 대비" : "vs 50-day average"} rows={metrics.map((row) => row.vsAverage)} percent /><ComparisonRow label={locale === "ko" ? "데이터 행" : "Data points"} rows={metrics.map((row) => row.count)} /></tbody></table></div>;
}

function ComparisonRow({ label, rows, percent = false }: Readonly<{ label: string; rows: number[]; percent?: boolean }>) { return <tr className="border-t border-line"><th scope="row" className="px-3 py-3">{label}</th>{rows.map((value, index) => <td key={`${label}-${index}`} className="px-3 py-3">{Number.isFinite(value) ? `${value.toFixed(2)}${percent ? "%" : ""}` : "—"}</td>)}</tr>; }
function comparisonMetrics(row: PrivateHistoryResponse) { const closes = row.points.map((point) => Number(point.close)).filter(Number.isFinite); const first = closes[0]; const last = closes.at(-1); const average = closes.slice(-50).reduce((total, value) => total + value, 0) / Math.min(50, closes.length); return { symbol: row.symbol, count: closes.length, returnPct: first && last ? ((last - first) / first) * 100 : Number.NaN, rsi: rsi14(closes), vsAverage: last && average ? ((last - average) / average) * 100 : Number.NaN }; }
function rsi14(values: number[]) { if (values.length < 15) return Number.NaN; let gains = 0; let losses = 0; for (let index = values.length - 14; index < values.length; index += 1) { const change = values[index] - values[index - 1]; if (change > 0) gains += change; else losses -= change; } if (losses === 0) return 100; const rs = gains / losses; return 100 - 100 / (1 + rs); }
function comparisonRange() { const to = new Date(); const from = new Date(to); from.setUTCFullYear(from.getUTCFullYear() - 1); return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) }; }
function formatMetric(value: unknown) { const number = Number(value); return Number.isFinite(number) ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(number) : "—"; }
function State({ text, tone = "muted" }: Readonly<{ text: string; tone?: "muted" | "warning" | "danger" }>) { const className = tone === "danger" ? "signal-danger" : tone === "warning" ? "signal-warning" : "border-line bg-panelAlt text-muted"; return <div className={`mt-5 rounded-md border p-4 text-sm leading-6 ${className}`}>{text}</div>; }
