import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardProvider } from "../context/DashboardContext";
import { QuotaSidebar, QuotaValuePage, ResetsPage, PricingPage, validatePriceValues } from "../pages/QuotaPages";

const savedAt = "2026-10-01T02:00:00+00:00";
const resetAt = "2026-09-30T02:00:00+00:00";
const cycle = {
  id: 1, slot: "primary", limit_id: "codex", window_minutes: 300, plan_type: "plus",
  used_percent: 25, remaining_percent: 75, fetched_at: savedAt, cycle_start_at: resetAt,
  resets_at: "2026-10-01T07:00:00+00:00", total: { api_usd_known: 8, calls: 3, total_tokens: 100 },
  usd_per_percent: 0.32, full_quota_usd: 32, remaining_quota_usd: 24,
  observation_count: 2, is_current: true, price_mode: "snapshot",
};
const offlineQuota = {
  status: "error", message: "读取额度失败，请检查 Codex CLI 后重试。", windows: [{ remaining_percent: 75 }],
  history_mode: "offline", history_label: "上次保存的账号", history_fetched_at: savedAt,
  reset_history_scope: "account-a", reset_history_status: "available", value_history_status: "available",
  checked_at: savedAt, reset_records: [{ reset_at: resetAt, slot: "primary", limit_id: "codex", window_minutes: 300, method: "regular" }],
};
const liveQuota = { ...offlineQuota, status: "ready", message: null, fetched_at: savedAt, history_mode: "verified", history_label: "当前账号", plan_type: "plus", windows: [{ ...cycle, resets_at: Date.parse(cycle.resets_at) / 1000 }] };
const config = { timezone: "Asia/Taipei", defaultStart: "2026-10-02", defaultEnd: "2026-10-02", minimumDate: "2026-08-01", maximumDate: "2026-10-02" };
const response = payload => ({ ok: true, json: async () => payload });
const historyResponse = cycles => ({ status: "ready", cycles, total: cycles.length, offset: 0, has_more: false });
function LocationProbe() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output>; }
function mount(children, quota = offlineQuota, pathname = "/quota-value") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  if (quota !== null) client.setQueryData(["quota"], quota);
  const result = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[pathname]}><DashboardProvider config={config}>{children}<LocationProbe /></DashboardProvider></MemoryRouter></QueryClientProvider>);
  return { ...result, client };
}
function mockQuotaApis({ history = historyResponse([cycle]), value = { status: "ready", saved: true, fetched_at: savedAt, price_mode: "snapshot", windows: [cycle] } } = {}) {
  vi.stubGlobal("fetch", vi.fn(async path => {
    if (path.startsWith("/api/quota/value/history/")) return response({ status: "ready", cycle, observations: [cycle] });
    if (path.startsWith("/api/quota/value/history?")) return response(history);
    if (path.startsWith("/api/quota/value?")) return response(value);
    throw new Error(`Unexpected API request: ${path}`);
  }));
}
beforeEach(() => {
  document.body.dataset.timezone = "Asia/Taipei";
  vi.stubGlobal("fetch", vi.fn());
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: vi.fn(function () { this.setAttribute("open", ""); }) });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: vi.fn(function () { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); }) });
});

