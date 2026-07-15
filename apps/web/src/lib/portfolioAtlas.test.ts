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
  calculateAnnualizedVolatility,
  calculateBinaryKellyCriterion,
  calculateContinuousKellyFraction,
  calculateGainLossKellyCriterion,
  DEFAULT_ASSET_CLASS_CORRELATION_MATRIX,
  calculateLinkedTimeWeightedReturn,
  calculateMaxDrawdown,
  calculateMoneyWeightedReturn,
  calculateModifiedDietzReturn,
  calculateMonthlyGbmReturn,
  calculatePortfolioAssumptionMoments,
  calculateNetInvestedCapital,
  calculateRequiredMonthlyContribution,
  calculateSharpe,
  calculateReturnSeriesSharpe,
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
  instrumentFromSearchResult,
  isFeatureEnabled,
  resolveInstrumentSearchResult,
  runBacktest,
  runMonteCarlo,
  searchInstruments,
  validateHoldingsCsv
} from "./portfolioAtlas";
import type { Instrument, Portfolio } from "./portfolioAtlas";
import { normalizeWeights } from "./portfolio";

const testInstruments: Instrument[] = [
  testInstrument("AAPL", "Apple Inc.", 195, {
    aliases: ["Apple"],
    identifiers: [{ type: "ISIN", value: "US0378331005" }]
  }),
  testInstrument("MSFT", "Microsoft Corp.", 425),
  testInstrument("NVDA", "NVIDIA Corporation", 112),
  testInstrument("005930.KS", "Samsung Electronics", 75_300, {
    aliases: ["삼성전자"],
    identifiers: [
      { type: "ISIN", value: "KR7005930003" },
      { type: "LOCAL_CODE", value: "005930" }
    ],
    exchange: "KRX",
    country: "Korea",
    currency: "KRW",
    listings: [
      {
        listingId: "KRX:005930",
        symbol: "005930.KS",
        exchange: "KRX",
        country: "Korea",
        currency: "KRW",
        localCode: "005930",
        isPrimary: true,
        isActive: true
      }
    ],
    primaryListingId: "KRX:005930"
  }),
  testInstrument("VXUS", "International Equity ETF", 62, {
    instrumentType: "etf",
    fundFlag: true,
    expenseRatio: 0.0007,
    lookThroughHoldings: [
      { symbol: "TSM", weight: 0.031 },
      { symbol: "ASML", weight: 0.016 }
    ]
  })
];

function testInstrument(
  symbol: string,
  name: string,
  currentPrice: number,
  overrides: Partial<Instrument> = {}
): Instrument {
  const exchange = overrides.exchange ?? "NASDAQ";
  const country = overrides.country ?? "US";
  const currency = overrides.currency ?? "USD";
  return {
    instrumentId: symbol,
    symbol,
    exchange,
    name,
    instrumentType: "stock",
    isActive: true,
    assetClass: "Equity",
    subAssetClass: "Single Stocks",
    country,
    domicileCountry: country,
    currency,
    sector: "Information Technology",
    industry: "Information Technology",
    theme: [],
    expenseRatio: 0,
    dataQualityScore: 1,
    currentPrice,
    previousClose: currentPrice * 0.99,
    priceAsOf: "2026-05-29",
    priceQuality: "COMPLETE",
    priceCoverage: "available",
    calculationEligible: true,
    requiresUserPrice: false,
    sourceProviders: ["test_fixture"],
    sourceObservedAt: "2026-05-29T00:00:00Z",
    listings: [
      {
        listingId: `${exchange}:${symbol}`,
        symbol,
        exchange,
        country,
        currency,
        localCode: symbol,
        isPrimary: true,
        isActive: true
      }
    ],
    primaryListingId: `${exchange}:${symbol}`,
    ...overrides
  };
}

