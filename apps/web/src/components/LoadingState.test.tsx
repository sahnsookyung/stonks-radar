import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { ErrorState, LoadingState } from "./LoadingState";
import { SnapshotHardExpiredError } from "../lib/snapshots";

describe("ErrorState", () => {
  it("renders an actionable expired-snapshot state", () => {
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <ErrorState error={new SnapshotHardExpiredError("home", "2026-06-06T00:00:00Z")} />
      </QueryClientProvider>
    );

    expect(screen.getByRole("heading", { name: /Public data passed/i })).toBeInTheDocument();
    expect(screen.getByText("home")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try again/i })).toBeInTheDocument();
    expect(screen.getByText(/Last checked/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /admin/i })).not.toBeInTheDocument();
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
