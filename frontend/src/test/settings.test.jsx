import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "../App";
import { DashboardProvider, useDashboard } from "../context/DashboardContext";
import { formatCompact, formatDateTime } from "../lib/format";
import { LANGUAGE_STORAGE_KEY, getLanguagePreference, setLanguagePreference, useLocale } from "../lib/i18n";

const originalHome = "C:\\Users\\reporter\\.codex";
const replacementHome = "E:\\Codex\\alternate";
const config = { codexHome: originalHome, timezone: "Asia/Taipei", defaultStart: "2026-10-02", defaultEnd: "2026-10-02", minimumDate: "2026-08-01", maximumDate: "2026-10-02" };
const pricing = {
  source: "bundled", as_of: "2026-10-02", fetched_at: "2026-10-01T17:03:00Z",
  models: [{ model: "existing-model", display_name: "Existing model", official: true, effective: { input: 1, cached_input: 0.1, output: 5, cache_write: null, api_fast_multiplier: 2 } }],
};
const quota = (scope = "original-account") => ({ status: "ready", windows: [], history_mode: "verified", reset_history_scope: scope, history_label: "当前账号", reset_records: [], checked_at: "2026-10-02T01:00:00Z" });
const response = (payload, status = 200) => ({ ok: status < 400, status, json: async () => payload });

function Probes() {
  const dashboard = useDashboard();
  const location = useLocation();
  useLocale();
  return <>
    <output data-testid="location">{location.pathname}{location.search}</output>
    <output data-testid="configuration">{JSON.stringify({ codexHome: dashboard.codexHome, maximumDate: dashboard.maximumDate, quotaScope: dashboard.quota?.reset_history_scope })}</output>
    <output data-testid="formatted">{formatCompact(10000)} | {formatDateTime("2026-10-01T17:03:00Z", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</output>
  </>;
}

function mount(pathname = "/settings", { seedQuota = true } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  if (seedQuota) client.setQueryData(["quota"], quota());
  const result = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[pathname]}><DashboardProvider config={config}><App /><Probes /></DashboardProvider></MemoryRouter></QueryClientProvider>);
  return { ...result, client };
}

function mockSettingsApis({ failSave = false, failScan = false, deferSave = false } = {}) {
  let settings = { codex_home: originalHome, codex_home_exists: true };
  let releaseSave;
  const requests = [];
  vi.stubGlobal("fetch", vi.fn(async (path, options = {}) => {
    const method = options.method || "GET";
    const body = options.body && JSON.parse(options.body);
    requests.push({ path, method, body });
    if (path === "/api/settings" && method === "GET") return response(settings);
    if (path === "/api/settings" && method === "PUT") {
      if (failSave) return response({ detail: "Codex 目录不存在，请选择已有目录。" }, 400);
      settings = { codex_home: body.codex_home, codex_home_exists: true };
      const saved = response({ ...settings, ui_config: { ...config, codexHome: settings.codex_home } });
      if (deferSave) return new Promise(resolve => { releaseSave = () => resolve(saved); });
      return saved;
    }
    if (path === "/api/scan" && method === "POST") {
      if (failScan) return response({ detail: "Scanner is temporarily unavailable" }, 503);
      return response({ stored_events: 12, scanned_files: 2, unchanged_files: 0, parse_errors: 0, missing_directories: [], tier_counts: {}, priority_trace: {} });
    }
    if (path === "/api/ui-config") return response({ ...config, codexHome: settings.codex_home, maximumDate: "2026-10-03" });
    if (path === "/api/quota") return response(quota(settings.codex_home === originalHome ? "original-account" : "replacement-account"));
    if (path === "/api/pricing") return response(pricing);
    throw new Error(`Unexpected API request: ${method} ${path}`);
  }));
  return { requests, releaseSave: () => releaseSave?.() };
}

async function ready() {
  await screen.findByRole("heading", { name: "Model price management" });
  await screen.findByText("Existing model");
  await waitFor(() => expect(screen.getByRole("button", { name: "Save and scan" }).disabled).toBe(false));
}
const directoryInput = () => screen.getByLabelText("Codex log directory");
const configuration = () => JSON.parse(screen.getByTestId("configuration").textContent);

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(navigator, "languages", "get").mockReturnValue(["en-US"]);
  vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
  setLanguagePreference("auto");
  document.body.dataset.timezone = "Asia/Taipei";
});