function testPortfolio(): Portfolio {
  const base = createDemoPortfolio();
  return {
    ...base,
    cashBalance: 6_500,
    targetAllocation: { Equity: 0.8, "Cash & Cash Equivalents": 0.2 },
    goal: {
      ...base.goal,
      targetAmount: 300_000,
      targetDate: "2036-12-31",
      monthlyContribution: 1_200,
      inflationAssumption: 0.025
    },
    holdings: [
      { holdingId: "h-aapl", portfolioId: base.portfolioId, accountId: "taxable", instrumentId: "AAPL", quantity: 200, currency: "USD", source: "manual" },
      { holdingId: "h-msft", portfolioId: base.portfolioId, accountId: "taxable", instrumentId: "MSFT", quantity: 100, currency: "USD", source: "manual" },
      { holdingId: "h-vxus", portfolioId: base.portfolioId, accountId: "taxable", instrumentId: "VXUS", quantity: 500, currency: "USD", source: "manual" }
    ],
    transactions: [
      { transactionId: "deposit", portfolioId: base.portfolioId, accountId: "taxable", instrumentId: "CASH", type: "DEPOSIT", date: "2024-01-01", quantity: 0, price: 0, fees: 0, amount: 100_000, currency: "USD" }
    ],
    taxLots: [
      { lotId: "aapl-lot", portfolioId: base.portfolioId, accountId: "taxable", instrumentId: "AAPL", purchaseDate: "2024-01-01", quantityOriginal: 200, quantityRemaining: 200, costBasisPerUnit: 150, fees: 0, currency: "USD", currentPrice: 195, source: "manual" }
    ]
  };
}

