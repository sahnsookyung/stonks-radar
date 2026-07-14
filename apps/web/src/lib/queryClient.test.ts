import { describe, expect, it } from "vitest";
import { SnapshotHardExpiredError } from "./snapshots";
import { createAppQueryClient } from "./queryClient";

describe("application query client", () => {
  it("does not retry hard-expired snapshots", () => {
    const options = createAppQueryClient().getDefaultOptions().queries;
    const retry = options?.retry;

    expect(typeof retry).toBe("function");
    expect((retry as (count: number, error: Error) => boolean)(0, new SnapshotHardExpiredError("home", "2026-07-01T00:00:00Z"))).toBe(false);
    expect((retry as (count: number, error: Error) => boolean)(0, new Error("network"))).toBe(true);
    expect((retry as (count: number, error: Error) => boolean)(1, new Error("network"))).toBe(false);
  });

  it("polls failed snapshot queries every minute", () => {
    const options = createAppQueryClient().getDefaultOptions().queries;
    const interval = options?.refetchInterval;
    expect(typeof interval).toBe("function");

    const failedSnapshot = { queryKey: ["snapshot", "home"], state: { status: "error" } };
    const readySnapshot = { queryKey: ["snapshot", "home"], state: { status: "success" } };
    const failedOther = { queryKey: ["member"], state: { status: "error" } };

    expect((interval as (query: unknown) => number | false)(failedSnapshot)).toBe(60_000);
    expect((interval as (query: unknown) => number | false)(readySnapshot)).toBe(false);
    expect((interval as (query: unknown) => number | false)(failedOther)).toBe(false);
  });
});
