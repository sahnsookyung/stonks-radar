import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import { router } from "./router";
import "./i18n/config";

describe("router", () => {
  it("renders the shell for a locale route", async () => {
    const queryClient = new QueryClient();
    globalThis.window.history.pushState({}, "", "/en/methodology");
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    );
    expect(await screen.findByText(/Source, Review, And Snapshot Methodology/i)).toBeInTheDocument();
  });
});