describe("portfolio atlas calculation engine", () => {
  it("ships without checked-in holdings or instrument observations", () => {
    const portfolio = createDemoPortfolio();

    expect(demoInstruments).toEqual([]);
    expect(portfolio.holdings).toEqual([]);
    expect(portfolio.transactions).toEqual([]);
    expect(portfolio.taxLots).toEqual([]);
    expect(portfolio.cashBalance).toBe(0);
    expect(portfolio.targetAllocation).toEqual({});
    expect(portfolio.goal.targetAmount).toBe(0);
    expect(portfolio.goal.monthlyContribution).toBe(0);
    expect(portfolio.isDemo).toBe(false);
  });

  it("calculates value, allocation, concentration, fees, and drift", () => {
    const portfolio = testPortfolio();
    const analysis = analyzePortfolio(portfolio, testInstruments, defaultAssumptions);

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
      calculateModifiedDietzReturn([
        { beginningValue: 100, endingValue: 120.5, externalCashFlow: 10, cashFlowTiming: "mid" }
      ])
    ).toBeCloseTo(0.1, 6);
    expect(calculateLinkedTimeWeightedReturn([0.1, -0.05, 0.02])).toBeCloseTo(1.1 * 0.95 * 1.02 - 1, 10);
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
    expect(calculateAnnualizedVolatility([0.01, 0.03, 0.05], 12, "population")).toBeCloseTo(Math.sqrt(0.0002666666666666667) * Math.sqrt(12), 10);
    expect(calculateAnnualizedVolatility([0.01, 0.03, 0.05], 12, "sample")).toBeCloseTo(0.02 * Math.sqrt(12), 10);
    expect(calculateVolatility(returns, 12)).toBeGreaterThan(0);
    expect(calculateMaxDrawdown([0.1, -0.2, 0.05])).toBeCloseTo(-0.2, 6);
    expect(calculateSharpe(0.08, 0.16, 0.04)).toBeCloseTo(0.25, 6);
    expect(calculateReturnSeriesSharpe([0.02, 0.01, -0.01, 0.03], 0, 12, "population")).toBeCloseTo((0.0125 * 12) / (Math.sqrt(0.00021875) * Math.sqrt(12)), 10);
    expect(calculateSortino(0.12, [0.02, -0.01, 0.03, -0.02], 0, 12)).toBeCloseTo(3.098, 3);
  });

  it("implements Kelly sizing formulas with explicit conventions", () => {
    const binary = calculateBinaryKellyCriterion({
      winProbability: 0.6,
      netOdds: 1,
      fractionalKelly: 0.5,
      maxRecommendedFraction: 0.25
    });
    expect(binary.fullKellyFraction).toBeCloseTo(0.2, 10);
    expect(binary.fractionalKellyFraction).toBeCloseTo(0.1, 10);
    expect(binary.cappedKellyFraction).toBeCloseTo(0.1, 10);
    expect(binary.convention).toBe("binary_net_odds");

    const gainLoss = calculateGainLossKellyCriterion({
      winProbability: 0.55,
      gainPerUnit: 0.12,
      lossPerUnit: 0.08,
      fractionalKelly: 0.25,
      maxRecommendedFraction: 0.5
    });
    expect(gainLoss.fullKellyFraction).toBeCloseTo(0.55 / 0.08 - 0.45 / 0.12, 10);
    expect(gainLoss.edge).toBeCloseTo(0.55 * 0.12 - 0.45 * 0.08, 10);

    const continuous = calculateContinuousKellyFraction({
      expectedAnnualReturn: 0.08,
      annualVolatility: 0.2,
      riskFreeRate: 0.03,
      fractionalKelly: 0.25,
      maxRecommendedFraction: 0.5
    });
    expect(continuous.fullKellyFraction).toBeCloseTo(1.25, 10);
    expect(continuous.fractionalKellyFraction).toBeCloseTo(0.3125, 10);
    expect(continuous.cappedKellyFraction).toBeCloseTo(0.3125, 10);
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
    const portfolio = testPortfolio();
    const analysis = analyzePortfolio(portfolio, testInstruments, defaultAssumptions);
    const backtest = runBacktest({ portfolio, instruments: testInstruments, assumptions: defaultAssumptions, years: 5 });
    const monteCarlo = runMonteCarlo({ portfolio, instruments: testInstruments, assumptions: defaultAssumptions, pathCount: 500, seed: 7 });
    const rebalance = generateContributionRebalancePlan(analysis, portfolio.targetAllocation, 1000, defaultAssumptions);
    const taxImpact = estimateTaxLotImpact(portfolio.taxLots, testInstruments, "AAPL", 5, "LOWEST_GAIN_FIRST");

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
    expect(calculateRequiredMonthlyContribution(12_682.5, 12, 0, 0.12682503013196977)).toBeCloseTo(1000, 2);
  });

  it("uses correlation-aware portfolio moments and testable GBM conversion", () => {
    const moments = calculatePortfolioAssumptionMoments(
      [
        { key: "Equity", label: "Equity", value: 60, weight: 0.6, topHoldings: [], quality: "COMPLETE" },
        { key: "Fixed Income", label: "Fixed Income", value: 40, weight: 0.4, topHoldings: [], quality: "COMPLETE" }
      ],
      {
        ...defaultAssumptions,
        expectedReturnByAssetClass: { ...defaultAssumptions.expectedReturnByAssetClass, Equity: 0.08, "Fixed Income": 0.04 },
        volatilityByAssetClass: { ...defaultAssumptions.volatilityByAssetClass, Equity: 0.2, "Fixed Income": 0.1 },
        correlationMatrix: { Equity: { "Fixed Income": 0.25 } }
      }
    );
    expect(moments.annualReturn).toBeCloseTo(0.064, 10);
    expect(moments.annualVariance).toBeCloseTo(0.6 ** 2 * 0.2 ** 2 + 0.4 ** 2 * 0.1 ** 2 + 2 * 0.6 * 0.4 * 0.2 * 0.1 * 0.25, 10);
    expect(defaultAssumptions.correlationMatrix).toBe(DEFAULT_ASSET_CLASS_CORRELATION_MATRIX);
    expect(calculatePortfolioAssumptionMoments(
      [
        { key: "Equity", label: "Equity", value: 60, weight: 0.6, topHoldings: [], quality: "COMPLETE" },
        { key: "Fixed Income", label: "Fixed Income", value: 40, weight: 0.4, topHoldings: [], quality: "COMPLETE" }
      ],
      {
        ...defaultAssumptions,
        volatilityByAssetClass: { ...defaultAssumptions.volatilityByAssetClass, Equity: 0.2, "Fixed Income": 0.1 },
        correlationMatrix: {}
      }
    ).annualVariance).toBeCloseTo(0.6 ** 2 * 0.2 ** 2 + 0.4 ** 2 * 0.1 ** 2 + 2 * 0.6 * 0.4 * 0.2 * 0.1 * 0.25, 10);

    expect(calculateMonthlyGbmReturn(0.12, 0.24, 0, 12)).toBeCloseTo(
      Math.exp(Math.log1p(0.12) / 12 - (0.24 / Math.sqrt(12)) ** 2 / 2) - 1,
      10
    );
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
    expect(searchInstruments("NVDA", testInstruments)[0]?.instrumentId).toBe("NVDA");
    expect(searchInstruments("US0378331005", testInstruments)[0]?.instrumentId).toBe("AAPL");
    expect(searchInstruments("KR7005930003", testInstruments)[0]?.instrumentId).toBe("005930.KS");
    expect(searchInstruments("005930", testInstruments)[0]?.listingId).toBe("KRX:005930");
    expect(searchInstruments("삼성전자", testInstruments)[0]?.instrumentId).toBe("005930.KS");
    expect(resolveInstrumentSearchResult("005930", testInstruments)?.listingId).toBe("KRX:005930");
  });

  it("materializes API-only search results as metadata-only instruments", () => {
    const result = {
      instrumentId: "ZZZAPI",
      listingId: "NASDAQ:ZZZAPI",
      displaySymbol: "ZZZAPI",
      name: "API Only Corp.",
      exchange: "NASDAQ",
      country: "US",
      currency: "USD",
      assetClass: "Equity",
      instrumentType: "stock" as const,
      sector: "Unclassified",
      isPrimaryListing: true,
      isAdvancedInstrument: false,
      isActive: true,
      isStale: false,
      qualityLevel: "PARTIAL" as const,
      qualityMessage: "Source-backed listing metadata; price requires separate market data.",
      metadataCoverage: "partial" as const,
      priceCoverage: "unavailable" as const,
      calculationEligible: false,
      requiresUserPrice: true,
      sourceProviders: ["nasdaq_trader", "sec_company_tickers"],
      sourceObservedAt: "2026-06-06T00:00:00Z",
      score: 1000,
      matchedOn: ["SYMBOL_EXACT"],
      tooltipKeys: ["ticker"]
    };

    const instrument = instrumentFromSearchResult(result);
    const portfolio = {
      ...createDemoPortfolio(),
      holdings: [
        {
          holdingId: "h-api",
          portfolioId: "demo-growth-income",
          accountId: "taxable",
          instrumentId: "ZZZAPI",
          listingId: "NASDAQ:ZZZAPI",
          quantity: 10,
          currency: "USD",
          source: "manual" as const
        }
      ],
      cashBalance: 0,
      transactions: [],
      taxLots: []
    };
    const analysisWithoutPrice = analyzePortfolio(portfolio, [instrument], defaultAssumptions);

    expect(instrument.priceQuality).toBe("UNAVAILABLE");
    expect(instrument.requiresUserPrice).toBe(true);
    expect(analysisWithoutPrice.portfolioValue).toBe(0);
    expect(analysisWithoutPrice.dataQualityIssues.some((issue) => issue.issueId === "metadata-only-holdings")).toBe(true);

    const analysisWithManualPrice = analyzePortfolio(
      {
        ...portfolio,
        holdings: [{ ...portfolio.holdings[0], manualPrice: 12 }]
      },
      [instrument],
      defaultAssumptions
    );

    expect(analysisWithManualPrice.portfolioValue).toBe(120);
    expect(analysisWithManualPrice.dataQualityIssues.some((issue) => issue.issueId === "metadata-only-holdings")).toBe(false);
    expect(analysisWithManualPrice.holdingCoverageRows[0]?.coverageStatus).toBe("manual");
  });

  it("materializes provider-priced search results as calculation-ready instruments", () => {
    const result = {
      instrumentId: "RKLB",
      listingId: "NASDAQ:RKLB",
      displaySymbol: "RKLB",
      name: "Rocket Lab USA, Inc.",
      exchange: "NASDAQ",
      country: "US",
      currency: "USD",
      assetClass: "Equity",
      instrumentType: "stock" as const,
      sector: "Space",
      isPrimaryListing: true,
      isAdvancedInstrument: false,
      isActive: true,
      isStale: false,
      qualityLevel: "PARTIAL" as const,
      qualityMessage: "Provider-backed symbol metadata with latest quote snapshot.",
      metadataCoverage: "partial" as const,
      priceCoverage: "available" as const,
      calculationEligible: true,
      requiresUserPrice: false,
      currentPrice: 25.5,
      previousClose: 25.1,
      priceAsOf: "2026-07-02T00:00:00Z",
      sourceProviders: ["fmp", "fmp_quote_short"],
      sourceObservedAt: "2026-07-02T00:00:00Z",
      score: 1000,
      matchedOn: ["SYMBOL_EXACT"],
      tooltipKeys: ["ticker"]
    };

    const instrument = instrumentFromSearchResult(result);
    const portfolio = {
      ...createDemoPortfolio(),
      holdings: [
        {
          holdingId: "h-rklb",
          portfolioId: "demo-growth-income",
          accountId: "taxable",
          instrumentId: "RKLB",
          listingId: "NASDAQ:RKLB",
          quantity: 4,
          currency: "USD",
          source: "manual" as const
        }
      ],
      cashBalance: 0,
      transactions: [],
      taxLots: []
    };
    const analysis = analyzePortfolio(portfolio, [instrument], defaultAssumptions);

    expect(instrument.currentPrice).toBe(25.5);
    expect(instrument.priceQuality).toBe("PARTIAL");
    expect(instrument.requiresUserPrice).toBe(false);
    expect(instrument.calculationEligible).toBe(true);
    expect(analysis.portfolioValue).toBe(102);
    expect(analysis.holdingCoverageRows[0]?.coverageStatus).not.toBe("manual");
  });

  it("keeps advanced and inactive instruments gated unless explicitly requested", () => {
    const advanced = {
      ...testInstruments[0],
      instrumentId: "AAPL.WS",
      symbol: "AAPL.WS",
      name: "Apple warrant",
      listings: [{ listingId: "NASDAQ:AAPL.WS", symbol: "AAPL.WS", exchange: "NASDAQ", country: "US", currency: "USD", localCode: "AAPL.WS", isPrimary: true }]
    };
    const inactive = {
      ...testInstruments[0],
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
    const portfolio = testPortfolio();
    const totalValue = analyzePortfolio(portfolio, testInstruments, defaultAssumptions).portfolioValue;
    expect(calculateGeographicExposure(portfolio.holdings, testInstruments, totalValue, portfolio.cashBalance)[0]?.weight).toBeGreaterThan(0);
    expect(calculateCurrencyExposure(portfolio.holdings, testInstruments, totalValue, portfolio.cashBalance)[0]?.key).toBe("USD");
    expect(calculateSectorExposure(portfolio.holdings, testInstruments, totalValue)[0]?.weight).toBeGreaterThan(0);

    const overlapHoldings = [
      ...portfolio.holdings,
      { holdingId: "h-vxus2", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "VXUS2", quantity: 10, currency: "USD", source: "sample" as const }
    ];
    const overlap = calculateFundOverlap(overlapHoldings, [
      ...testInstruments,
      {
        ...testInstruments.find((item) => item.symbol === "VXUS")!,
        instrumentId: "VXUS2",
        symbol: "VXUS2",
        lookThroughHoldings: [
          { symbol: "TSM", weight: 0.02 },
          { symbol: "ASML", weight: 0.01 }
        ]
      }
    ]);
    expect(overlap[0]?.overlapWeight).toBeCloseTo(0.03, 6);
    expect(calculateDataFreshnessScore(testInstruments, new Date("2026-05-30T00:00:00Z"), 3)).toBeGreaterThan(0);
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
