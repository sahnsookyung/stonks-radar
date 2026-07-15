import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanCurrency,
  cleanManualText,
  clearSourceLinkedRecords,
  loadPortfolioWorkspace,
  loadServerPortfolioWorkspace,
  savePortfolioWorkspace,
  saveServerPortfolioWorkspace,
  validateManualDraft,
  workspaceStorageKey
} from "./portfolioWorkspace";
import { createDemoPortfolio, defaultAssumptions } from "./portfolioAtlas";

describe("portfolio workspace helpers", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis.window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => store.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => store.set(key, value)),
        clear: vi.fn(() => store.clear())
      }
    });
    sessionStorage.clear();
  });

  afterEach(() => {
    globalThis.window.localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("round-trips local workspace state through local storage", () => {
    const portfolio = createDemoPortfolio();
    savePortfolioWorkspace(portfolio.portfolioId, {
      portfolio,
      manualInstruments: [],
      reviewRequests: [],
      assumptions: defaultAssumptions
    });

    expect(globalThis.window.localStorage.getItem(workspaceStorageKey(portfolio.portfolioId))).toContain(
      portfolio.portfolioId
    );
    expect(loadPortfolioWorkspace(portfolio.portfolioId)).toMatchObject({
      version: 1,
      portfolio: { portfolioId: portfolio.portfolioId },
      assumptions: { name: defaultAssumptions.name }
    });
  });

  it("persists valid user portfolio ids locally", () => {
    const portfolio = createDemoPortfolio();
    savePortfolioWorkspace("private-plan", {
      portfolio: { ...portfolio, portfolioId: "private-plan" },
      manualInstruments: [],
      reviewRequests: [],
      assumptions: defaultAssumptions
    });

    expect(loadPortfolioWorkspace("private-plan")).toMatchObject({
      portfolio: { portfolioId: "private-plan" }
    });
  });

  it("removes only unmistakable legacy sample records from stored workspaces", () => {
    const portfolio = createDemoPortfolio();
    globalThis.window.localStorage.setItem(
      workspaceStorageKey(portfolio.portfolioId),
      JSON.stringify({
        version: 1,
        portfolio: {
          ...portfolio,
          cashBalance: 6_500,
          holdings: [
            { holdingId: "h-aapl", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "AAPL", quantity: 44, currency: "USD", source: "sample" },
            { holdingId: "manual", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "USER", quantity: 1, currency: "USD", source: "manual" }
          ],
          transactions: [
            { transactionId: "t-aapl-1", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "AAPL", type: "BUY", date: "2024-01-01", quantity: 44, price: 155, fees: 0, amount: -6_820, currency: "USD" }
          ],
          taxLots: [
            { lotId: "lot-aapl-1", portfolioId: portfolio.portfolioId, accountId: "taxable", instrumentId: "AAPL", purchaseDate: "2024-01-01", quantityOriginal: 44, quantityRemaining: 44, costBasisPerUnit: 155, fees: 0, currency: "USD", currentPrice: 195, source: "sample" }
          ]
        },
        manualInstruments: [],
        reviewRequests: [],
        assumptions: defaultAssumptions
      })
    );

    expect(loadPortfolioWorkspace(portfolio.portfolioId)?.portfolio).toMatchObject({
      cashBalance: 0,
      holdings: [{ holdingId: "manual" }],
      transactions: [],
      taxLots: []
    });
  });

  it("loads an authenticated server workspace response", async () => {
    const portfolio = createDemoPortfolio();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            portfolio_id: portfolio.portfolioId,
            workspace: {
              version: 1,
              portfolio,
              manualInstruments: [],
              reviewRequests: [],
              assumptions: defaultAssumptions
            }
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      )
    );

    await expect(loadServerPortfolioWorkspace(portfolio.portfolioId)).resolves.toMatchObject({
      portfolio: { portfolioId: portfolio.portfolioId },
      assumptions: { name: defaultAssumptions.name }
    });
    expect(fetch).toHaveBeenCalledWith(
      `/api/portfolio-workspaces/${portfolio.portfolioId}`,
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("saves a server workspace only when a csrf token is available", async () => {
    const portfolio = createDemoPortfolio();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      saveServerPortfolioWorkspace(portfolio.portfolioId, {
        portfolio,
        manualInstruments: [],
        reviewRequests: [],
        assumptions: defaultAssumptions
      })
    ).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();

    sessionStorage.setItem("frw_csrf", "csrf-token");
    await expect(
      saveServerPortfolioWorkspace(portfolio.portfolioId, {
        portfolio,
        manualInstruments: [],
        reviewRequests: [],
        assumptions: defaultAssumptions
      })
    ).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/portfolio-workspaces/${portfolio.portfolioId}`,
      expect.objectContaining({
        method: "PUT",
        headers: expect.objectContaining({ "x-csrf-token": "csrf-token" })
      })
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      workspace: { version: 1, portfolio: { portfolioId: portfolio.portfolioId } }
    });
  });

  it("cleans source-linked records before manual portfolio edits", () => {
    const portfolio = createDemoPortfolio();
    const cleared = clearSourceLinkedRecords(portfolio);

    expect(cleared.transactions).toEqual([]);
    expect(cleared.taxLots).toEqual([]);
    expect(cleared.holdings).toEqual(portfolio.holdings);
  });

  it("validates manual holdings without requiring a price and value together", () => {
    expect(cleanManualText("  Test\u0000   Holding  ")).toBe("Test Holding");
    expect(cleanCurrency(" krw ")).toBe("KRW");
    expect(cleanCurrency("12")).toBe("USD");

    expect(
      validateManualDraft({
        symbolOrCode: "005930",
        name: "Samsung Electronics",
        currency: "KRW",
        assetClass: "Equity",
        quantityText: "2",
        priceText: "70000",
        marketValueText: ""
      })
    ).toEqual([]);

    expect(
      validateManualDraft({
        symbolOrCode: "",
        name: "",
        currency: "12",
        assetClass: "",
        quantityText: "0",
        priceText: "",
        marketValueText: ""
      }).join(" ")
    ).toContain("Symbol or local code is required.");
  });
});
