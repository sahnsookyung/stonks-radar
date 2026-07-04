import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NewsScoreBadge } from "./NewsEventCard";

describe("NewsScoreBadge", () => {
  it("renders source-only discovery labels without score-heavy urgency", () => {
    render(<NewsScoreBadge label="Discovery" />);

    expect(screen.getByText("Discovery")).toBeInTheDocument();
    expect(screen.queryByText(/Discovery 82/)).not.toBeInTheDocument();
  });

  it("keeps numeric scores for reviewed breaking items", () => {
    render(<NewsScoreBadge label="Breaking" value={82} />);

    expect(screen.getByText("Breaking 82")).toBeInTheDocument();
  });
});
