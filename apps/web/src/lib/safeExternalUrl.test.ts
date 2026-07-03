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
    expect(safeExternalUrl(null)).toBeNull();
    expect(safeExternalUrl(undefined)).toBeNull();
    expect(safeExternalUrl("   ")).toBeNull();
    expect(safeExternalUrl("https://[::1")).toBeNull();
    expect(safeExternalUrl("javascript:alert(1)")).toBeNull();
    expect(safeExternalUrl("data:text/html,hello")).toBeNull();
    expect(safeExternalUrl("/internal/source")).toBeNull();
    expect(safeExternalUrl("not-a-source")).toBeNull();
    expect(safeExternalUrl("https://user:pass@example.com/story")).toBeNull();
    expect(safeExternalUrl("https://localhost/story")).toBeNull();
    expect(safeExternalUrl("https://status.localhost/story")).toBeNull();
    expect(safeExternalUrl("https://public.example/story")).toBe("https://public.example/story");
    expect(safeExternalUrl("https://192.0.2.10/story")).toBe("https://192.0.2.10/story");
    expect(safeExternalUrl("https://999.1.1.1/story")).toBeNull();
    expect(safeExternalUrl("https://01.two.3.4/story")).toBeNull();
    expect(safeExternalUrl("https://0.0.0.0/story")).toBeNull();
    expect(safeExternalUrl("https://127.0.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://10.0.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://100.64.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://172.16.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://172.31.255.255/story")).toBeNull();
    expect(safeExternalUrl("https://192.168.1.1/story")).toBeNull();
    expect(safeExternalUrl("https://192.0.0.8/story")).toBeNull();
    expect(safeExternalUrl("https://169.254.1.1/story")).toBeNull();
    expect(safeExternalUrl("https://198.18.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://198.19.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://198.51.100.10/story")).toBeNull();
    expect(safeExternalUrl("https://203.0.113.10/story")).toBeNull();
    expect(safeExternalUrl("https://224.0.0.1/story")).toBeNull();
    expect(safeExternalUrl("https://[::1]/story")).toBeNull();
    expect(safeExternalUrl("https://[fd00::1]/story")).toBeNull();
    expect(safeExternalUrl("https://[fe80::1]/story")).toBeNull();
    expect(safeExternalUrl("https://[2001:db8::1]/story")).toBeNull();
    expect(safeExternalUrl("https://[::ffff:127.0.0.1]/story")).toBeNull();
  });
});
