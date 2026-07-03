import { describe, expect, it } from "vitest";
import { fundLinks, getFundLinkByKey, validateFundLinks } from "./fundLinks";

describe("fund links registry", () => {
  it("contains complete outbound tracker rows", () => {
    expect(fundLinks.length).toBeGreaterThanOrEqual(11);
    for (const entry of fundLinks) {
      expect(entry.human_name).toBeTruthy();
      expect(entry.fund_name).toBeTruthy();
      expect(entry.source_label).toBeTruthy();
      expect(entry.note).toBeTruthy();
      expect(entry.primary_url).toMatch(/^https:\/\/hedgefollow\.com\/funds\//);
    }
  });

  it("indexes Leopold and validates unique keys", () => {
    expect(getFundLinkByKey("situational-awareness")).toMatchObject({
      human_name: "Leopold Aschenbrenner",
      fund_name: "Situational Awareness",
    });

    expect(() =>
      validateFundLinks([
        fundLinks[0],
        { ...fundLinks[0] },
      ]),
    ).toThrow("duplicate key");
  });

  it("rejects missing or unsafe links", () => {
    expect(() => validateFundLinks([{ ...fundLinks[0], primary_url: "http://example.com" }])).toThrow(
      "invalid primary_url",
    );
    expect(() => validateFundLinks([{ ...fundLinks[0], human_name: "" }])).toThrow("missing human_name");
  });
});
