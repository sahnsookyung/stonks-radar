import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorState } from "./LoadingState";
import { SnapshotHardExpiredError } from "../lib/snapshots";

describe("ErrorState", () => {
  it("renders an actionable expired-snapshot state", () => {
    render(<ErrorState error={new SnapshotHardExpiredError("home", "2026-06-06T00:00:00Z")} />);

    expect(screen.getByRole("heading", { name: /Public data passed/i })).toBeInTheDocument();
    expect(screen.getByText("home")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open status page/i })).toHaveAttribute("href", "/en/status");
  });
});
