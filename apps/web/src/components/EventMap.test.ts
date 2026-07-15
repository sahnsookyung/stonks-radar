import { describe, expect, it } from "vitest";
import { clusterLeafRequestLimit } from "./EventMap";

describe("clusterLeafRequestLimit", () => {
  it("requests every item represented by a map cluster", () => {
    expect(clusterLeafRequestLimit(34)).toBe(34);
    expect(clusterLeafRequestLimit(1)).toBe(1);
  });

  it("falls back safely for an invalid cluster count", () => {
    expect(clusterLeafRequestLimit(Number.NaN)).toBe(1);
    expect(clusterLeafRequestLimit(0)).toBe(1);
  });
});
