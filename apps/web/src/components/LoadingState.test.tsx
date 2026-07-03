import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorState, LoadingState } from "./LoadingState";
import { SnapshotHardExpiredError } from "../lib/snapshots";

describe("ErrorState", () => {
  it("renders an actionable expired-snapshot state", () => {
    render(<ErrorState error={new SnapshotHardExpiredError("home", "2026-06-06T00:00:00Z")} />);

    expect(screen.getByRole("heading", { name: /Public data passed/i })).toBeInTheDocument();
    expect(screen.getByText("home")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open admin system status/i })).toHaveAttribute("href", "/admin/system-config");
  });

  it("renders generic and fallback errors", () => {
    const { rerender } = render(<ErrorState error={new Error("Snapshot missing")} />);
    expect(screen.getByText("Snapshot missing")).toBeInTheDocument();

    rerender(<ErrorState error="not an Error instance" />);
    expect(screen.getByText("Unable to load snapshot")).toBeInTheDocument();
  });
});

describe("LoadingState", () => {
  it("renders the default and custom labels", () => {
    const { rerender } = render(<LoadingState />);
    expect(screen.getByText("Loading snapshot")).toBeInTheDocument();

    rerender(<LoadingState label="Loading curves" />);
    expect(screen.getByText("Loading curves")).toBeInTheDocument();
  });
});