describe("quota saved history", () => {
  it("hides stale live percentages while showing immutable offline amounts and cycle details", async () => {
    mockQuotaApis();
    mount(<><QuotaSidebar /><QuotaValuePage /></>);
    await screen.findByText("View readings");
    expect(document.querySelector("#quotaWindows progress")).toBeNull();
    expect(document.querySelector("#quotaValueTitle").textContent).toBe("Last saved conversion");
    expect(document.querySelector("#quotaValueWindows").textContent).toContain("Saved quota reading");
    expect(document.querySelector("#quotaValueWindows").textContent).toContain("$8.00");
    expect(document.querySelector("#quotaValueHistoryTable").textContent).toContain("Historical cycle");
    expect(document.querySelector("#quotaValueHistoryTable").textContent).not.toContain("Current cycle");
    expect(document.querySelector(".reset-selection").textContent).toContain("Last successful read");
    fireEvent.click(screen.getByText("View readings"));
    await waitFor(() => expect(document.querySelector("#quotaValueObservationTable").textContent).toContain("$8.00"));
    expect(document.querySelector("#quotaValueHistoryDetailStatus").textContent).toContain("last reading is not final usage at reset");
  });

  it("retains prior records and values after temporary history and conversion failures", async () => {
    mockQuotaApis();
    const { client } = mount(<QuotaValuePage />);
    await screen.findByText("View readings");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("Network unavailable"); }));
    await act(async () => { await client.invalidateQueries({ predicate: query => query.queryKey[0] !== "quota" }); });
    expect(document.querySelector("#quotaValueHistoryTable").textContent).toContain("$8.00");
    expect(document.querySelector("#quotaValueWindows").textContent).toContain("$8.00");
    await waitFor(() => expect(document.querySelector("#quotaValueHistoryStatus").textContent).toContain("Displayed records retain values"));
    expect(document.querySelector("#quotaValueHistoryPanel").getAttribute("aria-busy")).toBe("false");
  });

  it("preserves legacy archive provenance when a live refresh fails", async () => {
    const legacy = { ...offlineQuota, history_label: "旧版本本地账号档案（日志目录归属未确认）", history_directory_verified: false };
    mockQuotaApis();
    mount(<><QuotaSidebar /><QuotaValuePage /></>, legacy);
    await screen.findByText("View readings");
    vi.stubGlobal("fetch", vi.fn(async path => {
      if (path === "/api/quota/refresh") throw new Error("Network unavailable");
      throw new Error(`Unexpected API request: ${path}`);
    }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh quota" }));
    await waitFor(() => expect(document.querySelector("#quotaStatus").textContent).toContain("Network unavailable"));
    expect(document.querySelector(".reset-selection").textContent).toContain("Legacy local account archive (log directory ownership unverified)");
    expect(document.querySelector("#quotaValueHistoryTable").textContent).toContain("$8.00");
    expect(document.querySelector("#quotaWindows progress")).toBeNull();
  });

  it("does not restore an earlier account's in-flight history after an account switch", async () => {
    let releaseHistory;
    let historyRequests = 0;
    vi.stubGlobal("fetch", vi.fn(async path => {
      if (path.startsWith("/api/quota/value/history?")) {
        historyRequests += 1;
        if (historyRequests === 1) return new Promise(resolve => { releaseHistory = resolve; });
        return response(historyResponse([]));
      }
      if (path.startsWith("/api/quota/value?")) return response({ status: "ready", saved: true, fetched_at: savedAt, windows: [], price_mode: "snapshot" });
      throw new Error(`Unexpected API request: ${path}`);
    }));
    const { client } = mount(<QuotaValuePage />);
    await waitFor(() => expect(releaseHistory).toBeTypeOf("function"));
    act(() => client.setQueryData(["quota"], { ...offlineQuota, reset_history_scope: "account-b", checked_at: "2026-10-01T03:00:00Z", reset_records: [] }));
    await waitFor(() => expect(historyRequests).toBe(2));
    await act(async () => { releaseHistory(response(historyResponse([cycle]))); });
    expect(document.querySelector("#quotaValueHistoryTable").textContent).not.toContain("$8.00");
    expect(document.querySelector("#quotaValueHistoryTable").textContent).not.toContain("View readings");
  });

  it("clears the selected cycle and amounts immediately when the account scope changes", async () => {
    mockQuotaApis();
    const { client } = mount(<QuotaValuePage />);
    await screen.findByText("View readings");
    fireEvent.click(screen.getByText("View readings"));
    await waitFor(() => expect(document.querySelector("#quotaValueObservationTable").textContent).toContain("$8.00"));
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    act(() => client.setQueryData(["quota"], { ...offlineQuota, reset_history_scope: "account-c", checked_at: "2026-10-01T04:00:00Z" }));
    await waitFor(() => expect(document.querySelector("#quotaValueHistoryDetail")).toBeNull());
    expect(document.querySelector("#quotaValueHistoryTable").textContent).not.toContain("$8.00");
    expect(document.querySelector("#quotaValueWindows").textContent).not.toContain("$8.00");
  });

  it("keeps cycle details open without moving focus when an automatic reading updates", async () => {
    mockQuotaApis();
    const { client } = mount(<QuotaValuePage />);
    fireEvent.click(await screen.findByText("View readings"));
    await waitFor(() => expect(document.querySelector("#quotaValueObservationTable").textContent).toContain("$8.00"));
    const refresh = document.querySelector("#refreshQuotaValueButton");
    refresh.focus();
    const fetch = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn(path => path.startsWith("/api/quota/value/history/")
      ? Promise.resolve(response({ status: "ready", cycle, observations: [{ ...cycle, total: { ...cycle.total, api_usd_known: 16 } }] }))
      : fetch(path)));
    act(() => client.setQueryData(["quota"], { ...offlineQuota, checked_at: "2026-10-01T03:00:00Z" }));
    expect(document.querySelector("#quotaValueHistoryDetail")).not.toBeNull();
    await waitFor(() => expect(document.querySelector("#quotaValueObservationTable").textContent).toContain("$16.00"));
    expect(document.activeElement).toBe(refresh);
  });

  it("keeps reset expiration dates open for the same account and closes them on an account switch", async () => {
    const quota = { ...liveQuota, reset_credits_available: 1, reset_credits: [{ title: "Full reset", expires_at: 1793300934 }] };
    const { client } = mount(<QuotaSidebar />, quota);
    fireEvent.click(screen.getByRole("button", { name: "Available quota resets: 1" }));
    expect(document.querySelector("#quotaResetPopover").open).toBe(true);
    act(() => client.setQueryData(["quota"], { ...quota, checked_at: "2026-10-01T03:00:00Z", reset_credits: [{ title: "Updated reset" }] }));
    await screen.findByText("Updated reset");
    expect(document.querySelector("#quotaResetPopover").open).toBe(true);
    act(() => client.setQueryData(["quota"], { ...quota, reset_history_scope: "account-b" }));
    await waitFor(() => expect(document.querySelector("#quotaResetPopover").open).toBe(false));
  });

  it("shows raw archive failures without hiding usable values", async () => {
    mockQuotaApis({ value: { status: "ready", fetched_at: savedAt, price_mode: "snapshot", windows: [cycle] } });
    mount(<><QuotaSidebar /><QuotaValuePage /></>, { ...liveQuota, archive_status: "error", reset_history_status: "error", value_history_status: "error" });
    await screen.findByText("View readings");
    expect(document.querySelector("#quotaStatus").textContent).toContain("Raw quota readings could not be saved");
    expect(document.querySelector("#quotaStatus").textContent).toContain("Reset records could not be saved");
    expect(document.querySelector("#quotaValueStatus").textContent).toContain("amounts remain available");
    expect(document.querySelector("#quotaValueWindows").textContent).toContain("$8.00");
  });
});

