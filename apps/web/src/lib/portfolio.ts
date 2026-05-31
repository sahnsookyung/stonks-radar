export interface PricePoint {
  date: string;
  close: number;
}

export interface PriceSeries {
  symbol: string;
  points: PricePoint[];
}

export interface HoldingWeight {
  symbol: string;
  weight: number;
}

export interface PortfolioStats {
  observationCount: number;
  startDate: string;
  endDate: string;
  annualizedReturn: number;
  annualizedVolatility: number;
  sharpeRatio: number | null;
  sortinoRatio: number | null;
  maxDrawdown: number;
  cumulativeReturn: number;
  assetReturns: { symbol: string; cumulativeReturn: number }[];
}

const TRADING_DAYS_PER_YEAR = 252;

export function computePortfolioStats(
  series: PriceSeries[],
  holdings: HoldingWeight[],
  annualRiskFreeRate: number,
  annualDownsideTarget: number
): PortfolioStats | null {
  const weights = normalizeWeights(holdings);
  const returnMaps = series.map((item) => ({
    symbol: item.symbol,
    returns: returnsByDate(item.points)
  }));
  const commonDates = intersectSorted(returnMaps.map((item) => Object.keys(item.returns)));
  if (commonDates.length < 2) return null;

  const portfolioReturns = commonDates.map((day) =>
    returnMaps.reduce((sum, item) => {
      const weight = weights.get(item.symbol) ?? 0;
      return sum + weight * item.returns[day];
    }, 0)
  );

  const averageDailyReturn = mean(portfolioReturns);
  const dailyRiskFreeRate = Math.pow(1 + annualRiskFreeRate, 1 / TRADING_DAYS_PER_YEAR) - 1;
  const dailyDownsideTarget = Math.pow(1 + annualDownsideTarget, 1 / TRADING_DAYS_PER_YEAR) - 1;
  const totalReturn = cumulativeReturn(portfolioReturns);
  const annualizedReturn =
    totalReturn <= -1 ? -1 : Math.pow(1 + totalReturn, TRADING_DAYS_PER_YEAR / portfolioReturns.length) - 1;
  const annualizedVolatility = standardDeviation(portfolioReturns) * Math.sqrt(TRADING_DAYS_PER_YEAR);
  const downsideDeviation = Math.sqrt(
    mean(portfolioReturns.map((value) => Math.min(0, value - dailyDownsideTarget) ** 2))
  ) * Math.sqrt(TRADING_DAYS_PER_YEAR);
  const annualizedExcessReturn = (averageDailyReturn - dailyRiskFreeRate) * TRADING_DAYS_PER_YEAR;
  const annualizedTargetExcessReturn = (averageDailyReturn - dailyDownsideTarget) * TRADING_DAYS_PER_YEAR;

  return {
    observationCount: portfolioReturns.length,
    startDate: commonDates[0],
    endDate: commonDates[commonDates.length - 1],
    annualizedReturn,
    annualizedVolatility,
    sharpeRatio:
      annualizedVolatility > 0 ? annualizedExcessReturn / annualizedVolatility : null,
    sortinoRatio:
      downsideDeviation > 0 ? annualizedTargetExcessReturn / downsideDeviation : null,
    maxDrawdown: maxDrawdown(portfolioReturns),
    cumulativeReturn: totalReturn,
    assetReturns: returnMaps.map((item) => ({
      symbol: item.symbol,
      cumulativeReturn: cumulativeReturn(commonDates.map((day) => item.returns[day]))
    }))
  };
}

export function normalizeWeights(holdings: HoldingWeight[]): Map<string, number> {
  const cleaned = holdings
    .map((item) => ({ symbol: item.symbol.trim().toUpperCase(), weight: Number(item.weight) }))
    .filter((item) => item.symbol && Number.isFinite(item.weight) && item.weight > 0);
  const total = cleaned.reduce((sum, item) => sum + item.weight, 0);
  const aggregated = new Map<string, number>();
  for (const item of cleaned) {
    aggregated.set(item.symbol, (aggregated.get(item.symbol) ?? 0) + item.weight);
  }
  return new Map([...aggregated.entries()].map(([symbol, weight]) => [symbol, total > 0 ? weight / total : 0]));
}

export function returnsByDate(points: PricePoint[]): Record<string, number> {
  const sorted = [...points]
    .filter((point) => Number.isFinite(point.close) && point.close > 0)
    .sort((left, right) => left.date.localeCompare(right.date));
  const returns: Record<string, number> = {};
  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1];
    const current = sorted[index];
    returns[current.date] = current.close / previous.close - 1;
  }
  return returns;
}

function intersectSorted(groups: string[][]): string[] {
  if (groups.length === 0) return [];
  const [first, ...rest] = groups.map((group) => new Set(group));
  return [...first].filter((date) => rest.every((group) => group.has(date))).sort();
}

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const average = mean(values);
  const variance = mean(values.map((value) => (value - average) ** 2));
  return Math.sqrt(variance);
}

function cumulativeReturn(returns: number[]) {
  return returns.reduce((compound, value) => compound * (1 + value), 1) - 1;
}

function maxDrawdown(returns: number[]) {
  let equity = 1;
  let peak = 1;
  let worst = 0;
  for (const value of returns) {
    equity *= 1 + value;
    peak = Math.max(peak, equity);
    worst = Math.min(worst, equity / peak - 1);
  }
  return worst;
}
