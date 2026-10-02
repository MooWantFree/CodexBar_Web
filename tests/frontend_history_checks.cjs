const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/codex_token_report/static/app.js"), "utf8");

class Element {
  constructor() {
    this.innerHTML = ""; this.textContent = ""; this.value = "snapshot";
    this.hidden = false; this.disabled = false; this.dataset = {}; this.attrs = {};
    this.classList = {remove() {}, toggle() {}};
  }
  get children() { return this.innerHTML ? [{}] : []; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  replaceChildren() { this.innerHTML = ""; this.textContent = ""; }
  append() {}
  addEventListener() {}
  querySelector() { return null; }
  contains() { return false; }
}

function fixture() {
  const elements = new Map();
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const body = new Element(); body.dataset.timezone = "Asia/Taipei";
  const context = vm.createContext({
    URL, URLSearchParams, Intl,
    location: {pathname: "/quota-value"},
    document: {body, querySelector: element, querySelectorAll: () => [], activeElement: null},
    datePicker: {setResetEvents() {}, dateTime: value => ({date: value.slice(0, 10), clock: "08:00"})},
    fetch: (...args) => context.request(...args),
  });
  vm.runInContext(source.slice(0, source.indexOf("function renderKpis")), context);
  vm.runInContext(source.slice(source.indexOf("function clearSessionQuota"), source.indexOf("async function loadSessions")), context);
  return {context, element, run: code => vm.runInContext(code, context)};
}

const savedAt = "2026-10-01T02:00:00+00:00";
const resetAt = "2026-09-30T02:00:00+00:00";
const cycle = {id: 1, slot: "primary", limit_id: "codex", window_minutes: 300,
  used_percent: 25, fetched_at: savedAt, cycle_start_at: resetAt,
  resets_at: "2026-10-01T07:00:00+00:00", total: {api_usd_known: 8, calls: 3, total_tokens: 100},
  observation_count: 2, is_current: true};
const offlineQuota = {status: "error", message: "额度查询失败", windows: [{remaining_percent: 75}],
  history_mode: "offline", history_label: "上次保存的账号", history_fetched_at: savedAt,
  reset_history_scope: "account-a", reset_history_status: "available", value_history_status: "available",
  reset_records: [{reset_at: resetAt, slot: "primary", limit_id: "codex", window_minutes: 300, method: "regular"}]};

async function main() {
  const {context, element, run} = fixture();
  context.quotaFixture = offlineQuota;
  run("renderQuota(quotaFixture)");
  assert.match(element("#resetHistoryStatus").textContent, /离线历史.*1 个重置时刻/);
  assert.equal(element("#resetHistoryNotice").hidden, false);
  assert.match(element("#resetHistoryNotice").innerHTML, /上次保存的账号.*最后成功读取/s);
  assert.doesNotMatch(element("#quotaWindows").innerHTML, /75%|progress/);

  // A failed live read still fetches both immutable conversion and saved history.
  const requests = [];
  context.request = async url => {
    requests.push(url);
    return {ok: true, json: async () => url.startsWith("/api/quota/value/history")
      ? {status: "ready", history_mode: "offline", cycles: [cycle], total: 1, offset: 0, has_more: false}
      : {status: "ready", saved: true, history_mode: "offline", price_mode: "snapshot", fetched_at: savedAt, windows: [cycle]}};
  };
  await run("loadQuotaValue()");
  assert.equal(requests.length, 2);
  assert.equal(element("#quotaValueTitle").textContent, "最后保存的换算");
  assert.match(element("#quotaValueStatus").textContent, /2026\/10\/0?1.*保留读取时的金额和百分比/);
  assert.match(element("#quotaValueWindows").innerHTML, /当次保存的额度读数.*\$8\.00/s);
  assert.doesNotMatch(element("#quotaValueHistoryTable").innerHTML, /当前周期/);
  assert.match(element("#quotaValueHistoryTable").innerHTML, /历史周期/);

  // Temporary request failures retain already displayed records for this scope.
  const savedRows = element("#quotaValueHistoryTable").innerHTML;
  context.request = async () => { throw new Error("网络失败"); };
  await run("loadQuotaValue()");
  assert.equal(element("#quotaValueHistoryTable").innerHTML, savedRows);
  assert.match(element("#quotaValueHistoryStatus").textContent, /网络失败.*保留/);
  assert.equal(element("#quotaValueHistoryPanel").getAttribute("aria-busy"), "false");
  assert.match(element("#quotaValueWindows").innerHTML, /\$8\.00/);

  // The same account keeps a reset selection; an account switch clears every detail.
  const resetKey = new Date(resetAt).toISOString();
  run(`selectedReset = ${JSON.stringify(resetKey)}; renderQuota(quotaFixture)`);
  assert.equal(run("selectedReset"), resetKey);
  run("selectedQuotaValueCycle = 1; els.quotaValueHistoryDetail.hidden = false");
  context.quotaFixture = {...offlineQuota, reset_history_scope: "account-b", reset_records: []};
  run("renderQuota(quotaFixture)");
  assert.equal(run("selectedReset"), null);
  assert.equal(run("selectedQuotaValueCycle"), null);
  assert.equal(element("#quotaValueHistoryDetail").hidden, true);
  assert.equal(element("#quotaValueWindows").innerHTML, "");
  assert.doesNotMatch(element("#quotaValueHistoryTable").innerHTML, /data-quota-value-cycle="1"/);

  // An earlier account's in-flight history response cannot restore its rows.
  let release;
  context.request = () => new Promise(resolve => { release = resolve; });
  const pending = run("loadQuotaValueHistory()");
  context.quotaFixture = {...offlineQuota, reset_history_scope: "account-c", reset_records: []};
  run("renderQuota(quotaFixture)");
  release({ok: true, json: async () => ({status: "ready", cycles: [cycle], total: 1, offset: 0})});
  await pending;
  assert.doesNotMatch(element("#quotaValueHistoryTable").innerHTML, /data-quota-value-cycle="1"/);

  // Session history uses account-wide samples with ISO reset times and explicit tree scope.
  run("selectedSession = 'session-a'; selectedSessionScope = 'tree'");
  context.request = async url => {
    assert.match(url, /\/api\/sessions\/session-a\/quota/);
    assert.match(url, /include_children=true/);
    return {ok: true, json: async () => ({samples: [{...cycle, timestamp_utc: savedAt, session_id: "child-a"}], total: 1, offset: 0, has_more: false})};
  };
  await run("loadSessionQuota()");
  assert.match(element("#sessionQuotaStatus").textContent, /账号额度读数.*包含子会话/);
  assert.match(element("#sessionQuotaTable").innerHTML, /25%.*2026\/10\/0?1.*child-a/s);
  assert.doesNotMatch(element("#sessionQuotaTable").innerHTML, /Invalid Date/);

  run("selectedSessionScope = 'self'");
  context.request = async url => {
    assert.match(url, /offset=0.*include_children=false/);
    return {ok: true, json: async () => ({samples: [], total: 0, offset: 0, has_more: false})};
  };
  await run("loadSessionQuota()");
  assert.match(element("#sessionQuotaTable").innerHTML, /尚未采集/);

  // Raw snapshot storage failures are visible while live values remain usable.
  const archive = fixture();
  archive.context.quotaFixture = {...offlineQuota, status: "ready", history_mode: "verified",
    history_label: "当前账号", windows: [], archive_status: "error",
    reset_history_status: "error", value_history_status: "error"};
  archive.run("renderQuota(quotaFixture)");
  assert.match(archive.element("#quotaStatus").textContent, /额度原始读数保存失败.*重置记录保存失败.*额度美元历史保存失败/);
  archive.context.valueFixture = {status: "ready", price_mode: "snapshot", fetched_at: savedAt, windows: [cycle]};
  archive.run("renderQuotaValue(valueFixture)");
  assert.match(archive.element("#quotaValueStatus").textContent, /额度原始读数保存失败.*金额仍可查看/);
  assert.match(archive.element("#quotaValueWindows").innerHTML, /\$8\.00/);

  // Network failures must preserve the provenance warning on a legacy offline archive.
  const legacy = fixture();
  const legacyLabel = "旧版本本地账号档案（日志目录归属未确认）";
  legacy.context.quotaFixture = {...offlineQuota, history_label: legacyLabel, history_directory_verified: false};
  legacy.run("renderQuota(quotaFixture)");
  legacy.context.request = async () => { throw new Error("网络失败"); };
  await legacy.run("loadQuota(true)");
  assert.equal(legacy.run("quotaSnapshot.history_label"), legacyLabel);
  assert.match(legacy.element("#resetHistoryNotice").innerHTML, /旧版本本地账号档案（日志目录归属未确认）/);
  assert.match(legacy.element("#quotaValueHistoryNotice").innerHTML, /旧版本本地账号档案（日志目录归属未确认）/);
  console.log("Frontend history behavior checks passed.");
}

main().catch(error => { console.error(error); process.exitCode = 1; });
