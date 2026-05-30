import { useMemo, useState } from "react";
import { Activity, AlertTriangle, ArrowRight, Calculator, DatabaseZap, Info, Plus, Trash2 } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import {
  type HoldingWeight,
  type PriceSeries,
  computePortfolioStats,
  normalizeWeights
} from "../lib/portfolio";
import { useLocale } from "../lib/locale";

interface HoldingRow {
  id: string;
  symbol: string;
  weight: number;
}

interface MarketHistoryResponse {
  status: "ok";
  provider: string;
  source_note: string;
  cache: "hit" | "miss";
  series: PriceSeries[];
  warnings: string[];
}

const sampleSeries: PriceSeries[] = [
  {
    symbol: "AAPL",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-01-03", close: 101.5 },
      { date: "2026-01-04", close: 100.4 },
      { date: "2026-01-05", close: 103.1 },
      { date: "2026-01-06", close: 102.7 },
      { date: "2026-01-07", close: 105.2 },
      { date: "2026-01-08", close: 104.8 }
    ]
  },
  {
    symbol: "MSFT",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-01-03", close: 100.6 },
      { date: "2026-01-04", close: 101.4 },
      { date: "2026-01-05", close: 102.6 },
      { date: "2026-01-06", close: 101.8 },
      { date: "2026-01-07", close: 103.4 },
      { date: "2026-01-08", close: 104.1 }
    ]
  },
  {
    symbol: "TLT",
    points: [
      { date: "2026-01-02", close: 100 },
      { date: "2026-01-03", close: 99.8 },
      { date: "2026-01-04", close: 100.2 },
      { date: "2026-01-05", close: 99.6 },
      { date: "2026-01-06", close: 100.4 },
      { date: "2026-01-07", close: 100.1 },
      { date: "2026-01-08", close: 100.9 }
    ]
  }
];

const formulaCards = [
  {
    title: "Sharpe ratio",
    formula: "(annual return - risk-free rate) / annual volatility",
    use: "Risk-adjusted return when upside and downside volatility are both treated as risk."
  },
  {
    title: "Sortino ratio",
    formula: "(annual return - target return) / downside deviation",
    use: "Better when you care more about bad volatility than upside volatility."
  },
  {
    title: "Max drawdown",
    formula: "lowest portfolio equity / prior peak - 1",
    use: "Shows the worst peak-to-trough loss over the selected history."
  },
  {
    title: "Free cash flow yield",
    formula: "free cash flow / market capitalization",
    use: "A compact valuation sanity check for cash-generative businesses."
  },
  {
    title: "ROIC spread",
    formula: "return on invested capital - weighted average cost of capital",
    use: "Useful for judging whether growth is creating or destroying value."
  },
  {
    title: "Altman Z / Beneish M",
    formula: "multi-factor bankruptcy / earnings-manipulation screens",
    use: "High-leverage forensic screens before reading filings line by line."
  }
];