describe("settings navigation and language", () => {
  it("switches to Chinese immediately, keeps the draft, and follows a Chinese browser in Auto mode", async () => {
    mockSettingsApis();
    mount();
    await ready();
    const draft = "E:\\中文日志\\未保存";
    fireEvent.change(directoryInput(), {target: {value: draft}});
    const language = screen.getByLabelText("Interface language");
    expect(screen.getByRole('option', {name: '中文 (Chinese)'}).value).toBe('zh');
    fireEvent.change(language, {target: {value: 'zh'}});
    expect(screen.getByRole('heading', {level: 1, name: '设置'})).toBeTruthy();
    expect(screen.getByRole('heading', {name: '模型价格管理'})).toBeTruthy();
    expect(screen.getByRole('button', {name: '刷新价格'})).toBeTruthy();
    expect(screen.getByLabelText('Codex 日志目录').value).toBe(draft);
    expect(document.documentElement.lang).toBe('zh');
    expect(document.title).toBe('设置 · Codex Token Report');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('zh');
    expect(screen.getByTestId('formatted').textContent).toContain('1万');
    expect(screen.getByText('Existing model')).toBeTruthy();
    fireEvent.change(language, {target: {value: 'en'}});
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['zh-TW', 'en-US']);
    fireEvent.change(language, {target: {value: 'auto'}});
    expect(document.documentElement.lang).toBe('zh');
    expect(screen.getByLabelText('显示语言').value).toBe('auto');
    expect(screen.getByLabelText('Codex 日志目录').value).toBe(draft);
    expect(screen.getByRole('option', {name: '跟随浏览器'}).selected).toBe(true);
  });

  it("puts pricing inside Settings and redirects the old pricing URL without losing filters", async () => {
    mockSettingsApis();
    const search = "?start=2026-09-20&end=2026-10-01&price_mode=current&grain=hourly";
    mount(`/pricing${search}`);
    await ready();
    expect(screen.getByTestId("location").textContent).toBe(`/settings${search}`);
    expect(screen.getByRole("link", { name: /Settings$/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("link", { name: /Model pricing$/ })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    expect(directoryInput().value).toBe(originalHome);
    expect(screen.getByRole("button", { name: "Refresh prices" })).toBeTruthy();
  });

  it("switches language and formatters immediately while preserving an unsaved directory draft", async () => {
    const { requests } = mockSettingsApis();
    mount();
    await ready();
    const draft = "E:\\Draft directory\\未保存";
    fireEvent.change(directoryInput(), { target: { value: draft } });
    const language = screen.getByLabelText("Interface language");
    fireEvent.change(language, { target: { value: "ja" } });
    expect(document.documentElement.lang).toBe("ja");
    expect(screen.getByRole("heading", { level: 1, name: "設定" })).toBeTruthy();
    expect(screen.getByLabelText("Codexログディレクトリ").value).toBe(draft);
    expect(screen.getByLabelText("表示言語").value).toBe("ja");
    expect(screen.getByTestId("formatted").textContent).toContain("1万");
    expect(screen.getByTestId("formatted").textContent).toContain("2026/10/02 01:03");
    expect(document.title).toBe("設定 · Codex Token Report");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("ja");
    fireEvent.change(language, { target: { value: "en" } });
    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    expect(directoryInput().value).toBe(draft);
    expect(screen.getByTestId("formatted").textContent).toContain("10K");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
    expect(requests.filter(request => request.path === "/api/settings" && request.method === "PUT")).toHaveLength(0);
    expect(requests.filter(request => request.path === "/api/settings" && request.method === "GET")).toHaveLength(1);
  });

  it("follows browser language when Auto is selected and falls back to English for unsupported preferences", async () => {
    mockSettingsApis();
    setLanguagePreference("en");
    const browserLanguages = vi.spyOn(navigator, "languages", "get").mockReturnValue(["ja-JP", "en-US"]);
    mount();
    await ready();
    const language = screen.getByLabelText("Interface language");
    fireEvent.change(language, { target: { value: "auto" } });
    expect(document.documentElement.lang).toBe("ja");
    expect(getLanguagePreference()).toBe("auto");
    expect(screen.getByLabelText("表示言語").value).toBe("auto");
    browserLanguages.mockReturnValue(["fr-FR", "ko-KR"]);
    act(() => window.dispatchEvent(new Event("languagechange")));
    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByLabelText("Interface language").value).toBe("auto");
    expect(screen.getByRole("option", { name: "Follow browser" }).selected).toBe(true);
  });
});

describe("log directory settings", () => {
  it("saves the directory before scanning, then updates the footer, bounds, and account quota state", async () => {
    const { requests } = mockSettingsApis();
    const { client } = mount();
    await ready();
    client.setQueryData(["quota-value", "original-account", "snapshot"], { status: "ready", windows: [{ used_percent: 75 }] });
    fireEvent.change(directoryInput(), { target: { value: replacementHome } });
    fireEvent.click(screen.getByRole("button", { name: "Save and scan" }));
    await waitFor(() => expect(document.querySelector("footer code").textContent).toBe(replacementHome));
    await waitFor(() => expect(configuration().maximumDate).toBe("2026-10-03"));
    const save = requests.find(request => request.path === "/api/settings" && request.method === "PUT");
    expect(save.body).toEqual({ codex_home: replacementHome });
    const saveIndex = requests.indexOf(save), scanIndex = requests.findIndex(request => request.path === "/api/scan");
    expect(scanIndex).toBeGreaterThan(saveIndex);
    expect(configuration().codexHome).toBe(replacementHome);
    expect(client.getQueryData(["settings"]).codex_home).toBe(replacementHome);
    expect(client.getQueryData(["quota-value", "original-account", "snapshot"])).toBeUndefined();
    await waitFor(() => expect(configuration().quotaScope).toBe("replacement-account"));
    expect(await screen.findByText("Log directory saved.")).toBeTruthy();
  });

  it("keeps the previous source and shows a localized error when directory validation fails", async () => {
    const { requests } = mockSettingsApis({ failSave: true });
    const { client } = mount();
    await ready();
    const invalidHome = "E:\\Does not exist";
    fireEvent.change(directoryInput(), { target: { value: invalidHome } });
    fireEvent.click(screen.getByRole("button", { name: "Save and scan" }));
    await screen.findByRole("alert");
    expect(document.querySelector("footer code").textContent).toBe(originalHome);
    expect(configuration().codexHome).toBe(originalHome);
    expect(configuration().quotaScope).toBe("original-account");
    expect(client.getQueryData(["settings"]).codex_home).toBe(originalHome);
    expect(directoryInput().value).toBe(invalidHome);
    expect(screen.getByRole("alert").textContent).toMatch(/directory.*does not exist|existing directory/i);
    expect(screen.getByRole("alert").textContent).not.toContain("目录");
    expect(requests.some(request => request.path === "/api/scan")).toBe(false);
  });

  it("resumes an initial quota read canceled by a failed directory save", async () => {
    mockSettingsApis({ failSave: true });
    const settingsFetch = globalThis.fetch;
    let releaseInitialQuota;
    let quotaRequests = 0;
    const resumedQuota = { ...quota("resumed-account"), plan_type: "plus", windows: [{ limit_id: "codex", slot: "primary", window_minutes: 300, remaining_percent: 55, resets_at: 1790924400 }] };
    vi.stubGlobal("fetch", vi.fn((path, options) => {
      if (path !== "/api/quota") return settingsFetch(path, options);
      quotaRequests += 1;
      if (quotaRequests === 1) return new Promise(resolve => { releaseInitialQuota = resolve; });
      return Promise.resolve(response(resumedQuota));
    }));
    mount("/settings", { seedQuota: false });
    await ready();
    await waitFor(() => expect(releaseInitialQuota).toBeTypeOf("function"));
    expect(document.querySelector("#quotaPanel").getAttribute("aria-busy")).toBe("true");
    fireEvent.change(directoryInput(), { target: { value: "E:\\Does not exist" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and scan" }));
    await screen.findByRole("alert");
    await waitFor(() => expect(quotaRequests).toBe(2));
    await waitFor(() => expect(configuration().quotaScope).toBe("resumed-account"));
    expect(document.querySelector("#quotaPanel").getAttribute("aria-busy")).toBe("false");
    expect(document.querySelector("#quotaWindows progress").value).toBe(55);
    expect(screen.getByRole("button", { name: "Refresh quota" }).disabled).toBe(false);
    expect(configuration().codexHome).toBe(originalHome);
    await act(async () => releaseInitialQuota(response(quota("canceled-account"))));
    expect(configuration().quotaScope).toBe("resumed-account");
  });

  it("retains the saved source when its subsequent scan fails", async () => {
    mockSettingsApis({ failScan: true });
    mount();
    await ready();
    fireEvent.change(directoryInput(), { target: { value: replacementHome } });
    fireEvent.click(screen.getByRole("button", { name: "Save and scan" }));
    await waitFor(() => expect(document.querySelector("footer code").textContent).toBe(replacementHome));
    await screen.findByText("Scanner is temporarily unavailable");
    expect(configuration().codexHome).toBe(replacementHome);
    expect(directoryInput().value).toBe(replacementHome);
  });

  it("does not duplicate a pending save and keeps the draft visible during language changes", async () => {
    const { requests, releaseSave } = mockSettingsApis({ deferSave: true });
    mount();
    await ready();
    fireEvent.change(directoryInput(), { target: { value: replacementHome } });
    fireEvent.click(screen.getByRole("button", { name: "Save and scan" }));
    await waitFor(() => expect(requests.filter(request => request.method === "PUT")).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Saving and scanning…" }).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Interface language"), { target: { value: "ja" } });
    expect(screen.getByLabelText("Codexログディレクトリ").value).toBe(replacementHome);
    expect(requests.filter(request => request.method === "PUT")).toHaveLength(1);
    await act(async () => releaseSave());
    await waitFor(() => expect(document.querySelector("footer code").textContent).toBe(replacementHome));
  });
});
