import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LineChart } from "./LineChart";

describe("LineChart", () => {
  it("does not render a chart for fewer than two points", () => {
    const { container } = render(<LineChart label="One point" points={[{ date: "2026-01-01", value: 1 }]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a flat chart when all values are equal", () => {
    render(
      <LineChart
        label="Flat range"
        points={[
          { date: "2026-01-01", value: 4.25 },
          { date: "2026-02-01", value: 4.25 },
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Flat range" })).toBeInTheDocument();
  });
});
