import { describe, expect, it } from "vitest";
import { computePortfolioStats } from "./portfolio";

describe("portfolio analytics", () => {
  it("computes Sharpe, Sortino, and drawdown from aligned daily closes", () => {
    const portfolioReturns = [
      0.6 * (102 / 100 - 1) + 0.4 * (49 / 50 - 1),
      0.6 * (101 / 102 - 1) + 0.4 * (47 / 49 - 1),
      0.6 * (104 / 101 - 1) + 0.4 * (51 / 47 - 1)
    ];
    const averageDailyReturn = mean(portfolioReturns);
    const dailyRiskFreeRate = Math.pow(1 + 0.04, 1 / 252) - 1;
    const dailyDownsideTarget = Math.pow(1 + 0.1, 1 / 252) - 1;
    const annualizedVolatility = standardDeviation(portfolioReturns) * Math.sqrt(252);
    const downsideDeviation =
      Math.sqrt(mean(portfolioReturns.map((value) => Math.min(0, value - dailyDownsideTarget) ** 2))) *
      Math.sqrt(252);
    const cumulativeReturn = portfolioReturns.reduce((compound, value) => compound * (1 + value), 1) - 1;

    const stats = computePortfolioStats(
      [
        {
          symbol: "AAA",
          points: [
            { date: "2026-01-01", close: 100 },
            { date: "2026-01-02", close: 102 },
            { date: "2026-01-03", close: 101 },
            { date: "2026-01-04", close: 104 }
          ]
        },
        {
          symbol: "BBB",
          points: [
            { date: "2026-01-01", close: 50 },
            { date: "2026-01-02", close: 49 },
            { date: "2026-01-03", close: 47 },
            { date: "2026-01-04", close: 51 }
          ]
        }
      ],
      [
        { symbol: "AAA", weight: 60 },
        { symbol: "BBB", weight: 40 }
      ],
      0.04,
      0.1
    );

    expect(stats).not.toBeNull();
    expect(stats?.observationCount).toBe(3);
    expect(stats?.annualizedReturn).toBeCloseTo(Math.pow(1 + cumulativeReturn, 252 / 3) - 1, 10);
    expect(stats?.annualizedVolatility).toBeCloseTo(annualizedVolatility, 10);
    expect(stats?.sharpeRatio).toBeCloseTo(
      ((averageDailyReturn - dailyRiskFreeRate) * 252) / annualizedVolatility,
      10
    );
    expect(stats?.sortinoRatio).toBeCloseTo(
      ((averageDailyReturn - dailyDownsideTarget) * 252) / downsideDeviation,
      10
    );
    expect(stats?.maxDrawdown).toBeCloseTo(portfolioReturns[1], 10);
  });
});

function mean(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function standardDeviation(values: number[]) {
  const average = mean(values);
  return Math.sqrt(mean(values.map((value) => (value - average) ** 2)));
}
