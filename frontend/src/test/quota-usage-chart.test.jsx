import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QuotaUsageChart } from "../pages/quota/QuotaUsageChart";

describe("quota usage chart", () => {
  it("plots saved readings at their actual times and lets the keyboard inspect them chronologically", () => {
    const observations = [
      { fetched_at: "2026-10-01T01:00:00Z", used_percent: 80 },
      { fetched_at: "2026-10-01T00:10:00Z", used_percent: 10 },
      { fetched_at: "2026-10-01T00:00:00Z", used_percent: 0 },
    ];
    const { container } = render(<QuotaUsageChart observations={observations} />);
    const chart = screen.getByRole("group", { name: "Quota usage over time" });
    const reading = screen.getByRole("status");
    expect(reading.textContent).toContain("80%");
    fireEvent.keyDown(chart, { key: "Home" });
    expect(reading.textContent).toContain("0%");
    expect(reading.querySelector("time").dateTime).toBe("2026-10-01T00:00:00Z");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(reading.textContent).toContain("10%");
    fireEvent.keyDown(chart, { key: "End" });
    expect(reading.textContent).toContain("80%");
    const points = [...container.querySelectorAll(".quota-usage-point")].map(point => Number(point.getAttribute("cx")));
    expect((points[1] - points[0]) / (points[2] - points[0])).toBeCloseTo(1 / 6);
    expect(observations[0].used_percent).toBe(80);
  });

  it("keeps a lone zero-percent reading visible and excludes unknown percentages and invalid times", () => {
    const { container } = render(<QuotaUsageChart observations={[
      { fetched_at: "2026-10-01T00:00:00Z", used_percent: 0 },
      { fetched_at: "2026-10-01T00:10:00Z", used_percent: null },
      { fetched_at: "2026-10-01T00:20:00Z", used_percent: "" },
      { fetched_at: "2026-10-01T00:30:00Z", used_percent: "unknown" },
      { fetched_at: "invalid", used_percent: 50 },
    ]} />);
    expect(screen.getByRole("status").textContent).toContain("0%");
    expect(container.querySelectorAll(".quota-usage-point")).toHaveLength(1);
    expect(container.querySelector("svg").outerHTML).not.toMatch(/NaN|Infinity/);
  });

  it("shows empty feedback when no usable readings are available", () => {
    const { rerender } = render(<QuotaUsageChart observations={[]} />);
    expect(screen.getByText("No snapshots are available for this cycle.")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
    rerender(<QuotaUsageChart observations={[{ fetched_at: "2026-10-01T00:00:00Z", used_percent: null }]} />);
    expect(screen.getByText("No percentage readings are available.")).toBeTruthy();
  });
});
