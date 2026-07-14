import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createPortfolioInstrumentReviewRequest,
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
