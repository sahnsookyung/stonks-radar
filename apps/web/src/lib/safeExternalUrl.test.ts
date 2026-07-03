import { describe, expect, it } from "vitest";
import { safeExternalUrl } from "./safeExternalUrl";

describe("safeExternalUrl", () => {
  it("allows explicit http and https URLs", () => {
    expect(safeExternalUrl("https://example.com/path?q=1")).toBe("https://example.com/path?q=1");
    expect(safeExternalUrl("http://example.com/path")).toBe("http://example.com/path");
  });

  it("normalizes protocol-less external source URLs to https", () => {
    expect(safeExternalUrl("example.com/story")).toBe("https://example.com/story");
    expect(safeExternalUrl("//example.com/story")).toBe("https://example.com/story");
  });

  it("rejects unsafe or local href values", () => {
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("data:text/html,hello")).toBeNull();
    expect(safeExternalUrl("/internal/source")).toBeNull();
    expect(safeExternalUrl("not-a-source")).toBeNull();
    expect(safeExternalUrl("https://user:pass@example.com/story")).toBeNull();
  });
});
