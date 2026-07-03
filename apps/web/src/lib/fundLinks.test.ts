import { describe, expect, it } from "vitest";
import { fundLinks, getFundLinkByKey, validateFundLinks } from "./fundLinks";

describe("fund links registry", () => {
  it("contains complete outbound tracker rows", () => {
    expect(fundLinks.length).toBeGreaterThanOrEqual(12);
    for (const entry of fundLinks) {
      expect(entry.human_name).toBeTruthy();
      expect(entry.fund_name).toBeTruthy();
      expect(entry.source_label).toBeTruthy();
      expect(entry.source_type).toBeTruthy();
      expect(entry.note).toBeTruthy();
      expect(entry.primary_url).toMatch(/^https:\/\//);
    }
  });

  it("indexes curated entries and validates unique keys", () => {
    expect(getFundLinkByKey("situational-awareness")).toMatchObject({
      human_name: "Leopold Aschenbrenner",
      fund_name: "Situational Awareness",
      source_label: "HedgeFollow",
    });
    expect(getFundLinkByKey("donald-trump")).toMatchObject({
      human_name: "Donald Trump",
      fund_name: "Donald Trump Stock Trades",
      source_label: "QuiverQuant",
      source_type: "External public-trade tracker",
    });

    expect(() =>
      validateFundLinks([
        fundLinks[0],
        { ...fundLinks[0] },
      ]),
    ).toThrow("duplicate key");
  });

  it("rejects missing or unsafe links", () => {
    expect(() => validateFundLinks("not a registry")).toThrow("must be an array");
    expect(() => validateFundLinks([null])).toThrow("entry 0 must be an object");
    expect(() => validateFundLinks([[fundLinks[0]]])).toThrow("entry 0 must be an object");
    expect(() => validateFundLinks([{ ...fundLinks[0], key: "Bad Key" }])).toThrow("invalid key");
    expect(() => validateFundLinks([{ ...fundLinks[0], primary_url: "http://example.com" }])).toThrow(
      "invalid primary_url",
    );
    expect(() => validateFundLinks([{ ...fundLinks[0], primary_url: "https://[::1" }])).toThrow(
      "invalid primary_url",
    );
    expect(() => validateFundLinks([{ ...fundLinks[0], human_name: "" }])).toThrow("missing human_name");
  });
});
