import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  TICKER_WORKSPACE_STORAGE_KEY,
  emptyTickerWorkspace,
  getMemberSession,
  loadAlertDraft,
  loadTickerWorkspace,
  normalizeTickerWorkspace,
  saveAlertDraft,
  saveComparison,
  toggleWatchedTicker,
  updateTickerNote
} from "./tickerWorkspace";

describe("ticker workspace", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis.window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => store.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => store.set(key, value)),
        removeItem: vi.fn((key: string) => store.delete(key)),
        clear: vi.fn(() => store.clear())
      }
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists normalized anonymous watch, note, and comparison state", () => {
    let workspace = toggleWatchedTicker(emptyTickerWorkspace(), " aapl ");
    workspace = updateTickerNote(workspace, "aapl", "Evidence and counterpoint");
    workspace = saveComparison(workspace, ["aapl", "MSFT", "AAPL", "NVDA", "TSLA"]);

    expect(loadTickerWorkspace()).toMatchObject({
      watchlist: ["AAPL"],
      notes: { AAPL: { content: "Evidence and counterpoint" } },
      comparisons: [{ id: "AAPL:MSFT:NVDA:TSLA", symbols: ["AAPL", "MSFT", "NVDA", "TSLA"] }]
    });
    expect(globalThis.window.localStorage.getItem(TICKER_WORKSPACE_STORAGE_KEY)).not.toContain("undefined");
  });

  it("bounds malformed stored state and preserves merge-conflict copies", () => {
    const workspace = normalizeTickerWorkspace({
      version: 99,
      watchlist: [" aapl ", "bad symbol", "AAPL"],
      notes: {
        aapl: {
          content: "x".repeat(20_100),
          updated_at: "2026-07-14T00:00:00Z",
          conflicts: [{ content: "older", updated_at: "2026-07-13T00:00:00Z" }]
        }
      },
      comparisons: [{ id: "compare<script>", symbols: ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"] }]
    });

    expect(workspace.version).toBe(1);
    expect(workspace.watchlist).toEqual(["AAPL", "BADSYMBOL"]);
    expect(workspace.notes.AAPL.content).toHaveLength(20_000);
    expect(workspace.notes.AAPL.conflicts[0]).toMatchObject({ content: "older", source: "merge" });
    expect(workspace.comparisons[0].symbols).toHaveLength(4);
    expect(workspace.comparisons[0].id).toBe("comparescript");
  });

  it("stores anonymous alert drafts without credentials", () => {
    saveAlertDraft({
      symbol: "AAPL",
      rule_type: "rsi",
      configuration: { operator: "below", value: 30 },
      cooldown_seconds: 3600,
      email_enabled: false
    });

    expect(loadAlertDraft("aapl")).toMatchObject({ symbol: "AAPL", rule_type: "rsi" });
  });

  it("treats invalid or aborted session probes as signed out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ authenticated: false }), { status: 200 })));
    await expect(getMemberSession()).resolves.toBeNull();

    vi.stubGlobal("fetch", vi.fn(async () => { throw new DOMException("aborted", "AbortError"); }));
    await expect(getMemberSession()).resolves.toBeNull();
  });
});
