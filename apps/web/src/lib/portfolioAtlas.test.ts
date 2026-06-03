import { describe, expect, it } from "vitest";
import {
  analyzePortfolio,
  calculateAllocationDrift,
  calculateCAGR,
  calculateCurrencyExposure,
  calculateDataFreshnessScore,
  calculateFundOverlap,
  calculateGeographicExposure,
  calculateHHI,
  calculateMaxDrawdown,
  calculateMoneyWeightedReturn,
  calculateNetInvestedCapital,
  calculateRequiredMonthlyContribution,
  calculateSharpe,
  calculateSectorExposure,
  calculateSortino,
  calculateTotalGainLoss,
  calculateTimeWeightedReturn,
  calculateVolatility,
  createDemoPortfolio,
  defaultAssumptions,
  demoInstruments,
  estimateTaxLotImpact,
  generateContributionRebalancePlan,
  isFeatureEnabled,
  resolveInstrumentSearchResult,
  runBacktest,
  runMonteCarlo,
  searchInstruments,
  validateHoldingsCsv
} from "./portfolioAtlas";
import { normalizeWeights } from "./portfolio";

describe("portfolio atlas calculation engine", () => {
  it("calculates value, allocation, concentration, fees, and drift", () => {
    const portfolio = createDemoPortfolio();
    const analysis = analyzePortfolio(portfolio, demoInstruments, defaultAssumptions);

    expect(analysis.portfolioValue).toBeGreaterThan(100_000);
    expect(analysis.netInvestedCapital).toBeGreaterThan(0);
    expect(analysis.assetAllocation.reduce((sum, row) => sum + row.weight, 0)).toBeCloseTo(1, 4);
    expect(calculateHHI([0.5, 0.3, 0.2])).toBeCloseTo(0.38, 6);
    expect(analysis.weightedExpenseRatio).toBeGreaterThanOrEqual(0);
    expect(analysis.estimatedAnnualFees).toBeGreaterThan(0);
    expect(analysis.allocationDrift).toBeGreaterThanOrEqual(0);
    expect(analysis.dataFreshnessScore).toBeGreaterThanOrEqual(0);
    expect(analysis.dataFreshnessScore).toBeLessThanOrEqual(1);
    expect(analysis.coverageSummary.coveredWeight + analysis.coverageSummary.staleWeight + analysis.coverageSummary.proxyWeight + analysis.coverageSummary.missingWeight).toBeGreaterThan(0.9);
    expect(analysis.calculationProvenance.cachePolicy).toContain("daily bars");
    expect(analysis.returnBasis).toBe("daily-close-total-return-proxy");
  });

  it("implements core return and risk formulas", () => {
    expect(calculateCAGR(100, 121, 2)).toBeCloseTo(0.1, 6);
    expect(
      calculateTimeWeightedReturn([
        { beginningValue: 100, endingValue: 110, externalCashFlow: 0 },
        { beginningValue: 110, endingValue: 130, externalCashFlow: 10 }
      ])
    ).toBeCloseTo(0.2, 6);
    expect(
      calculateTimeWeightedReturn([
        { beginningValue: 100, endingValue: 121, externalCashFlow: 10, cashFlowTiming: "beginning" }
      ])
    ).toBeCloseTo(0.1, 6);
    expect(
      calculateTimeWeightedReturn([
        { beginningValue: 100, endingValue: 120.5, externalCashFlow: 10, cashFlowTiming: "mid" }
      ])
    ).toBeCloseTo(0.1, 6);

    const xirr = calculateMoneyWeightedReturn([
      { date: "2024-01-01", amount: -1000 },
      { date: "2025-01-01", amount: 1100 }
    ]);
    expect(xirr).not.toBeNull();
    expect(xirr ?? 0).toBeCloseTo(0.1, 2);

    const returns = [0.01, -0.02, 0.03, -0.01, 0.02];
    expect(calculateVolatility(returns, 12)).toBeGreaterThan(0);
    expect(calculateMaxDrawdown([0.1, -0.2, 0.05])).toBeCloseTo(-0.2, 6);
    expect(calculateSharpe(0.08, 0.16, 0.04)).toBeCloseTo(0.25, 6);
    expect(calculateSortino(0.12, [0.02, -0.01, 0.03, -0.02], 0, 12)).toBeCloseTo(3.098, 3);
  });

  it("keeps cash-flow math from double-counting portfolio buys", () => {
    expect(
      calculateNetInvestedCapital([
        { transactionId: "d1", portfolioId: "p", accountId: "a", instrumentId: "CASH", type: "DEPOSIT", date: "2024-01-01", quantity: 0, price: 0, fees: 0, amount: 10_000, currency: "USD" },
        { transactionId: "b1", portfolioId: "p", accountId: "a", instrumentId: "AAPL", type: "BUY", date: "2024-01-02", quantity: 10, price: 100, fees: 5, amount: -1_005, currency: "USD" }
      ])
    ).toBe(10_000);
    expect(
      calculateNetInvestedCapital([
        { transactionId: "b1", portfolioId: "p", accountId: "a", instrumentId: "AAPL", type: "BUY", date: "2024-01-02", quantity: 10, price: 100, fees: 5, amount: -1_000, currency: "USD" },
        { transactionId: "s1", portfolioId: "p", accountId: "a", instrumentId: "AAPL", type: "SELL", date: "2024-02-02", quantity: 2, price: 120, fees: 0, amount: 240, currency: "USD" }
      ])
    ).toBe(760);
    expect(calculateTotalGainLoss(12_500, 10_000)).toEqual({ gainLoss: 2_500, gainLossPercent: 0.25 });
  });

  it("runs backtest, monte carlo, rebalance, and tax-lot estimates deterministically", () => {
    const portfolio = createDemoPortfolio();
    const analysis = analyzePortfolio(portfolio, demoInstruments, defaultAssumptions);
    const backtest = runBacktest({ portfolio, instruments: demoInstruments, assumptions: defaultAssumptions, years: 5 });
    const monteCarlo = runMonteCarlo({ portfolio, instruments: demoInstruments, assumptions: defaultAssumptions, pathCount: 500, seed: 7 });
    const rebalance = generateContributionRebalancePlan(analysis, portfolio.targetAllocation, 1000, defaultAssumptions);
    const taxImpact = estimateTaxLotImpact(portfolio.taxLots, demoInstruments, "AAPL", 5, "LOWEST_GAIN_FIRST");

    expect(backtest.equityCurve).toHaveLength(60);
    expect(backtest.endingValue).toBeGreaterThan(0);
    expect(monteCarlo.pathCount).toBe(500);
    expect(monteCarlo.p5Outcome).toBeGreaterThanOrEqual(0);
    expect(monteCarlo.p90Outcome).toBeGreaterThan(monteCarlo.p10Outcome);
    expect(rebalance.cashContributionPlan.length).toBeGreaterThan(0);
    expect(Object.values(rebalance.postRebalanceWeights).reduce((sum, value) => sum + value, 0)).toBeCloseTo(1, 6);
    expect(rebalance.postRebalanceWeights).not.toEqual(portfolio.targetAllocation);
    expect(taxImpact.sellQuantity).toBe(5);
    expect(taxImpact.lotsUsed.length).toBeGreaterThan(0);
    expect(calculateRequiredMonthlyContribution(1200, 12, 0, 0)).toBe(100);
  });

  it("validates CSV import and blocks malformed or unsafe rows", () => {
    const ok = validateHoldingsCsv("symbol,quantity,price\nAAPL,2,100\nMSFT,3,200");
    expect(ok.errors).toEqual([]);
    expect(ok.holdings).toHaveLength(2);

    const rejected = validateHoldingsCsv("symbol,quantity,price\n=CMD(),2,100");
    expect(rejected.errors.join(" ")).toContain("formula");
    expect(rejected.holdings).toEqual([]);

    const duplicate = validateHoldingsCsv("symbol,quantity,price\nAAPL,2,100\nAAPL,2,100");
    expect(duplicate.errors.join(" ")).toContain("duplicates");

    const unknown = validateHoldingsCsv("symbol,quantity,price\nNOPE,2,100", {
      knownSymbols: ["AAPL"],
      rejectUnknownSymbols: true
    });
    expect(unknown.errors.join(" ")).toContain("unknown symbol NOPE");

    const badDate = validateHoldingsCsv("symbol,quantity,price,date\nAAPL,2,100,not-a-date");
    expect(badDate.errors.join(" ")).toContain("invalid date");

    const tooManyRows = validateHoldingsCsv(`symbol,quantity,price\n${Array.from({ length: 4 }, (_, index) => `AAPL,${index + 1},100`).join("\n")}`, {
      maxRows: 3
    });
    expect(tooManyRows.errors.join(" ")).toContain("too many holding rows");
  });

  it("searches instruments by ticker, ISIN, local code, aliases, and listing metadata", () => {
    expect(searchInstruments("NVDA", demoInstruments)[0]?.instrumentId).toBe("NVDA");
    expect(searchInstruments("US0378331005", demoInstruments)[0]?.instrumentId).toBe("AAPL");
    expect(searchInstruments("KR7005930003", demoInstruments)[0]?.instrumentId).toBe("005930.KS");
    expect(searchInstruments("005930", demoInstruments)[0]?.listingId).toBe("KRX:005930");
    expect(searchInstruments("삼성전자", demoInstruments)[0]?.instrumentId).toBe("005930.KS");
    expect(resolveInstrumentSearchResult("005930", demoInstruments)?.listingId).toBe("KRX:005930");
  });

  it("keeps advanced and inactive instruments gated unless explicitly requested", () => {
    const advanced = {
      ...demoInstruments[0],
      instrumentId: "AAPL.WS",
      symbol: "AAPL.WS",
      name: "Apple warrant",
      listings: [{ listingId: "NASDAQ:AAPL.WS", symbol: "AAPL.WS", exchange: "NASDAQ", country: "US", currency: "USD", localCode: "AAPL.WS", isPrimary: true }]
    };
    const inactive = {
      ...demoInstruments[0],
      instrumentId: "OLD",
      symbol: "OLD",
      name: "Old Co",
      isActive: false,
      listings: [{ listingId: "NYSE:OLD", symbol: "OLD", exchange: "NYSE", country: "US", currency: "USD", localCode: "OLD", isPrimary: true, isActive: false }]
    };

    expect(searchInstruments("Apple", [advanced])).toEqual([]);
    expect(searchInstruments("Apple", [advanced], { includeAdvanced: true })[0]?.instrumentId).toBe("AAPL.WS");
    expect(searchInstruments("OLD", [inactive])).toEqual([]);
    expect(searchInstruments("OLD", [inactive], { includeInactive: true })[0]?.isActive).toBe(false);
  });

  it("calculates exposure wrappers, fund overlap, and data freshness", () => {
    const portfolio = createDemoPortfolio();
    const totalValue = analyzePortfolio(portfolio, demoInstruments, defaultAssumptions).portfolioValue;
    expect(calculateGeographicExposure(portfolio.holdings, demoInstruments, totalValue, portfolio.cashBalance)[0]?.weight).toBeGreaterThan(0);
    expect(calculateCurrencyExposure(portfolio.holdings, demoInstruments, totalValue, portfolio.cashBalance)[0]?.key).toBe("USD");
    expect(calculateSectorExposure(portfolio.holdings, demoInstruments, totalValue)[0]?.weight).toBeGreaterThan(0);

    const overlapHoldings = [
      ...portfolio.holdings,
      { holdingId: "h-vxus2", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "VXUS2", quantity: 10, currency: "USD", source: "sample" as const }
    ];
    const overlap = calculateFundOverlap(overlapHoldings, [
      ...demoInstruments,
      {
        ...demoInstruments.find((item) => item.symbol === "VXUS")!,
        instrumentId: "VXUS2",
        symbol: "VXUS2",
        lookThroughHoldings: [
          { symbol: "TSM", weight: 0.02 },
          { symbol: "ASML", weight: 0.01 }
        ]
      }
    ]);
    expect(overlap[0]?.overlapWeight).toBeCloseTo(0.03, 6);
    expect(calculateDataFreshnessScore(demoInstruments, new Date("2026-05-30T00:00:00Z"), 3)).toBeGreaterThan(0);
  });

  it("supports feature gate resolution and duplicate weight aggregation", () => {
    expect(
      isFeatureEnabled(
        [
          {
            key: "FEATURE_TEST",
            displayName: "Test",
            description: "Test",
            enabledGlobally: false,
            enabledForFreeUsers: false,
            enabledForPaidUsers: false,
            enabledForAdmins: true,
            rolloutPercentage: 0,
            hardDisabled: false
          }
        ],
        "FEATURE_TEST",
        { role: "ADMIN" }
      )
    ).toBe(true);

    const weights = normalizeWeights([
      { symbol: "AAPL", weight: 10 },
      { symbol: "AAPL", weight: 20 },
      { symbol: "MSFT", weight: 30 }
    ]);
    expect(weights.get("AAPL")).toBeCloseTo(0.5, 6);
    expect(weights.get("MSFT")).toBeCloseTo(0.5, 6);
  });

  it("calculates allocation drift as half the absolute difference", () => {
    const rows = calculateAllocationDrift(
      [
        { key: "Equity", label: "Equity", value: 60, weight: 0.6, topHoldings: [], quality: "COMPLETE" },
        { key: "Fixed Income", label: "Fixed Income", value: 40, weight: 0.4, topHoldings: [], quality: "COMPLETE" }
      ],
      { Equity: 0.5, "Fixed Income": 0.5 },
      100
    );
    expect(rows.reduce((sum, row) => sum + Math.abs(row.drift), 0) / 2).toBeCloseTo(0.1, 6);
  });
});