export function PortfolioLabPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const [defaultDates] = useState(defaultDateRange);
  const [holdings, setHoldings] = useState<HoldingRow[]>([
    { id: "aapl", symbol: "AAPL", weight: 45 },
    { id: "msft", symbol: "MSFT", weight: 35 },
    { id: "tlt", symbol: "TLT", weight: 20 }
  ]);
  const [start, setStart] = useState(defaultDates.start);
  const [end, setEnd] = useState(defaultDates.end);
  const [riskFree, setRiskFree] = useState(4.5);
  const [target, setTarget] = useState(0);
  const [marketData, setMarketData] = useState<MarketHistoryResponse>({
    status: "ok",
    provider: "sample",
    source_note: "Illustrative sample only. Fetch live data after provider credentials are configured.",
    cache: "miss",
    series: sampleSeries,
    warnings: ["Sample data is not market data and must not be used for decisions."]
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const weights: HoldingWeight[] = holdings.map((item) => ({ symbol: item.symbol, weight: item.weight }));
  const stats = useMemo(
    () => computePortfolioStats(marketData.series, weights, riskFree / 100, target / 100),
    [holdings, marketData, riskFree, target]
  );
  const normalizedWeights = normalizeWeights(weights);

  async function fetchLiveData() {
    setLoading(true);
    setError(null);
    try {
      const symbols = holdings.map((item) => item.symbol.trim().toUpperCase()).filter(Boolean).join(",");
      const url = new URL("/api/public/market/history", window.location.origin);
      url.searchParams.set("symbols", symbols);
      url.searchParams.set("start", start);
      url.searchParams.set("end", end);
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = payload?.detail;
        throw new Error(typeof detail === "string" ? detail : detail?.message ?? `Request failed: ${response.status}`);
      }
      setMarketData(payload as MarketHistoryResponse);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to load market data");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-w-0 gap-7">
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <Calculator className="h-4 w-4" />
            {isKo ? "포트폴리오 실험실" : "Portfolio lab"}
          </div>
          <h1 className="safe-text mt-3 max-w-4xl text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">
            {isKo ? "샤프와 소르티노를 즉시 계산" : "Sharpe and Sortino, without spreadsheet fog"}
          </h1>
          <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted md:text-lg md:leading-8">
            {isKo
              ? "티커, 비중, 기간, 무위험 수익률을 입력하면 서버측 시장 데이터 프록시 또는 예시 데이터로 리스크 조정 성과를 계산합니다."
              : "Enter tickers, weights, dates, and a risk-free rate. The tool uses the server-side market-data proxy when keys are configured, with an explicit sample mode until then."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <FreshnessBadge value={marketData.provider === "sample" ? "watch" : "fresh"} />
          <SourceBadge label={`provider: ${marketData.provider}`} />
          <SourceBadge label={`cache: ${marketData.cache}`} />
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-2">
        <Link
          to="/$locale/funds/$fundKey"
          params={{ locale, fundKey: "situational-awareness" }}
          className="focus-ring panel grid min-h-32 gap-2 p-5 hover:border-accent"
        >
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
            <DatabaseZap className="h-4 w-4" />
            {isKo ? "공개 13F 포트폴리오" : "Public 13F portfolio"}
          </div>
          <h2 className="safe-text text-xl font-bold">
            {isKo ? "레오폴드 아셴브레너 / Situational Awareness" : "Leopold Aschenbrenner / Situational Awareness"}
          </h2>
          <p className="safe-text text-sm leading-6 text-muted">
            {isKo
              ? "SEC EDGAR XML 정보표에서 지연 분기 보유 종목을 재구성합니다."
              : "Reconstructs delayed quarterly holdings from SEC EDGAR XML information tables."}
          </p>
          <span className="inline-flex items-center gap-2 text-sm font-semibold text-accent">
            {isKo ? "열기" : "Open"}
            <ArrowRight className="h-4 w-4" />
          </span>
        </Link>
        <Link
          to="/$locale/trump-filings"
          params={{ locale }}
          className="focus-ring panel grid min-h-32 gap-2 p-5 hover:border-accent"
        >
          <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
            <Info className="h-4 w-4" />
            {isKo ? "공개 공시 데이터베이스" : "Public disclosure database"}
          </div>
          <h2 className="safe-text text-xl font-bold">{isKo ? "트럼프 공개 주식 공시" : "Trump public stock disclosures"}</h2>
          <p className="safe-text text-sm leading-6 text-muted">
            {isKo
              ? "SEC/OGE 원문 연결 거래 행과 재구성 한계를 같이 표시합니다."
              : "Shows source-linked SEC/OGE transaction rows with reconstruction limits kept visible."}
          </p>
          <span className="inline-flex items-center gap-2 text-sm font-semibold text-accent">
            {isKo ? "열기" : "Open"}
            <ArrowRight className="h-4 w-4" />
          </span>
        </Link>
      </section>

      <section className="grid min-w-0 gap-5 xl:grid-cols-[minmax(360px,0.85fr)_minmax(0,1.15fr)]">
        <div className="grid min-w-0 gap-4">
          <div className="panel p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">{isKo ? "보유 종목" : "Holdings"}</h2>
                <p className="mt-1 text-xs leading-5 text-muted">
                  {isKo ? "비중은 자동으로 100%로 정규화됩니다." : "Weights are normalized to 100% automatically."}
                </p>
              </div>
              <button
                type="button"
                className="secondary-action min-h-11 px-3 py-2"
                onClick={() =>
                  setHoldings((items) => [
                    ...items,
                    { id: crypto.randomUUID(), symbol: "", weight: 0 }
                  ])
                }
              >
                <Plus className="h-4 w-4" />
                {isKo ? "추가" : "Add"}
              </button>
            </div>
            <div className="grid gap-3">
              {holdings.map((holding) => (
                <div key={holding.id} className="grid grid-cols-[minmax(0,1fr)_88px_44px] gap-2 sm:grid-cols-[minmax(0,1fr)_96px_44px]">
                  <input
                    className="input-control"
                    value={holding.symbol}
                    aria-label="Ticker symbol"
                    onChange={(event) =>
                      setHoldings((items) =>
                        items.map((item) =>
                          item.id === holding.id ? { ...item, symbol: event.target.value.toUpperCase() } : item
                        )
                      )
                    }
                  />
                  <input
                    className="input-control"
                    type="number"
                    min="0"
                    value={holding.weight}
                    aria-label="Portfolio weight"
                    onChange={(event) =>
                      setHoldings((items) =>
                        items.map((item) =>
                          item.id === holding.id ? { ...item, weight: Number(event.target.value) } : item
                        )
                      )
                    }
                  />
                  <button
                    type="button"
                    className="secondary-action h-11 min-w-11 px-0 py-0"
                    aria-label="Remove holding"
                    onClick={() => setHoldings((items) => items.filter((item) => item.id !== holding.id))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="panel p-5">
            <h2 className="font-semibold">{isKo ? "데이터와 가정" : "Data and assumptions"}</h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
                Start
                <input className="input-control" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
                End
                <input className="input-control" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
                Risk-free %
                <input className="input-control" type="number" step="0.1" value={riskFree} onChange={(event) => setRiskFree(Number(event.target.value))} />
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase text-muted">
                Sortino target %
                <input className="input-control" type="number" step="0.1" value={target} onChange={(event) => setTarget(Number(event.target.value))} />
              </label>
            </div>
            <button type="button" className="primary-action mt-4 w-full" disabled={loading} onClick={fetchLiveData}>
              <DatabaseZap className="h-4 w-4" />
              {loading ? (isKo ? "불러오는 중" : "Fetching") : isKo ? "시장 데이터 가져오기" : "Fetch market data"}
            </button>
            {error ? (
              <div className="signal-warning mt-4 flex min-w-0 gap-2 px-4 py-3 text-sm leading-6">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span className="safe-text min-w-0">{error}. Configure `TWELVE_DATA_API_KEY`, `ALPHA_VANTAGE_API_KEY`, or `FMP_API_KEY` to enable live history.</span>
              </div>
            ) : null}
          </div>
        </div>

        <div className="grid min-w-0 gap-4">
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Sharpe" value={formatRatio(stats?.sharpeRatio)} />
            <Metric label="Sortino" value={formatRatio(stats?.sortinoRatio)} />
            <Metric label="Annual return" value={formatPercent(stats?.annualizedReturn)} />
            <Metric label="Max drawdown" value={formatPercent(stats?.maxDrawdown)} tone="risk" />
          </section>

          <section className="panel p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-lg font-semibold">{isKo ? "계산 결과" : "Calculation detail"}</h2>
                <p className="safe-text mt-1 text-sm leading-6 text-muted">{marketData.source_note}</p>
              </div>
              {stats ? <SourceBadge label={`${stats.observationCount} aligned returns`} /> : <FreshnessBadge value="unsupported" />}
            </div>
            {marketData.warnings.length ? (
              <div className="mt-4 flex min-w-0 gap-2 rounded-md border border-line bg-panelAlt px-4 py-3 text-sm leading-6 text-muted">
                <Info className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <span className="safe-text min-w-0">{marketData.warnings.join(" ")}</span>
              </div>
            ) : null}
            <div className="mt-5 grid gap-2 md:hidden">
              {holdings.map((holding) => {
                const symbol = holding.symbol.trim().toUpperCase();
                const asset = stats?.assetReturns.find((item) => item.symbol === symbol);
                return (
                  <article key={holding.id} className="rounded-md border border-line bg-panelAlt p-3">
                    <div className="safe-text text-sm font-semibold">{symbol || "n/a"}</div>
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs leading-5 text-muted">
                      <div>
                        <div className="font-semibold uppercase">Weight</div>
                        <div className="text-ink">{formatPercent(normalizedWeights.get(symbol))}</div>
                      </div>
                      <div>
                        <div className="font-semibold uppercase">Return</div>
                        <div className="text-ink">{formatPercent(asset?.cumulativeReturn)}</div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="mt-5 hidden overflow-x-auto md:block" data-allow-horizontal-scroll aria-label="Portfolio calculation detail table">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs uppercase text-muted">
                  <tr>
                    <th className="py-2 pr-3">Ticker</th>
                    <th className="py-2 pr-3">Weight</th>
                    <th className="py-2 pr-3">Period return</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {holdings.map((holding) => {
                    const symbol = holding.symbol.trim().toUpperCase();
                    const asset = stats?.assetReturns.find((item) => item.symbol === symbol);
                    return (
                      <tr key={holding.id}>
                        <td className="py-3 pr-3 font-semibold">{symbol || "n/a"}</td>
                        <td className="py-3 pr-3">{formatPercent(normalizedWeights.get(symbol))}</td>
                        <td className="py-3 pr-3">{formatPercent(asset?.cumulativeReturn)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-accent">
              <Activity className="h-4 w-4" />
              {isKo ? "평가 공식" : "Useful evaluation formulas"}
            </div>
              <p className="safe-text mt-1 text-sm leading-6 text-muted">
              {isKo
                ? "이 공식은 순위와 대시보드 설명에 활용할 수 있는 리서치 도구입니다."
                : "These are research tools for ranking, triage, and explaining why a stock deserves deeper work."}
            </p>
          </div>
          <Link to="/$locale/sources" params={{ locale }} className="secondary-action py-2">
            {isKo ? "출처 보기" : "View sources"}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {formulaCards.map((card) => (
            <article key={card.title} className="panel p-5">
              <h3 className="font-semibold">{card.title}</h3>
              <p className="safe-text mt-2 rounded-md border border-line bg-panelAlt px-3 py-2 font-mono text-xs text-ink">
                {card.formula}
              </p>
              <p className="safe-text mt-3 text-sm leading-6 text-muted">{card.use}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value, tone = "normal" }: { label: string; value: string; tone?: "normal" | "risk" }) {
  return (
    <article className="panel min-w-0 p-5">
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className={`safe-text mt-2 text-2xl font-bold sm:text-3xl ${tone === "risk" ? "text-warning" : "text-ink"}`}>{value}</div>
    </article>
  );
}

function formatPercent(value: number | undefined) {
  if (value == null || !Number.isFinite(value)) return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

function formatRatio(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "n/a";
  return value.toFixed(2);
}

function defaultDateRange() {
  const end = new Date();
  const start = new Date(end);
  start.setMonth(start.getMonth() - 6);
  return {
    start: formatLocalDate(start),
    end: formatLocalDate(end)
  };
}

function formatLocalDate(date: Date) {
  const offsetMs = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
}
