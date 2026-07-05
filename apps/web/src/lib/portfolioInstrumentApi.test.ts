import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createPortfolioInstrumentReviewRequest,
  enrichPortfolioInstrumentSelection,
  searchPortfolioInstruments
} from "./portfolioInstrumentApi";
import type { InstrumentSearchResult } from "./portfolioAtlas";

describe("portfolio instrument API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("searches the Phoenix instrument autocomplete endpoint", async () => {
    const result = searchResult({ instrumentId: "RKLB", listingId: "NASDAQ:RKLB", displaySymbol: "RKLB" });
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ results: [result], dataFreshness: { status: "ACTIVE" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      searchPortfolioInstruments({
        query: "RKLB",
        limit: 5,
        includeAdvanced: true,
        includeInactive: false,
        context: "BUILDER"
      })
    ).resolves.toMatchObject({ results: [{ listingId: "NASDAQ:RKLB" }] });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/search?q=RKLB&limit=5&include_advanced=true&include_inactive=false&context=BUILDER",
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ Accept: "application/json" }),
        method: "GET"
      })
    );
  });

  it("resolves and enriches selected search results through resolve and detail endpoints", async () => {
    const base = searchResult({ instrumentId: "005930.KS", listingId: "KRX:005930", displaySymbol: "005930" });
    const resolved = searchResult({
      instrumentId: "005930.KS",
      listingId: "KRX:005930",
      displaySymbol: "005930",
      currency: "KRW"
    });
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/instruments/resolve") {
        return jsonResponse({ status: "MATCHED", confidence: "HIGH", matches: [resolved] });
      }
      if (url === "/api/instruments/005930.KS?listing_id=KRX%3A005930") {
        return jsonResponse({
          instrumentId: "005930.KS",
          symbol: "005930",
          name: "Samsung Electronics",
          assetClass: "Equity",
          instrumentType: "stock",
          country: "Korea",
          currency: "KRW",
          sector: "Technology",
          isActive: true,
          dataQualityLevel: "COMPLETE",
          dataQualityMessage: "Resolved by Phoenix index.",
          listings: [
            {
              listingId: "KRX:005930",
              displaySymbol: "005930",
              exchangeCode: "KRX",
              country: "Korea",
              tradingCurrency: "KRW",
              isPrimaryListing: true,
              isActive: true
            }
          ]
        });
      }
      return new Response("missing", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(enrichPortfolioInstrumentSelection(base, "HOLDING_ENTRY")).resolves.toMatchObject({
      name: "Samsung Electronics",
      exchange: "KRX",
      currency: "KRW",
      sourceProviders: expect.arrayContaining(["phoenix_instruments_api"])
    });
  });

  it("rejects failed enrichment so callers can keep local fallback behavior", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));

    await expect(
      enrichPortfolioInstrumentSelection(searchResult({ instrumentId: "AAPL", listingId: "NASDAQ:AAPL" }), "HOLDING_ENTRY")
    ).rejects.toThrow("Instrument API failed: 503");
  });

  it("creates review requests with backend context fields", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: "review-1", status: "queued" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createPortfolioInstrumentReviewRequest({ query: "QBTS", contextScreen: "BUILDER" })
    ).resolves.toEqual({ id: "review-1", status: "queued" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/instruments/review-requests",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ query: "QBTS", context_screen: "BUILDER", optional_notes: undefined })
      })
    );
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

function searchResult(overrides: Partial<InstrumentSearchResult>): InstrumentSearchResult {
  return {
    instrumentId: "AAPL",
    listingId: "NASDAQ:AAPL",
    displaySymbol: "AAPL",
    name: "Apple",
    exchange: "NASDAQ",
    country: "US",
    currency: "USD",
    assetClass: "Equity",
    instrumentType: "stock",
    sector: "Technology",
    isPrimaryListing: true,
    isAdvancedInstrument: false,
    isActive: true,
    isStale: false,
    qualityLevel: "COMPLETE",
    qualityMessage: "Complete record.",
    metadataCoverage: "full",
    priceCoverage: "available",
    calculationEligible: true,
    requiresUserPrice: false,
    sourceProviders: ["local_catalog"],
    score: 100,
    matchedOn: ["SYMBOL_EXACT"],
    tooltipKeys: [],
    ...overrides
  };
}