describe("quota controls", () => {
  it("renders the reset page while the first quota request is pending, then shows saved records", async () => {
    let releaseQuota;
    vi.stubGlobal("fetch", vi.fn(path => {
      if (path === "/api/quota") return new Promise(resolve => { releaseQuota = resolve; });
      throw new Error(`Unexpected API request: ${path}`);
    }));
    mount(<ResetsPage />, null, "/resets");
    expect(document.querySelector("#resetHistoryStatus").textContent).toBe("Reading reset records…");
    expect(screen.getByText("Choose the first time")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reading…" }).disabled).toBe(true);
    await waitFor(() => expect(releaseQuota).toBeTypeOf("function"));
    await act(async () => { releaseQuota(response(offlineQuota)); });
    const savedReset = await screen.findByRole("button", { name: /Select time, 2026-09-30 10:00,/ });
    expect(savedReset.disabled).toBe(false);
    expect(document.querySelector("#resetHistoryStatus").textContent).toContain("Offline history · Last saved account");
    expect(document.querySelector("#resetRecords").getAttribute("aria-busy")).toBe("false");
  });

  it("renders an initially unavailable quota with no account history scope", async () => {
    vi.stubGlobal("fetch", vi.fn(async path => {
      if (path === "/api/quota") return response({ status: "unavailable", message: "请先读取账号额度。", history_mode: "unavailable", reset_history_scope: null, reset_records: [] });
      throw new Error(`Unexpected API request: ${path}`);
    }));
    mount(<ResetsPage />, null, "/resets");
    await waitFor(() => expect(document.querySelector("#resetHistoryStatus").textContent).toBe("Read the account quota first."));
    expect(screen.getByText("Choose the first time")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel selection" }).disabled).toBe(true);
    expect(document.querySelectorAll("#resetRecords .reset-record")).toHaveLength(1);
    expect(document.querySelector("#resetRecords").textContent).toContain("Reporting cutoff");
    expect(document.querySelector("#resetRecords").textContent).toContain("No reset records yet.");
    expect(document.querySelector("#resetRecords").getAttribute("aria-busy")).toBe("false");
  });

  it("uses exact reset instants and configured-zone local fields for the overview range", () => {
    const quota = { ...liveQuota, reset_records: [
      { reset_at: "2026-09-30T02:00:31Z", slot: "primary", limit_id: "codex", window_minutes: 300, method: "regular" },
      { reset_at: "2026-10-01T03:02:22Z", slot: "primary", limit_id: "codex", window_minutes: 300, method: "regular" },
    ] };
    mount(<ResetsPage />, quota, "/resets");
    fireEvent.click(screen.getByRole("button", { name: /Select time, 2026-10-01 11:02,/ }));
    fireEvent.click(screen.getByRole("button", { name: /Select time, 2026-09-30 10:00,/ }));
    const location = screen.getByTestId("location").textContent;
    const params = new URLSearchParams(location.split("?")[1]);
    expect(location).toMatch(/^\/overview\?/);
    expect(params.get("start_at")).toBe("2026-09-30T02:00:31.000Z");
    expect(params.get("end_at")).toBe("2026-10-01T03:02:22.000Z");
    expect(params.get("start")).toBe("2026-09-30");
    expect(params.get("start_time")).toBe("10:00");
    expect(params.get("end_time")).toBe("11:02");
  });

  it("preserves external reset titles and exposes known and missing expiration dates", () => {
    mount(<QuotaSidebar />, { ...liveQuota, reset_credits_available: 3, reset_credits_details_available: true, reset_credits: [{ title: "用户的重置", expires_at: null, expiry_known: true }, { title: "External title", expires_at: null, expiry_known: false }] });
    fireEvent.click(screen.getByRole("button", { name: "Available quota resets: 3" }));
    expect(screen.getByRole("dialog").open).toBe(true);
    expect(screen.getByText("用户的重置")).toBeTruthy();
    expect(screen.getByText("No expiration date")).toBeTruthy();
    expect(screen.getByText("Expiration date unavailable")).toBeTruthy();
    expect(screen.getByText("Expiration dates for 1 resets are unavailable.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close expiration dates" }));
    expect(document.querySelector("#quotaResetPopover").open).toBe(false);
  });

  it("scans before refreshing and converting quota", async () => {
    mockQuotaApis();
    mount(<QuotaValuePage />);
    await screen.findByText("View readings");
    const requests = [];
    vi.stubGlobal("fetch", vi.fn(async path => {
      requests.push(path);
      if (path === "/api/scan") return response({ events_added: 1 });
      if (path === "/api/quota/refresh") return response({ ...liveQuota, checked_at: "2026-10-02T02:00:00Z" });
      if (path.startsWith("/api/quota/value/history?")) return response(historyResponse([cycle]));
      if (path.startsWith("/api/quota/value?")) return response({ status: "ready", fetched_at: savedAt, price_mode: "snapshot", windows: [cycle] });
      throw new Error(`Unexpected API request: ${path}`);
    }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh and convert" }));
    await waitFor(() => expect(requests).toContain("/api/quota/refresh"));
    expect(requests.indexOf("/api/scan")).toBeLessThan(requests.indexOf("/api/quota/refresh"));
    await waitFor(() => expect(document.querySelector("#quotaValueHistoryPanel").getAttribute("aria-busy")).toBe("false"));
  });

  it("validates pricing overrides and preserves optional unknown values", () => {
    const fields = { input: "1.25", cached_input: "0", cache_write: "", output: "4", api_fast_multiplier: "" };
    expect(validatePriceValues("model-a", fields)).toEqual({ input: 1.25, cached_input: 0, cache_write: null, output: 4, api_fast_multiplier: null });
    expect(() => validatePriceValues("model-a", { ...fields, input: "" })).toThrow(/nonnegative number/);
    expect(() => validatePriceValues("model-a", { ...fields, cache_write: "-1" })).toThrow(/empty or a nonnegative number/);
    expect(() => validatePriceValues("model-a", { ...fields, api_fast_multiplier: "Infinity" })).toThrow(/empty or a nonnegative number/);
  });

  it("writes pricing overrides with PUT and restores them with DELETE", async () => {
    const item = { model: "model-a", display_name: "用户模型名", official: true, override: { input: 1 }, effective: { input: 1, cached_input: 0.5, cache_write: null, output: 4, api_fast_multiplier: 2 } };
    const writes = [];
    vi.stubGlobal("fetch", vi.fn(async (path, options) => {
      if (path === "/api/pricing") return response({ models: [item], source: "bundled" });
      writes.push({ path, method: options.method, body: options.body && JSON.parse(options.body) });
      return response({ updated: true });
    }));
    mount(<PricingPage />, liveQuota, "/pricing");
    await screen.findByText("用户模型名");
    fireEvent.change(screen.getByLabelText("model-a Input"), { target: { value: "3.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes[0]?.method).toBe("PUT"));
    expect(writes[0].body.input).toBe(3.25);
    expect(writes[0].body.cache_write).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "Restore" }).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(writes[1]?.method).toBe("DELETE"));
    expect(writes[1].path).toBe("/api/pricing/models/model-a/override");
  });
});
