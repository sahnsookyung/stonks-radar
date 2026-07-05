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

  it("round-trips demo workspace state through local storage", () => {
    const portfolio = createDemoPortfolio();
    savePortfolioWorkspace("demo-growth-income", {
      portfolio,
      manualInstruments: [],
      reviewRequests: [],
      assumptions: defaultAssumptions
    });

    expect(globalThis.window.localStorage.getItem(workspaceStorageKey("demo-growth-income"))).toContain(
      "demo-growth-income"
    );
    expect(loadPortfolioWorkspace("demo-growth-income")).toMatchObject({
      version: 1,
      portfolio: { portfolioId: "demo-growth-income" },
      assumptions: { name: defaultAssumptions.name }
    });
  });

  it("does not persist arbitrary portfolio ids in local demo mode", () => {
    const portfolio = createDemoPortfolio();
    savePortfolioWorkspace("private-plan", {
      portfolio: { ...portfolio, portfolioId: "private-plan" },
      manualInstruments: [],
      reviewRequests: [],
      assumptions: defaultAssumptions
    });

    expect(loadPortfolioWorkspace("private-plan")).toBeNull();
  });

  it("loads an authenticated server workspace response", async () => {
    const portfolio = createDemoPortfolio();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            portfolio_id: "demo-growth-income",
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

    await expect(loadServerPortfolioWorkspace("demo-growth-income")).resolves.toMatchObject({
      portfolio: { portfolioId: "demo-growth-income" },
      assumptions: { name: defaultAssumptions.name }
    });
    expect(fetch).toHaveBeenCalledWith(
      "/api/portfolio-workspaces/demo-growth-income",
      expect.objectContaining({ credentials: "include" })
    );
  });

  it("saves a server workspace only when a csrf token is available", async () => {
    const portfolio = createDemoPortfolio();
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      saveServerPortfolioWorkspace("demo-growth-income", {
        portfolio,
        manualInstruments: [],
        reviewRequests: [],
        assumptions: defaultAssumptions
      })
    ).resolves.toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();

    sessionStorage.setItem("frw_csrf", "csrf-token");
    await expect(
      saveServerPortfolioWorkspace("demo-growth-income", {
        portfolio,
        manualInstruments: [],
        reviewRequests: [],
        assumptions: defaultAssumptions
      })
    ).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/portfolio-workspaces/demo-growth-income",
      expect.objectContaining({
        method: "PUT",
        headers: expect.objectContaining({ "x-csrf-token": "csrf-token" })
      })
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      workspace: { version: 1, portfolio: { portfolioId: "demo-growth-income" } }
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
