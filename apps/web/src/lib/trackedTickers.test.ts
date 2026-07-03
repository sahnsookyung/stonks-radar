import { describe, expect, it } from "vitest";
import {
  entityDisplayName,
  getTrackedTicker,
  relatedTrackedEntities,
  resolveTrackedEntity,
  routeKeyForSymbol,
  searchTrackedTickers,
  tickerMatchesFilterValue,
  trackedTickerFilterOptions,
  trackedTickers
} from "./trackedTickers";

describe("tracked entity registry helpers", () => {
  it("resolves dotted ticker route aliases", () => {
    expect(routeKeyForSymbol("005930.KS")).toBe("005930_KS");
    expect(getTrackedTicker("005930.KS")?.routeKey).toBe("005930_KS");
    expect(getTrackedTicker("005930_KS")?.symbol).toBe("005930.KS");
  });

  it("keeps related entities distinct from the current entity", () => {
    const qbts = resolveTrackedEntity("QBTS");
    expect(qbts).toBeDefined();
    const related = relatedTrackedEntities(qbts!, 12);

    expect(related.map((entity) => entity.entityId)).not.toContain(qbts!.entityId);
    expect(new Set(related.map((entity) => entity.entityId)).size).toBe(related.length);
    expect(related.some((entity) => entity.routeKind === "reference_entity")).toBe(true);
  });

  it("builds news filter options for every configured ticker", () => {
    const options = trackedTickerFilterOptions([{ key: "RKLB", label: "Rocket Lab USA, Inc.", count: 2 }]);

    expect(options).toHaveLength(trackedTickers.length);
    expect(options.find((option) => option.key === "RKLB")).toMatchObject({ count: 2 });
    expect(options.find((option) => option.key === "AMD")).toMatchObject({ count: 0 });
  });

  it("matches ticker filters by symbol and route key", () => {
    expect(tickerMatchesFilterValue("NVDA", undefined)).toBe(true);
    expect(tickerMatchesFilterValue("NVDA", "")).toBe(true);
    expect(tickerMatchesFilterValue("UNKNOWN", "UNKNOWN")).toBe(true);
    expect(tickerMatchesFilterValue("005930.KS", "005930_KS")).toBe(true);
    expect(tickerMatchesFilterValue("RKLB", "RKLB")).toBe(true);
    expect(tickerMatchesFilterValue("NVDA", "RKLB")).toBe(false);
  });

  it("searches configured tickers by company aliases", () => {
    expect(searchTrackedTickers("rocket").map((ticker) => ticker.symbol)).toContain("RKLB");
    expect(searchTrackedTickers("semiconductor").map((ticker) => ticker.symbol)).toContain("NVDA");
    expect(searchTrackedTickers("", 2)).toHaveLength(2);
    expect(searchTrackedTickers("rocket", -1)).toHaveLength(0);
    expect(searchTrackedTickers("no such ticker")).toHaveLength(0);
  });

  it("localizes tracked entity display names", () => {
    const rklb = getTrackedTicker("RKLB");
    expect(rklb).toBeDefined();
    expect(entityDisplayName(rklb!, "en")).toBe(rklb!.name);
    expect(entityDisplayName(rklb!, "ko")).toBe(rklb!.nameKo);
  });
});
