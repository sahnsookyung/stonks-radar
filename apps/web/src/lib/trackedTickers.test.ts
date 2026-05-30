import { describe, expect, it } from "vitest";
import { getTrackedTicker, relatedTrackedEntities, resolveTrackedEntity, routeKeyForSymbol } from "./trackedTickers";

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
});
