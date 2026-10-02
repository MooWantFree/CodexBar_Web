const body = document.body;
const $ = selector => document.querySelector(selector);
const els = {
  start: $("#startDate"), end: $("#endDate"), dateControls: $("#dateControls"),
  startTime: $("#startTime"), endTime: $("#endTime"),
  startAt: $("#startAt"), endAt: $("#endAt"),
  priceMode: $("#priceMode"), grain: $("#trendGrain"), analysisControls: $("#analysisControls"),
  priceNotice: $("#priceModeNotice"), sessionTable: $("#sessionTable"), requestTable: $("#requestTable"),
  sessionSearch: $("#sessionSearch"), sessionSort: $("#sessionSort"),
  status: $("#statusStrip"), scan: $("#scanButton"),
  export: $("#exportLink"), menuToggle: $("#menuToggle"),
  sidebarBackdrop: $("#sidebarBackdrop"), pageTitle: $("#pageTitle"),
  pageEyebrow: $("#pageEyebrow"), pageSubtitle: $("#pageSubtitle"),
  input: $("#inputKpi"), inputDetail: $("#inputDetail"), cached: $("#cachedKpi"),
  cacheRate: $("#cacheRateKpi"), output: $("#outputKpi"), reasoning: $("#reasoningKpi"),
  cost: $("#costKpi"), coverage: $("#coverageKpi"), credits: $("#creditsKpi"),
  fast: $("#fastKpi"), tierCoverage: $("#tierCoverageKpi"), tokenChart: $("#tokenChart"),
  costChart: $("#costChart"), legend: $("#modelLegend"), modelTable: $("#modelTable"),
  dailyTable: $("#dailyTable"), refreshPricing: $("#refreshPricingButton"),
  pricingAsOf: $("#pricingAsOf"), pricingFetchedAt: $("#pricingFetchedAt"),
  pricingStatus: $("#pricingStatus"), pricingTable: $("#pricingTable"),
  projectChart: $("#projectChart"), projectTotalCostChart: $("#projectTotalCostChart"), projectTable: $("#projectTable"),
  projectSelect: $("#projectSelect"), projectTitle: $("#selectedProjectTitle"),
  projectPath: $("#selectedProjectPath"), projectTokenChart: $("#projectTokenChart"),
  projectCostChart: $("#projectCostChart"), projectDailyTable: $("#projectDailyTable"),
  quotaPanel: $("#quotaPanel"), quotaPlan: $("#quotaPlan"), quotaWindows: $("#quotaWindows"),
  quotaStatus: $("#quotaStatus"), refreshQuota: $("#refreshQuotaButton"),
  quotaResetPopover: $("#quotaResetPopover"),
  resetRecords: $("#resetRecords"), resetHistoryStatus: $("#resetHistoryStatus"),
  resetHistoryNotice: $("#resetHistoryNotice"), quotaValueHistoryNotice: $("#quotaValueHistoryNotice"),
  quotaValueTitle: $("#quotaValueTitle"),
  resetSelectionStatus: $("#resetSelectionStatus"), clearResetSelection: $("#clearResetSelection"), refreshResets: $("#refreshResetsButton"),
  quotaValueWindows: $("#quotaValueWindows"), quotaValueStatus: $("#quotaValueStatus"),
  quotaValuePriceMode: $("#quotaValuePriceMode"), refreshQuotaValue: $("#refreshQuotaValueButton"),
  quotaValueHistoryPanel: $("#quotaValueHistoryPanel"), quotaValueHistoryStatus: $("#quotaValueHistoryStatus"),
  quotaValueHistoryTable: $("#quotaValueHistoryTable"), quotaValueHistoryPrev: $("#quotaValueHistoryPrev"),
  quotaValueHistoryNext: $("#quotaValueHistoryNext"), quotaValueHistoryPage: $("#quotaValueHistoryPage"),
  quotaValueHistoryDetail: $("#quotaValueHistoryDetail"), quotaValueHistoryDetailTitle: $("#quotaValueHistoryDetailTitle"),
  quotaValueHistoryDetailStatus: $("#quotaValueHistoryDetailStatus"), quotaValueObservationTable: $("#quotaValueObservationTable"),
  closeQuotaValueHistoryDetail: $("#closeQuotaValueHistoryDetail"),
  sessionQuotaPanel: $("#sessionQuotaPanel"), sessionQuotaStatus: $("#sessionQuotaStatus"),
  sessionQuotaTable: $("#sessionQuotaTable"), sessionQuotaPrev: $("#sessionQuotaPrev"),
  sessionQuotaNext: $("#sessionQuotaNext"), sessionQuotaPage: $("#sessionQuotaPage"),
};
body.append(els.quotaResetPopover);

const routes = {
  "/": ["overview", "用量总览", "USAGE OVERVIEW", "Token、模型与 API 等价成本概览。"],
  "/overview": ["overview", "用量总览", "USAGE OVERVIEW", "Token、模型与 API 等价成本概览。"],
  "/pricing": ["pricing", "模型定价", "MODEL PRICING", "管理 models.dev 价格缓存与本地手工覆盖。"],
  "/daily": ["daily", "每日明细", "DAILY LEDGER", "逐日核对调用、Token 与等价成本。"],
  "/projects": ["projects", "项目用量", "PROJECT USAGE", "按 Git 项目查看总量与每日使用情况。"],
  "/resets": ["resets", "重置日期", "RESET HISTORY", "查看重置时间，选择两个时刻统计期间用量。"],
  "/quota-value": ["quota-value", "额度等价美元", "QUOTA VALUE", "从本周期已用额度，推算每 1% 和整窗额度的 API 等价美元。"],
  "/sessions": ["sessions", "会话用量", "SESSION USAGE", "查看会话排行、用量趋势与每次调用。"],
};
const state = { report: null, reportKey: "", projects: null, projectsKey: "", pricingLoaded: false };
let resetRecords = [];
const todayReset = { key: "today", stamp: 0, labels: new Set(["今天"]), methods: new Set(), today: true };
let selectedReset = null;
let resetAccountScope = null;
let quotaLoading = false;
let quotaSnapshot = null;
let quotaValueReport = null, quotaValueReportScope = null;
let quotaValueGeneration = 0;
let quotaValueRefreshing = false;
let quotaValueScanning = false;
let quotaValueHistoryGeneration = 0, quotaValueDetailGeneration = 0;
let quotaValueHistoryOffset = 0, quotaValueHistoryData = null, selectedQuotaValueCycle = null;
const quotaValueHistoryPageSize = 20;
let resetCreditExpiries = [];
let sessionData = null;
let selectedSession = null, selectedSessionScope = "tree", sessionPage = 0, requestOffset = 0;
let sessionQuotaOffset = 0, sessionQuotaGeneration = 0, sessionQuotaData = null;
let sessionQuotaSelection = null;
const expandedSessions = new Set();
const pageSize = 50;
const number = new Intl.NumberFormat("zh-CN");
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 });
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });
const moneyPrecise = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 6 });
const quotaPlans = { free: "Free", go: "Go", plus: "Plus", pro: "Pro", prolite: "Pro Lite", team: "Team", business: "Business", enterprise: "Enterprise", edu: "Edu" };
const knownModelColors = Object.freeze({
  "gpt-6-astra": "#7655c5", "gpt-5.6-sol": "#277ad9", "gpt-5.6-terra": "#2f8a57",
  "gpt-5.6-luna": "#168e94", "codex-auto-review": "#b66a12",
});

function formatNumber(value) { return number.format(value || 0); }
function fastSurcharge(row, precise = false) {
  const amount = (precise ? moneyPrecise : money).format(row.fast_surcharge_usd || 0);
  if (!row.unknown_fast_price_calls) return amount;
  return row.fast_surcharge_usd ? `${amount} + 未知` : "未知";
}
function formatCompact(value) { return compact.format(value || 0); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
}
function modelColor(model) {
  const normalized = String(model || "unknown").toLowerCase();
  if (knownModelColors[normalized]) return knownModelColors[normalized];
  let hash = 0;
  for (const char of normalized) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `hsl(${((hash % 360) + 360) % 360} 52% 52%)`;
}
function queryString(extra = {}) {
  const params = new URLSearchParams();
  if (els.start.value) params.set("start", els.start.value);
  if (els.end.value) params.set("end", els.end.value);
  params.set("start_time", els.startTime.value);
  params.set("end_time", els.endTime.value);
  params.set("price_mode", els.priceMode.value);
  params.set("grain", els.grain.value);
  if (currentRoute()[0] === "sessions" && selectedSession) {
    params.set("session", selectedSession);
    params.set("session_scope", selectedSessionScope);
  }
  if (els.startAt.value && els.endAt.value) { params.set("start_at", els.startAt.value); params.set("end_at", els.endAt.value); }
  for (const [key, value] of Object.entries(extra)) if (value !== undefined) params.set(key, value);
  return params.toString();
}
function setStatus(message, kind = "") {
  els.status.hidden = !message;
  els.status.innerHTML = `<span class="${kind}">${escapeHtml(message)}</span>`;
}
function currentRoute() { return routes[location.pathname] || routes["/overview"]; }
function invalidateUsage() {
  state.report = null; state.reportKey = ""; state.projects = null; state.projectsKey = "";
  sessionData = null; requestOffset = 0; sessionPage = 0;
}

function renderPriceNotice(inferred = 0) {
  const current = els.priceMode.value === "current";
  els.priceNotice.textContent = current ? "按当前价格重算 · 已包含 Fast API 加价"
    : inferred ? `快照估算 · ${formatNumber(inferred)} 次调用使用首次采集价格回填`
      : "按调用时已保存的价格估算 · 已包含 Fast API 加价";
  els.priceNotice.title = current ? "按当前有效价格重算；API 等价已包含 Fast API 加价。"
    : `按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。${inferred ? `其中 ${formatNumber(inferred)} 次旧调用使用首次采集价格，属于回填估算，无法确认当时官方价。` : ""}`;
  if (els.grain.value === "hourly") els.priceNotice.title += " 小时趋势仅显示有调用的小时。";
  els.analysisControls.querySelectorAll("[data-grain]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.grain === els.grain.value)));
}

const restartBackendMessage = "运行中的后端版本较旧，请关闭旧服务并重新运行 codex_ana.bat，然后刷新页面。";
function validatePriceMode(report) {
  if (report.range?.price_mode !== els.priceMode.value) throw new Error(restartBackendMessage);
}
function trendRows(report) {
  const rows = report[els.grain.value];
  if (!Array.isArray(rows)) throw new Error(restartBackendMessage);
  return rows;
}
function renderTrend(report, token, cost, tokenTitle, costTitle) {
  const hourly = els.grain.value === "hourly";
  token.classList.toggle("hourly-chart", hourly); cost.classList.toggle("hourly-chart", hourly);
  $(tokenTitle).textContent = `${hourly ? "每小时" : "每日"} Token · 按模型`;
  $(costTitle).textContent = `${hourly ? "每小时" : "每日"} API 等价美元 · 按模型`;
  let rows;
  try { validatePriceMode(report); rows = trendRows(report); }
  catch (error) {
    token.innerHTML = cost.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    throw error;
  }
  renderStackedChart(token, rows, "total_tokens");
  renderStackedChart(cost, rows, "api_usd_known");
}

function quotaWindowLabel(window) {
  const minutes = window.window_minutes;
  let label = window.slot === "primary" ? "主额度窗口" : "次额度窗口";
  if (minutes === 10080) label = "每周额度";
  else if (minutes && minutes % 1440 === 0) label = `${minutes / 1440} 天额度`;
  else if (minutes && minutes % 60 === 0) label = `${minutes / 60} 小时额度`;
  else if (minutes) label = `${minutes} 分钟额度`;
  return window.limit_id === "codex" ? label : `${window.limit_name} · ${label}`;
}

function quotaTime(value, options = {}) {
  return new Date(value).toLocaleString("zh-CN", { timeZone: body.dataset.timezone, ...options });
}

function quotaHistoryAvailable(quota) {
  return quota?.history_mode !== "unavailable" && Boolean(quota?.reset_history_scope);
}

function quotaHistoryContext(quota = quotaSnapshot) {
  const label = quota?.history_label || (quota?.history_mode === "offline" ? "上次保存的账号" : "当前账号");
  return quota?.history_mode === "offline" ? `离线历史 · ${label}`
    : quota?.status !== "ready" ? `${label} · 本地历史（实时额度暂不可用）` : `${label} · 已保存历史`;
}

function renderQuotaHistoryNotice(quota) {
  const show = quotaHistoryAvailable(quota) && (quota.status !== "ready" || quota.history_mode === "offline");
  for (const notice of [els.resetHistoryNotice, els.quotaValueHistoryNotice]) {
    notice.hidden = !show;
    notice.innerHTML = show ? `<span class="unknown"><strong>${escapeHtml(quotaHistoryContext(quota))}</strong><br>最后成功读取：${escapeHtml(quotaValueTime(quota.history_fetched_at))}。当前显示已保存记录，金额和百分比保留当时的值。</span>` : "";
  }
}

function updateResetCreditWarning() {
  const now = Date.now();
  const urgent = resetCreditExpiries.some(expiry => expiry > now && expiry - now <= 72 * 60 * 60 * 1000);
  els.quotaStatus.querySelector(".quota-reset-trigger")?.classList.toggle("expiring", urgent);
  els.refreshQuota.classList.toggle("expiring", urgent);
}

function renderResetCredits(quota) {
  const credits = Array.isArray(quota.reset_credits) ? quota.reset_credits : [];
  resetCreditExpiries = credits.map(credit => credit.expires_at * 1000)
    .filter(expiry => Number.isFinite(expiry) && expiry > 0);
  if (els.quotaResetPopover.open) els.quotaResetPopover.close();
  const count = quota.reset_credits_available;
  if (!(quota.status === "ready" && count > 0)) {
    els.quotaResetPopover.replaceChildren();
    updateResetCreditWarning();
    return;
  }
  const rows = credits.map((credit, index) => {
    const expiry = credit.expires_at == null ? (credit.expiry_known ? "无到期时间" : "到期时间未提供") :
      `到期：${quotaTime(credit.expires_at * 1000, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZoneName: "short" })}`;
    return `<li><strong>${escapeHtml(credit.title || `额度重置 ${index + 1}`)}</strong><span>${escapeHtml(expiry)}</span></li>`;
  });
  const missing = Math.max(0, count - credits.length);
  els.quotaResetPopover.innerHTML = `<div class="quota-reset-popover-heading"><strong class="quota-reset-popover-title">可用额度重置到期时间</strong><button type="button" class="quota-reset-close" aria-label="关闭到期时间">×</button></div>
    ${rows.length ? `<ul>${rows.join("")}</ul>` : ""}
    ${missing || !quota.reset_credits_details_available ? `<p>${missing ? `${formatNumber(missing)} 次重置` : "重置"}的到期时间暂未提供。</p>` : ""}`;
  updateResetCreditWarning();
}

function renderQuota(quota) {
  const scopeChanged = quota.reset_history_scope !== quotaSnapshot?.reset_history_scope;
  quotaSnapshot = quota;
  quotaValueGeneration += 1;
  if (scopeChanged || !quotaHistoryAvailable(quota)) {
    quotaValueReport = null; quotaValueReportScope = null;
    els.quotaValueWindows.replaceChildren();
    clearQuotaValueHistory(quotaHistoryAvailable(quota) ? "正在读取已保存历史…" : quota.message || "暂无可读取的本地历史", { resetPage: true });
  } else if (quota.status !== "ready" && quotaValueReport) {
    renderQuotaValue({...quotaValueReport, saved: true, history_mode: quota.history_mode, history_label: quota.history_label});
  }
  if (!quotaValueReport) els.quotaValueStatus.textContent = quota.status === "ready" ? "正在换算本周期额度…" : "正在读取最后保存的换算…";
  renderQuotaHistoryNotice(quota);
  datePicker.setResetEvents(quota.reset_events || []);
  renderResetHistory(quota);
  els.quotaPlan.textContent = quota.status !== "ready" ? "实时不可用" : quota.plan_type ? (quotaPlans[quota.plan_type] || quota.plan_type) : "套餐未知";
  els.quotaPlan.classList.remove("quota-skeleton");
  els.quotaPlan.removeAttribute("aria-label");
  els.quotaPlan.title = els.quotaPlan.textContent;
  els.quotaWindows.innerHTML = (quota.status === "ready" ? quota.windows || [] : []).map(window => {
    const remaining = window.remaining_percent;
    const label = quotaWindowLabel(window);
    const reset = window.resets_at == null ? "重置时间未提供" : `重置于 ${quotaTime(window.resets_at * 1000, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false })}`;
    const resetDetail = window.resets_at == null ? reset : `重置于 ${quotaTime(window.resets_at * 1000)}`;
    const percent = remaining == null ? "—" : `${Number(remaining.toFixed(1))}%`;
    return `<article class="quota-window${remaining != null && remaining <= 20 ? " low" : ""}">
      <div class="quota-window-heading"><p>${escapeHtml(label)} · 剩余</p><strong>${percent}</strong></div>
      ${remaining == null ? "" : `<progress max="100" value="${remaining}" aria-label="${escapeHtml(label)}剩余 ${percent}"></progress>`}
      <small title="${escapeHtml(resetDetail)}">${escapeHtml(reset)}</small></article>`;
  }).join("");
  if (!els.quotaWindows.children.length) els.quotaWindows.innerHTML = '<div class="quota-empty">额度暂不可用</div>';
  let message = quota.message || "额度暂不可用";
  let resetCount = 0;
  if (quota.status === "ready") {
    const notices = [];
    if (!quota.windows?.length) notices.push("服务端未提供百分比额度");
    resetCount = quota.reset_credits_available || 0;
    if (resetCount > 0) notices.push(`可用额度重置次数 ${formatNumber(resetCount)}`);
    if (quota.archive_status === "error") notices.push("额度原始读数保存失败");
    if (quota.reset_history_status === "error") notices.push("重置记录保存失败");
    if (quota.value_history_status === "error") notices.push("额度美元历史保存失败，本次金额仍可查看");
    message = notices.join(" · ");
  }
  els.quotaStatus.replaceChildren();
  if (resetCount > 0) {
    const label = `可用额度重置次数 ${formatNumber(resetCount)}`;
    const [before, after] = message.split(label);
    els.quotaStatus.append(document.createTextNode(before));
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "quota-reset-trigger";
    trigger.textContent = label;
    trigger.setAttribute("aria-controls", "quotaResetPopover");
    trigger.setAttribute("aria-haspopup", "dialog");
    trigger.setAttribute("aria-expanded", "false");
    els.quotaStatus.append(trigger, document.createTextNode(after || ""));
  } else els.quotaStatus.textContent = message || "";
  els.quotaStatus.hidden = !message;
  els.quotaStatus.title = message || "";
  els.quotaStatus.className = `fine-print${quota.status === "error" ? " error-text" : ""}`;
  renderResetCredits(quota);
  els.quotaValueHistoryPanel.setAttribute("aria-busy", "false");
  updateQuotaValueHistoryPager();
}

async function loadQuota(force = false) {
  if (quotaLoading) return;
  quotaLoading = true;
  quotaValueGeneration += 1;
  els.quotaValueWindows.setAttribute("aria-busy", "true");
  els.quotaValueStatus.textContent = "正在读取账号额度…";
  beginQuotaValueHistoryLoad("正在读取账号额度；已保存历史仍可查看…");
  els.quotaPanel.setAttribute("aria-busy", "true");
  els.refreshQuota.disabled = true;
  els.refreshQuota.textContent = "读取中…";
  els.refreshResets.disabled = true;
  els.refreshResets.textContent = "读取中…";
  updateQuotaValueButton();
  try {
    const response = await fetch(force ? "/api/quota/refresh" : "/api/quota", { method: force ? "POST" : "GET" });
    if (!response.ok) throw new Error("读取额度失败，请稍后刷新。");
    renderQuota(await response.json());
  } catch (error) {
    const previous = quotaSnapshot;
    renderQuota({ ...previous, status: "error", plan_type: null, windows: [], credits: null,
      history_mode: quotaHistoryAvailable(previous) ? "offline" : "unavailable",
      history_label: previous?.history_mode === "offline" || previous?.history_directory_verified === false
        ? previous.history_label || "上次保存的账号" : "上次保存的账号",
      history_fetched_at: previous?.history_fetched_at || previous?.fetched_at,
      message: error.message });
  } finally {
    quotaLoading = false;
    els.quotaPanel.setAttribute("aria-busy", "false");
    els.refreshQuota.disabled = quotaValueRefreshing;
    els.refreshQuota.textContent = "刷新额度";
    els.refreshResets.disabled = quotaValueRefreshing;
    els.refreshResets.textContent = "刷新记录";
    updateQuotaValueButton();
  }
  if (currentRoute()[0] === "quota-value") await loadQuotaValue();
}

function updateQuotaValueButton() {
  els.refreshQuotaValue.disabled = quotaLoading || quotaValueRefreshing;
  els.quotaValuePriceMode.disabled = quotaLoading || quotaValueRefreshing;
  els.refreshQuotaValue.textContent = quotaValueRefreshing ? "刷新中…" : quotaLoading ? "读取中…" : "刷新并换算";
  updateQuotaValueHistoryPager();
}

function quotaValueTime(value) {
  return value ? quotaTime(value, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "未知";
}

function renderQuotaValue(report) {
  const saved = report.saved || quotaSnapshot?.status !== "ready";
  if (report.status === "ready") {
    quotaValueReport = report; quotaValueReportScope = quotaSnapshot?.reset_history_scope;
  }
  els.quotaValueTitle.textContent = saved ? "最后保存的换算" : "本周期额度换算";
  const plan = report.plan_type ? quotaPlans[report.plan_type] || report.plan_type : "套餐未知";
  els.quotaValueStatus.textContent = report.status === "ready"
    ? `${saved ? `${quotaHistoryContext(report)} · 最后保存的换算 · ` : ""}${plan} · 额度读取于 ${quotaValueTime(report.fetched_at)} · ${report.price_mode === "current" ? saved ? "当次当前价格换算" : "当前价格重算" : "快照估算"}${saved ? " · 保留读取时的金额和百分比" : ""}`
    : report.message || "额度暂不可用，请刷新重试。";
  if (report.archive_status === "error" || quotaSnapshot?.archive_status === "error") {
    els.quotaValueStatus.textContent += " · 额度原始读数保存失败，本次金额仍可查看。";
  }
  if (report.value_history_status === "error" || quotaSnapshot?.value_history_status === "error") {
    els.quotaValueStatus.textContent += " · 本次额度美元历史保存失败，当前金额仍可查看。";
  }
  els.quotaValueWindows.innerHTML = (report.windows || []).map(window => {
    const total = window.total;
    const used = window.used_percent;
    const percent = used == null ? "未知" : `${Number(used.toFixed(2))}%`;
    const partial = total?.unknown_price_calls > 0;
    const amount = total ? money.format(total.api_usd_known) : "未知";
    const coverage = total ? `${formatNumber(total.calls)} 次调用 · ${formatNumber(total.total_tokens)} Token · ${partial ? `${formatNumber(total.unknown_price_calls)} 次价格未知` : "价格完整"}` : "暂无可换算的调用样本";
    const notes = [window.message];
    if (total?.unknown_tier_calls) notes.push(`${formatNumber(total.unknown_tier_calls)} 次档位未知，按 Standard 基础价估算。`);
    if (report.price_mode === "snapshot" && total?.inferred_price_calls) notes.push(`${formatNumber(total.inferred_price_calls)} 次调用使用首次采集价格回填。`);
    const extrapolate = value => value == null ? "未知" : money.format(value);
    return `<article class="panel quota-value-card">
      <div class="panel-heading"><h2>${escapeHtml(quotaWindowLabel(window))}</h2><span class="reset-badge${window.cycle_start_estimated ? " estimated" : ""}">${window.cycle_start_at ? window.cycle_start_estimated ? "起点推测" : "起点已确认" : "起点未知"}</span></div>
      <div class="quota-value-range"><span>周期开始 <strong>${escapeHtml(quotaValueTime(window.cycle_start_at))}</strong></span><span>统计截止 <strong>${escapeHtml(quotaValueTime(report.fetched_at))}</strong></span><span>${saved ? "当次计划重置" : "下次重置"} <strong>${escapeHtml(quotaValueTime(window.resets_at))}</strong></span></div>
      <dl class="quota-value-metrics">
        <div><dt>期间已用额度</dt><dd>${percent}</dd><small>${saved ? "当次保存的额度读数" : "服务端额度读数"}</small></div>
        <div><dt>${partial ? "期间已知 API 等价" : "期间 API 等价"}</dt><dd>${amount}</dd><small>${escapeHtml(coverage)}</small></div>
        <div><dt>${partial ? "每 1% 已知金额估算" : "每 1% 等价美元"}</dt><dd>${extrapolate(window.usd_per_percent)}</dd><small>${partial ? "已知金额" : "期间金额"} ÷ 已用百分比</small></div>
        <div><dt>整窗 100% 估算</dt><dd>${extrapolate(window.full_quota_usd)}</dd><small>${partial ? "按已知金额外推" : saved ? "按当次样本比例外推" : "按当前样本比例外推"}</small></div>
      </dl>
      <p class="fine-print quota-value-remaining">${saved ? "当次" : ""}${partial ? "剩余额度已知金额估算" : "剩余额度等价估算"}：<strong>${extrapolate(window.remaining_quota_usd)}</strong>${window.remaining_percent == null ? "" : `（${saved ? "当时" : ""}剩余 ${Number(window.remaining_percent.toFixed(2))}%）`}</p>
      ${notes.filter(Boolean).length ? `<p class="fine-print unknown">${escapeHtml(notes.filter(Boolean).join(" "))}</p>` : ""}
    </article>`;
  }).join("") || `<div class="panel empty-state">${escapeHtml(report.message || "服务端未提供可换算的百分比额度窗口。")}</div>`;
}

async function loadQuotaValue() {
  if (!quotaSnapshot || quotaLoading || quotaValueScanning) return;
  await Promise.all([loadQuotaValueCurrent(), loadQuotaValueHistory(true)]);
}

async function loadQuotaValueCurrent() {
  if (!quotaSnapshot || quotaLoading || quotaValueScanning) return;
  const generation = ++quotaValueGeneration;
  els.quotaValuePriceMode.value = els.priceMode.value;
  els.quotaValueWindows.setAttribute("aria-busy", "true");
  els.quotaValueStatus.textContent = quotaSnapshot.status === "ready" ? "正在换算本周期额度…" : "正在读取最后保存的换算…";
  try {
    const response = await fetch(`/api/quota/value?${new URLSearchParams({ price_mode: els.priceMode.value })}`);
    if (!response.ok) throw new Error(response.status === 404 ? restartBackendMessage : "额度换算失败，请刷新重试。");
    const report = await response.json();
    if (generation !== quotaValueGeneration) return;
    renderQuotaValue(report);
  } catch (error) {
    if (generation !== quotaValueGeneration) return;
    if (quotaValueReport && quotaValueReportScope === quotaSnapshot.reset_history_scope && quotaValueReport.price_mode === els.priceMode.value) {
      renderQuotaValue({...quotaValueReport, saved: true});
      els.quotaValueStatus.textContent += ` · ${error.message}`;
    } else {
      els.quotaValueStatus.textContent = error.message;
      els.quotaValueWindows.replaceChildren();
    }
  } finally {
    if (generation === quotaValueGeneration) els.quotaValueWindows.setAttribute("aria-busy", "false");
  }
}

function closeQuotaValueHistoryDetail() {
  quotaValueDetailGeneration += 1;
  selectedQuotaValueCycle = null;
  els.quotaValueHistoryDetail.hidden = true;
  els.quotaValueHistoryDetail.setAttribute("aria-busy", "false");
  els.quotaValueObservationTable.replaceChildren();
  els.quotaValueHistoryDetailStatus.textContent = "";
}

function clearQuotaValueHistory(message, { loading = false, resetPage = false } = {}) {
  quotaValueHistoryGeneration += 1;
  quotaValueHistoryData = null;
  if (resetPage) quotaValueHistoryOffset = 0;
  closeQuotaValueHistoryDetail();
  els.quotaValueHistoryPanel.setAttribute("aria-busy", String(loading));
  els.quotaValueHistoryStatus.textContent = message;
  els.quotaValueHistoryTable.innerHTML = `<tr><td colspan="9" class="empty-state">${escapeHtml(message)}</td></tr>`;
  updateQuotaValueHistoryPager();
}

function beginQuotaValueHistoryLoad(message, resetPage = false) {
  quotaValueHistoryGeneration += 1;
  if (resetPage) quotaValueHistoryOffset = 0;
  closeQuotaValueHistoryDetail();
  els.quotaValueHistoryPanel.setAttribute("aria-busy", "true");
  els.quotaValueHistoryStatus.textContent = message;
  if (!quotaValueHistoryData) els.quotaValueHistoryTable.innerHTML = `<tr><td colspan="9" class="empty-state">${escapeHtml(message)}</td></tr>`;
  else renderQuotaValueHistoryRows();
  updateQuotaValueHistoryPager();
}

function updateQuotaValueHistoryPager() {
  const total = quotaValueHistoryData?.total || 0;
  const busy = quotaLoading || quotaValueRefreshing || els.quotaValueHistoryPanel.getAttribute("aria-busy") === "true";
  els.quotaValueHistoryPrev.disabled = busy || !total || quotaValueHistoryOffset === 0;
  els.quotaValueHistoryNext.disabled = busy || !quotaValueHistoryData?.has_more;
  els.quotaValueHistoryPage.textContent = total
    ? `第 ${Math.floor(quotaValueHistoryOffset / quotaValueHistoryPageSize) + 1} / ${Math.ceil(total / quotaValueHistoryPageSize)} 页 · ${formatNumber(total)} 个周期`
    : "暂无周期";
}

function quotaValuePercent(value) {
  return value == null ? "未知" : `${Number(value.toFixed(2))}%`;
}

function quotaValueMoney(value) {
  return value == null ? "未知" : money.format(value);
}

function quotaValueHistoryNotes(row) {
  const notes = [row.message];
  if (row.total?.unknown_price_calls) notes.push(`${formatNumber(row.total.unknown_price_calls)} 次价格未知，金额与外推仅包含已知部分。`);
  if (row.total?.unknown_tier_calls) notes.push(`${formatNumber(row.total.unknown_tier_calls)} 次档位未知，按 Standard 基础价估算。`);
  if (row.price_mode === "snapshot" && row.total?.inferred_price_calls) notes.push(`${formatNumber(row.total.inferred_price_calls)} 次使用首次采集价格回填。`);
  return notes.filter(Boolean).join(" ");
}

function renderQuotaValueHistoryRows() {
  const cycles = quotaValueHistoryData?.cycles || [];
  els.quotaValueHistoryTable.innerHTML = cycles.map(cycle => {
    const selected = cycle.id === selectedQuotaValueCycle;
    const isCurrent = quotaSnapshot?.status === "ready" && cycle.is_current;
    const plan = cycle.plan_type ? quotaPlans[cycle.plan_type] || cycle.plan_type : "套餐未知";
    const partial = cycle.total?.unknown_price_calls > 0;
    return `<tr${selected ? ' class="selected"' : ""}>
      <td><strong>${escapeHtml(quotaWindowLabel(cycle))}</strong><small>${escapeHtml(plan)} <span class="coverage${isCurrent ? "" : " partial"}">${isCurrent ? "当前周期" : "历史周期"}</span></small></td>
      <td>${escapeHtml(quotaValueTime(cycle.cycle_start_at))}<small>${cycle.cycle_start_at ? cycle.cycle_start_estimated ? "起点推测" : "起点已确认" : "起点未知"} · 当次计划重置 ${escapeHtml(quotaValueTime(cycle.resets_at))}</small></td>
      <td class="quota-value-primary">${quotaValuePercent(cycle.used_percent)}</td>
      <td class="quota-value-primary">${quotaValueMoney(cycle.total?.api_usd_known)}${partial ? '<small class="unknown">仅已知金额</small>' : ""}</td>
      <td>${escapeHtml(quotaValueTime(cycle.fetched_at))}</td>
      <td>${quotaValueMoney(cycle.usd_per_percent)}</td><td>${quotaValueMoney(cycle.full_quota_usd)}</td><td>${formatNumber(cycle.observation_count)}</td>
      <td><button class="button ghost" data-quota-value-cycle="${cycle.id}" aria-controls="quotaValueHistoryDetail" aria-expanded="${selected}">${selected ? "收起明细" : "查看读数"}</button></td>
    </tr>`;
  }).join("") || '<tr><td colspan="9" class="empty-state">暂无已保存的额度美元历史。成功读取可识别周期的额度后开始记录。</td></tr>';
}

async function loadQuotaValueHistory(resetPage = false) {
  if (!quotaSnapshot || quotaLoading || quotaValueScanning) return;
  beginQuotaValueHistoryLoad(`正在读取${quotaSnapshot.history_label || "账号"}的已保存历史…`, resetPage);
  const generation = quotaValueHistoryGeneration;
  const priceMode = els.priceMode.value;
  try {
    const query = new URLSearchParams({ price_mode: priceMode, offset: quotaValueHistoryOffset, limit: quotaValueHistoryPageSize });
    const response = await fetch(`/api/quota/value/history?${query}`);
    if (!response.ok) throw new Error(response.status === 404 ? restartBackendMessage : "读取额度美元历史失败，请刷新重试。");
    const report = await response.json();
    if (generation !== quotaValueHistoryGeneration) return;
    if (report.status !== "ready") {
      clearQuotaValueHistory(report.message || "暂无可读取的本地账号历史。");
      return;
    }
    if (!Array.isArray(report.cycles)) throw new Error(restartBackendMessage);
    quotaValueHistoryData = {...report, price_mode: priceMode};
    quotaValueHistoryOffset = report.offset;
    els.quotaValueHistoryStatus.textContent = `${quotaHistoryContext({...quotaSnapshot, ...report, status: quotaSnapshot.status})} · ${formatNumber(report.total)} 个已保存周期 · ${priceMode === "current" ? "当次当前价格换算" : "当次快照估算"} · 历史金额保持读取时的值`;
    if (quotaSnapshot.value_history_status === "error") els.quotaValueHistoryStatus.textContent += " · 本次历史保存失败，已保存的记录仍可查看。";
    renderQuotaValueHistoryRows();
  } catch (error) {
    if (generation !== quotaValueHistoryGeneration) return;
    if (quotaValueHistoryData && quotaValueHistoryData.price_mode === priceMode) {
      quotaValueHistoryOffset = quotaValueHistoryData.offset;
      els.quotaValueHistoryStatus.textContent = `${quotaHistoryContext()} · ${error.message} · 已显示记录保留上次读取时的值。`;
    } else clearQuotaValueHistory(error.message);
  } finally {
    if (generation === quotaValueHistoryGeneration) {
      els.quotaValueHistoryPanel.setAttribute("aria-busy", "false");
      updateQuotaValueHistoryPager();
    }
  }
}

async function loadQuotaValueCycle(id) {
  if (quotaLoading || quotaValueRefreshing || !quotaValueHistoryData?.cycles.some(cycle => cycle.id === id)) return;
  if (selectedQuotaValueCycle === id) {
    closeQuotaValueHistoryDetail(); renderQuotaValueHistoryRows(); return;
  }
  closeQuotaValueHistoryDetail();
  selectedQuotaValueCycle = id;
  const generation = quotaValueDetailGeneration;
  const historyGeneration = quotaValueHistoryGeneration;
  const priceMode = els.priceMode.value;
  renderQuotaValueHistoryRows();
  els.quotaValueHistoryDetail.hidden = false;
  els.quotaValueHistoryDetail.setAttribute("aria-busy", "true");
  els.quotaValueHistoryDetailTitle.textContent = "周期读数明细";
  els.quotaValueHistoryDetailStatus.textContent = "正在读取已保存的周期快照…";
  try {
    const response = await fetch(`/api/quota/value/history/${id}?${new URLSearchParams({ price_mode: priceMode })}`);
    if (generation !== quotaValueDetailGeneration || historyGeneration !== quotaValueHistoryGeneration) return;
    if (!response.ok) {
      if (response.status === 404) { clearQuotaValueHistory("该周期已不可用，请刷新额度后重试。"); return; }
      throw new Error("读取周期快照失败，请重试。");
    }
    const report = await response.json();
    if (generation !== quotaValueDetailGeneration || historyGeneration !== quotaValueHistoryGeneration) return;
    if (report.cycle?.id !== id || !Array.isArray(report.observations)) throw new Error(restartBackendMessage);
    const cycle = report.cycle;
    els.quotaValueHistoryDetailTitle.textContent = `${quotaWindowLabel(cycle)} · 周期读数明细`;
    els.quotaValueHistoryDetailStatus.textContent = `${quotaHistoryContext({...quotaSnapshot, ...report, status: quotaSnapshot.status})} · 周期起点 ${quotaValueTime(cycle.cycle_start_at)} · 当次计划重置 ${quotaValueTime(cycle.resets_at)} · ${formatNumber(report.observations.length)} 个已保存读数 · ${quotaSnapshot.status === "ready" && cycle.is_current ? "当前周期" : "历史周期，最后读数不代表重置时最终用量"}`;
    els.quotaValueObservationTable.innerHTML = report.observations.map(row => `<tr><td>${escapeHtml(quotaValueTime(row.fetched_at))}</td><td>${quotaValuePercent(row.used_percent)}</td><td>${quotaValueMoney(row.total?.api_usd_known)}</td><td>${quotaValueMoney(row.usd_per_percent)}</td><td>${quotaValueMoney(row.full_quota_usd)}</td><td>${quotaValueMoney(row.remaining_quota_usd)}</td><td class="quota-value-observation-note">${escapeHtml(quotaValueHistoryNotes(row)) || "—"}</td></tr>`).join("") || '<tr><td colspan="7" class="empty-state">此周期暂无可显示的快照。</td></tr>';
    scrollToDetail(els.quotaValueHistoryDetail);
  } catch (error) {
    if (generation !== quotaValueDetailGeneration || historyGeneration !== quotaValueHistoryGeneration) return;
    els.quotaValueHistoryDetailStatus.textContent = error.message;
    els.quotaValueObservationTable.replaceChildren();
  } finally {
    if (generation === quotaValueDetailGeneration && historyGeneration === quotaValueHistoryGeneration) els.quotaValueHistoryDetail.setAttribute("aria-busy", "false");
  }
}

function renderResetHistory(quota) {
  if (quota.reset_history_scope !== resetAccountScope) selectedReset = null;
  resetAccountScope = quota.reset_history_scope;
  const grouped = new Map();
  for (const record of quota.reset_records || []) {
    const stamp = Date.parse(record.reset_at);
    if (!Number.isFinite(stamp)) continue;
    const key = new Date(stamp).toISOString();
    const entry = grouped.get(key) || { key, stamp, labels: new Set(), estimated: false, methods: new Set() };
    entry.labels.add(quotaWindowLabel(record));
    entry.estimated ||= record.time_estimated || record.confidence === "estimated";
    entry.methods.add(record.method);
    grouped.set(key, entry);
  }
  resetRecords = Array.from(grouped.values()).sort((a, b) => b.stamp - a.stamp);
  // Refreshing may remove an estimate or switch the account; never keep an old pick.
  if (selectedReset !== todayReset.key && !resetRecords.some(record => record.key === selectedReset)) selectedReset = null;
  els.resetRecords.setAttribute("aria-busy", "false");
  if (quotaHistoryAvailable(quota)) {
    els.resetHistoryStatus.textContent = `${quotaHistoryContext(quota)} · ${resetRecords.length} 个重置时刻 · ${resetRecords.filter(record => record.estimated).length} 个包含推测时间`;
    if (quota.reset_history_status === "error") els.resetHistoryStatus.textContent += " · 本次重置记录读取或保存失败。";
  } else if (quota.reset_history_status === "error") els.resetHistoryStatus.textContent = "重置记录读取失败，请稍后刷新。";
  else els.resetHistoryStatus.textContent = quota.message || "暂无可读取的本地账号重置记录。";
  paintResetRecords();
}

function paintResetRecords() {
  // Keep a selected cutoff fixed until the user finishes choosing the range.
  if (selectedReset !== todayReset.key) todayReset.stamp = Date.now() - 2 * 60 * 1000;
  const records = [todayReset, ...resetRecords];
  const focusedKey = els.resetRecords.contains(document.activeElement) ? document.activeElement.dataset.resetKey : null;
  els.clearResetSelection.disabled = !selectedReset;
  const selected = records.find(record => record.key === selectedReset);
  els.resetSelectionStatus.textContent = selected
    ? `已选择 ${quotaTime(selected.stamp, { hour12: false })}，请再选择一个时刻`
    : "请选择第一个时刻";
  els.resetRecords.innerHTML = records.map(record => {
    const instant = new Date(record.stamp).toISOString();
    const parts = datePicker.dateTime(instant);
    const labels = Array.from(record.labels).join(" · ");
    const picked = record.key === selectedReset;
    const badge = record.today ? "统计截止" : record.estimated ? "时间推测" : "已确认";
    const description = record.today ? "当前时间前 2 分钟" : record.methods.has("early") ? "提前重置已确认，时间由新周期反推" : record.estimated ? "由下次重置时间与窗口长度反推" : "前后额度快照已确认周期变化";
    return `<button class="reset-record${picked ? " selected" : ""}" data-reset-key="${record.key}" aria-pressed="${picked}" aria-label="选择时刻，${parts.date} ${parts.clock}，${escapeHtml(labels)}，${badge}">
      <span class="reset-record-check" aria-hidden="true">${picked ? "✓" : "○"}</span>
      <span class="reset-record-time"><strong>${parts.date}</strong><time datetime="${instant}">${parts.clock}</time></span>
      <span class="reset-record-detail"><strong>${escapeHtml(labels)}</strong><small>${description}</small></span>
      <span class="reset-badge${record.estimated ? " estimated" : ""}">${badge}</span>
      <span class="reset-record-action">${picked ? "已选择" : "选择"}</span></button>`;
  }).join("") + (resetRecords.length ? "" : '<div class="empty-state">暂无重置记录。成功读取已使用的额度窗口后，会显示当前周期的推测时间。</div>');
  if (focusedKey) els.resetRecords.querySelector(`[data-reset-key="${focusedKey}"]`)?.focus();
}

els.resetRecords.addEventListener("click", event => {
  const button = event.target.closest("[data-reset-key]");
  const records = [todayReset, ...resetRecords];
  const record = records.find(item => item.key === button?.dataset.resetKey);
  if (!record) return;
  if (!selectedReset || selectedReset === record.key) {
    selectedReset = selectedReset === record.key ? null : record.key;
    paintResetRecords();
    return;
  }
  const first = records.find(item => item.key === selectedReset);
  if (!first) { selectedReset = record.key; paintResetRecords(); return; }
  const [start, end] = [first, record].sort((a, b) => a.stamp - b.stamp);
  const startAt = new Date(start.stamp).toISOString(), endAt = new Date(end.stamp).toISOString();
  const startParts = datePicker.dateTime(startAt), endParts = datePicker.dateTime(endAt);
  els.start.value = startParts.date; els.end.value = endParts.date;
  els.startTime.value = startParts.time; els.endTime.value = endParts.time;
  els.startAt.value = startAt; els.endAt.value = endAt;
  document.querySelectorAll(".preset").forEach(button => button.classList.remove("active"));
  selectedReset = null;
  invalidateUsage();
  const url = new URL("/overview", location.origin); url.search = queryString();
  history.pushState({}, "", url);
  setMenu(false); activateRoute();
  els.pageTitle.tabIndex = -1; els.pageTitle.focus();
});
els.clearResetSelection.addEventListener("click", () => { selectedReset = null; paintResetRecords(); });
els.refreshResets.addEventListener("click", () => loadQuota(true));

function renderKpis(report) {
  const total = report.total;
  const cacheRate = total.input_tokens ? total.cached_input_tokens / total.input_tokens * 100 : 0;
  els.input.textContent = formatCompact(total.input_tokens); els.input.title = formatNumber(total.input_tokens);
  els.inputDetail.textContent = `普通输入 ${formatCompact(total.uncached_input_tokens)}`;
  els.cached.textContent = formatCompact(total.cached_input_tokens); els.cached.title = formatNumber(total.cached_input_tokens);
  els.cacheRate.textContent = `占 Input ${cacheRate.toFixed(1)}%`;
  els.output.textContent = formatCompact(total.output_tokens); els.output.title = formatNumber(total.output_tokens);
  els.reasoning.textContent = `其中推理 ${formatCompact(total.reasoning_output_tokens)}`;
  els.cost.textContent = money.format(total.api_usd_known);
  els.coverage.textContent = `定价覆盖 ${total.price_coverage_percent.toFixed(1)}% 调用`;
  els.credits.textContent = formatNumber(Number(total.credits_known.toFixed(3)));
  els.fast.textContent = formatNumber(total.fast_calls); els.fast.title = `Fast tokens ${formatNumber(total.fast_tokens)}`;
  els.tierCoverage.textContent = `档位覆盖 ${total.tier_coverage_percent.toFixed(1)}%`;
}

function renderLegend(models) {
  els.legend.innerHTML = models.map(row => `<span><i style="background:${modelColor(row.key)}"></i>${escapeHtml(row.display_name || row.key)}</span>`).join("");
}

function renderStackedChart(element, rows, metric) {
  if (!rows.length) { element.innerHTML = '<div class="empty-state">这个日期范围还没有可统计的记录。</div>'; return; }
  const isCost = metric === "api_usd_known";
  const max = Math.max(...rows.map(row => isCost ? row.api_usd_known : row.total_tokens), Number.EPSILON);
  element.innerHTML = [...rows].reverse().map(row => {
    const rowTotal = isCost ? row.api_usd_known : row.total_tokens;
    const segments = row.models.map(model => {
      const value = isCost ? model.api_usd_known : model.total_tokens;
      if (!value) return "";
      const detail = isCost
        ? `${model.display_name}\n${moneyPrecise.format(value)}\n定价覆盖 ${model.price_coverage_percent.toFixed(1)}% 调用`
        : `${model.display_name}\nInput ${formatNumber(model.input_tokens)}\nCached ${formatNumber(model.cached_input_tokens)}\nOutput ${formatNumber(model.output_tokens)}\nTotal ${formatNumber(model.total_tokens)}`;
      return `<span class="segment model-segment" style="width:${value / max * 100}%;background:${modelColor(model.model || model.key)}" title="${escapeHtml(detail)}"></span>`;
    }).join("");
    const valueText = isCost ? moneyPrecise.format(rowTotal) : formatCompact(rowTotal);
    const coverage = isCost && row.unknown_price_calls
      ? `<small class="chart-warning" title="已有价格的调用数占当日调用总数">定价 ${row.price_coverage_percent.toFixed(0)}%</small>` : "";
    return `<div class="chart-row"><span class="chart-date" title="${escapeHtml(row.key)}">${escapeHtml(row.label || row.key.slice(5))}</span><div class="chart-track">${segments}</div><span class="chart-value">${valueText}${coverage}</span></div>`;
  }).join("");
  element.scrollTop = 0;
}

function synchronizeChartScrolling(first, second) {
  let activeSource = null; let releaseTimer = null;
  const claim = source => {
    activeSource = source; clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => { activeSource = null; }, 200);
  };
  const bind = (source, target) => {
    for (const eventName of ["wheel", "pointerdown", "touchstart", "keydown"]) {
      source.addEventListener(eventName, () => claim(source), { passive: true });
    }
    source.addEventListener("scroll", () => {
      if (activeSource && activeSource !== source) return;
      claim(source); if (target.scrollTop !== source.scrollTop) target.scrollTop = source.scrollTop;
    }, { passive: true });
  };
  bind(first, second); bind(second, first);
}

function renderModelTable(rows) {
  els.modelTable.innerHTML = rows.map(row => {
    const complete = row.price_coverage_percent === 100;
    return `<tr><td><i class="model-dot" style="background:${modelColor(row.key)}"></i>${escapeHtml(row.display_name || row.key)}</td>
      <td>${formatNumber(row.calls)}</td><td>${formatNumber(row.fast_calls)}</td><td>${formatNumber(row.input_tokens)}</td>
      <td>${formatNumber(row.cached_input_tokens)}</td><td>${formatNumber(row.output_tokens)}</td>
      <td class="${complete ? "" : "unknown"}">${complete ? money.format(row.api_usd_known) : `${money.format(row.api_usd_known)} + 未知`}</td>
      <td>${fastSurcharge(row)}</td><td>${row.unknown_credit_calls ? "—" : formatNumber(Number(row.credits_known.toFixed(3)))}</td>
      <td><span class="coverage ${row.tier_coverage_percent === 100 ? "" : "partial"}">${row.tier_coverage_percent.toFixed(1)}%</span></td></tr>`;
  }).join("") || '<tr><td colspan="10" class="empty-state">暂无数据</td></tr>';
}

function tableSortValue(row, field) {
  if (["key", "timestamp", "last_activity"].includes(field)) return Date.parse(row[field]);
  if (field === "service_tier") return {priority:"Fast", standard:"Standard", unknown:"未知"}[row.service_tier] || "未知";
  if (field === "price_snapshot") return row.price_snapshot ? row.price_snapshot.inferred ? "首次采集回填" : "当时已保存价格" : "无快照";
  if (field === "api_usd_known" && row.unknown_price_calls && !row.priced_calls) return null;
  if (field === "credits_known" && row.unknown_credit_calls) return null;
  if (field === "fast_surcharge_usd" && row.unknown_fast_price_calls && !row.fast_surcharge_usd) return null;
  const value = row[field];
  return value === null || value === undefined ? null : Number(value);
}

function createSortableTable(tbody, fields, render, onChange = null) {
  let rows = [], field = "api_usd_known", direction = "descending";
  const headers = [...tbody.closest("table").querySelectorAll("thead th")];
  const paintHeaders = () => {
    headers.forEach((header, index) => {
      if (!fields[index]) return;
      const active = fields[index] === field;
      header.setAttribute("aria-sort", active ? direction : "none");
      const button = header.querySelector("button");
      const next = active && direction === "ascending" ? "降序" : "升序";
      button.setAttribute("aria-label", `${button.dataset.label}：点击按${next}排序`);
      button.title = `点击按${next}排序`;
      button.querySelector(".sort-indicator").textContent = active ? direction === "ascending" ? "↑" : "↓" : "↕";
    });
  };
  const sortRows = values => [...values].sort((a, b) => {
      const left = tableSortValue(a, field), right = tableSortValue(b, field);
      const leftMissing = left === null || (typeof left === "number" && !Number.isFinite(left));
      const rightMissing = right === null || (typeof right === "number" && !Number.isFinite(right));
      // Unknown values stay after known values in either direction.
      return Number(leftMissing) - Number(rightMissing)
        || (leftMissing ? 0 : (typeof left === "string" ? left.localeCompare(right, "zh-CN") : left - right) * (direction === "ascending" ? 1 : -1));
    });
  const paint = () => { paintHeaders(); render(sortRows(rows)); };
  headers.forEach((header, index) => {
    if (!fields[index]) return;
    const label = header.textContent;
    const button = document.createElement("button");
    button.type = "button"; button.className = "table-sort"; button.dataset.label = label;
    button.append(document.createTextNode(label));
    const indicator = document.createElement("span");
    indicator.className = "sort-indicator"; indicator.setAttribute("aria-hidden", "true");
    button.append(indicator); header.replaceChildren(button);
    button.addEventListener("click", () => {
      direction = field === fields[index] && direction === "ascending" ? "descending" : "ascending";
      field = fields[index]; paintHeaders();
      if (onChange) onChange(field, direction); else paint();
    });
  });
  paintHeaders();
  return {
    setRows(value) { rows = value; paint(); }, sortRows,
    getSort() { return {sort_by: field, sort_direction: direction}; },
    setSort(value, order = "descending") { field = value; direction = order; paint(); },
  };
}

function dailyRows(rows, project = false) {
  const colspan = project ? 8 : 11;
  return (project ? [...rows].reverse() : rows).map(original => {
    const row = {...original, key: original.label || original.key};
    return project
    ? `<tr><td>${escapeHtml(row.key)}</td><td>${formatNumber(row.calls)}</td><td>${formatNumber(row.input_tokens)}</td><td>${formatNumber(row.cached_input_tokens)}</td><td>${formatNumber(row.output_tokens)}</td><td>${formatNumber(row.total_tokens)}</td><td>${money.format(row.api_usd_known)}${row.unknown_price_calls ? " + 未知" : ""}</td><td><span class="coverage ${row.price_coverage_percent === 100 ? "" : "partial"}">${row.price_coverage_percent.toFixed(1)}%</span></td></tr>`
    : `<tr><td>${escapeHtml(row.key)}</td><td>${formatNumber(row.calls)}</td><td>${formatNumber(row.fast_calls)}</td><td>${formatNumber(row.input_tokens)}</td><td>${formatNumber(row.uncached_input_tokens)}</td><td>${formatNumber(row.cached_input_tokens)}</td><td>${formatNumber(row.output_tokens)}</td><td>${formatNumber(row.total_tokens)}</td><td>${money.format(row.api_usd_known)}${row.unknown_price_calls ? " + 未知" : ""}</td><td>${fastSurcharge(row)}</td><td><span class="coverage ${row.tier_coverage_percent === 100 ? "" : "partial"}">${row.tier_coverage_percent.toFixed(1)}%</span></td></tr>`
  }).join("") || `<tr><td colspan="${colspan}" class="empty-state">暂无数据</td></tr>`;
}

async function loadReport(force = false) {
  const key = queryString();
  if (!force && state.report && state.reportKey === key) return state.report;
  setStatus("正在汇总本地 token 记录…");
  const response = await fetch(`/api/summary?${key}`);
  if (!response.ok) throw new Error((await response.json()).detail || "读取失败");
  const report = await response.json();
  if (queryString() !== key) return report;
  els.dailyTable.innerHTML = "";
  renderTrend(report, els.tokenChart, els.costChart, "#tokenTrendTitle", "#costTrendTitle");
  state.report = report; state.reportKey = key;
  renderKpis(report); renderLegend(report.models);
  usageTables.models.setRows(report.models); usageTables.daily.setRows(trendRows(report));
  document.querySelector('[data-page="daily"] h2').textContent = els.grain.value === "hourly" ? "每小时明细" : "每日明细";
  renderPriceNotice(report.total.inferred_price_calls);
  els.export.href = `/api/export.csv?${key}`; setStatus("");
  return report;
}

function renderProjectChart(projects) {
  for (const [chart, metric] of [[els.projectChart, "total_tokens"], [els.projectTotalCostChart, "api_usd_known"]]) {
    if (!projects.length) {
      chart.innerHTML = '<div class="empty-state">这个日期范围还没有项目数据。</div>';
      chart.scrollTop = 0; continue;
    }
    const isCost = metric === "api_usd_known";
    const max = Math.max(...projects.map(project => project[metric]), Number.EPSILON);
    chart.innerHTML = projects.map(project => {
      const segments = project.models.map(model => {
        if (!model[metric]) return "";
        const detail = isCost ? `${model.display_name}\n${moneyPrecise.format(model.api_usd_known)}\n定价覆盖 ${model.price_coverage_percent.toFixed(1)}% 调用`
          : `${model.display_name}\n${formatNumber(model.total_tokens)} tokens`;
        return `<span class="segment model-segment" style="width:${model[metric] / max * 100}%;background:${modelColor(model.model || model.key)}" title="${escapeHtml(detail)}"></span>`;
      }).join("");
      const value = isCost ? project.unknown_price_calls && !project.priced_calls ? "未知" : moneyPrecise.format(project.api_usd_known)
        : formatCompact(project.total_tokens);
      const coverage = isCost && project.unknown_price_calls ? `<small class="chart-warning">定价 ${project.price_coverage_percent.toFixed(0)}%</small>` : "";
      return `<div class="chart-row" role="button" tabindex="0" aria-controls="projectDetail" data-project-key="${escapeHtml(project.key)}" title="${escapeHtml(project.path || "无法识别项目路径")}"><span class="project-label">${escapeHtml(project.display_name)}</span><div class="chart-track">${segments}</div><span class="chart-value">${value}${coverage}</span></div>`;
    }).join("");
    chart.scrollTop = 0;
  }
  paintProjectSelection();
}

function renderProjectTable(projects) {
  els.projectTable.innerHTML = projects.map(project => `<tr data-project-key="${escapeHtml(project.key)}"><td class="project-name"><strong>${escapeHtml(project.display_name)}</strong><small title="${escapeHtml(project.path || "")}">${escapeHtml(project.path || "无法识别项目路径")}</small></td><td>${formatNumber(project.calls)}</td><td>${formatNumber(project.fast_calls)}</td><td>${formatNumber(project.input_tokens)}</td><td>${formatNumber(project.cached_input_tokens)}</td><td>${formatNumber(project.output_tokens)}</td><td>${formatNumber(project.total_tokens)}</td><td>${money.format(project.api_usd_known)}${project.unknown_price_calls ? " + 未知" : ""}</td><td>${fastSurcharge(project)}</td><td><span class="coverage ${project.price_coverage_percent === 100 ? "" : "partial"}">${project.price_coverage_percent.toFixed(1)}%</span></td></tr>`).join("") || '<tr><td colspan="10" class="empty-state">暂无项目数据</td></tr>';
  paintProjectSelection();
}

function paintProjectSelection() {
  for (const container of [els.projectChart, els.projectTotalCostChart, els.projectTable]) {
    container.querySelectorAll("[data-project-key]").forEach(row => {
      const selected = row.dataset.projectKey === els.projectSelect.value;
      row.classList.toggle("selected", selected);
      if (row.getAttribute("role") === "button") row.setAttribute("aria-pressed", String(selected));
    });
  }
}

function scrollToDetail(element) {
  element.focus({preventScroll: true});
  element.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
}

function selectProject(projectKey) {
  if (els.projectSelect.value === projectKey) {
    scrollToDetail($("#projectDetail"));
    return;
  }
  els.projectSelect.value = projectKey;
  paintProjectSelection();
  loadProjectDaily(projectKey).catch(error => setStatus(error.message, "error"));
}

async function loadProjectDaily(projectKey) {
  if (!projectKey) {
    els.projectTitle.textContent = "项目每日用量"; els.projectPath.textContent = "";
    els.projectTokenChart.innerHTML = els.projectCostChart.innerHTML = '<div class="empty-state">请先选择项目</div>';
    els.projectDailyTable.innerHTML = '<tr><td colspan="8" class="empty-state">暂无数据</td></tr>'; return;
  }
  const key = queryString({ project: projectKey });
  const response = await fetch(`/api/projects/daily?${key}`);
  if (!response.ok) throw new Error((await response.json()).detail || "读取项目日报失败");
  const report = await response.json();
  if (queryString({ project: els.projectSelect.value }) !== key) return;
  els.projectTitle.textContent = `${report.project.display_name} · 用量趋势`;
  els.projectPath.textContent = report.project.path || "无法识别项目路径";
  renderTrend(report, els.projectTokenChart, els.projectCostChart, "#projectTokenTitle", "#projectCostTitle");
  els.projectDailyTable.innerHTML = dailyRows(trendRows(report), true);
}

async function loadProjects(force = false) {
  const key = queryString();
  if (!force && state.projects && state.projectsKey === key) return state.projects;
  setStatus("正在按项目汇总本地 token 记录…");
  const response = await fetch(`/api/projects?${key}`);
  if (!response.ok) throw new Error((await response.json()).detail || "读取项目统计失败");
  const result = await response.json();
  if (queryString() !== key) return result;
  validatePriceMode(result);
  state.projects = result; state.projectsKey = key;
  renderPriceNotice(result.projects.reduce((sum, row) => sum + row.inferred_price_calls, 0));
  renderProjectChart(result.projects); usageTables.projects.setRows(result.projects);
  const previous = els.projectSelect.value;
  els.projectSelect.innerHTML = result.projects.map(project => `<option value="${escapeHtml(project.key)}">${escapeHtml(project.display_name)} — ${formatCompact(project.total_tokens)}</option>`).join("");
  if (result.projects.some(project => project.key === previous)) els.projectSelect.value = previous;
  paintProjectSelection();
  await loadProjectDaily(els.projectSelect.value);
  if (queryString() !== key) return result;
  setStatus(`已汇总 ${result.projects.length} 个项目；点击项目柱或使用选择器查看每日用量。`);
  return result;
}

function restoreAnalysis(params) {
  els.priceMode.value = params.get("price_mode") === "current" ? "current" : "snapshot";
  els.grain.value = params.get("grain") === "hourly" ? "hourly" : "daily";
  selectedSession = params.get("session") || null;
  selectedSessionScope = params.get("session_scope") === "self" ? "self" : "tree";
  renderPriceNotice();
}

function sessionList() {
  const search = els.sessionSearch.value.trim().toLocaleLowerCase();
  const rows = (sessionData?.sessions || []).filter(row =>
    [row, ...(row.members || [])].some(member =>
      [member.title, member.key, ...member.projects, ...member.models].join(" ").toLocaleLowerCase().includes(search)));
  return usageTables.sessions.sortRows(rows);
}

function sessionTableRow(row, { member = false, group = null } = {}) {
  const scope = member ? "self" : "tree";
  const selected = selectedSession === row.key && selectedSessionScope === scope;
  const ownParent = member && row.key === group.key;
  const title = ownParent ? `${row.title}（本身）` : row.title;
  const expanded = expandedSessions.has(row.key);
  const toggle = !member && row.has_children
    ? `<button type="button" class="session-expand" data-session-expand="${escapeHtml(row.key)}" aria-expanded="${expanded}" aria-label="${expanded ? "收起" : "展开"}${escapeHtml(row.title)}的会话用量"><span aria-hidden="true">${expanded ? "⌄" : "&gt;"}</span></button>`
    : '<span class="session-expand-spacer" aria-hidden="true"></span>';
  const description = [row.projects.join(" · ")];
  if (member) description.push(ownParent ? "父会话自身用量" : "子会话自身用量");
  else if (row.has_children) description.push(`含自身及 ${formatNumber(row.members.length - 1)} 个子会话`);
  if (row.parent_unknown) description.push("子代理 · 归属未知");
  const depth = member ? Math.max(1, Math.min(8, Number(row.depth) || 0)) : 0;
  return `<tr class="${member ? "session-member" : "session-parent"}${selected ? " selected" : ""}"><td><div class="session-name" style="--session-depth:${depth}">${toggle}<div><button type="button" class="session-pick" data-session="${escapeHtml(row.key)}" data-session-scope="${scope}" aria-pressed="${selected}">${escapeHtml(title)}</button><small>${escapeHtml(description.filter(Boolean).join(" · "))}</small></div></div></td>
    <td>${escapeHtml(row.models.join(" · ")) || "—"}</td><td>${row.last_activity ? escapeHtml(quotaTime(row.last_activity, {hour12:false})) : "—"}</td><td>${formatNumber(row.calls)}</td><td>${formatNumber(row.total_tokens)}</td><td>${formatNumber(row.fast_calls)}</td><td>${money.format(row.api_usd_known)}${row.unknown_price_calls ? " + 未知" : ""}</td><td>${fastSurcharge(row)}</td></tr>`;
}

function paintSessionList() {
  const focused = els.sessionTable.contains(document.activeElement) ? {...document.activeElement.dataset} : null;
  const rows = sessionList();
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  sessionPage = Math.min(sessionPage, pages - 1);
  $("#sessionCount").textContent = `${formatNumber(rows.length)} 个会话 · 父会话汇总自身及所有子会话 · 用量均在当前筛选区间内`;
  els.sessionTable.innerHTML = rows.slice(sessionPage * pageSize, (sessionPage + 1) * pageSize).map(row =>
    sessionTableRow(row) + (row.has_children && expandedSessions.has(row.key)
      ? row.members.map(member => sessionTableRow(member, {member:true, group:row})).join("") : "")
  ).join("") || '<tr><td colspan="8" class="empty-state">当前范围没有匹配的会话。</td></tr>';
  $("#sessionPage").textContent = `${sessionPage + 1} / ${pages}`;
  $("#sessionPrev").disabled = sessionPage === 0; $("#sessionNext").disabled = sessionPage >= pages - 1;
  if (focused) Array.from(els.sessionTable.querySelectorAll("button")).find(button =>
    focused.sessionExpand ? button.dataset.sessionExpand === focused.sessionExpand
      : button.dataset.session === focused.session && button.dataset.sessionScope === focused.sessionScope)?.focus();
}

function clearSessionDetail(message = "当前范围没有会话。") {
  $("#sessionDetailTitle").textContent = "会话明细";
  $("#sessionDetailSummary").textContent = message;
  $("#sessionTokenChart").innerHTML = $("#sessionCostChart").innerHTML = '<div class="empty-state">暂无数据</div>';
  els.requestTable.innerHTML = '<tr><td colspan="9" class="empty-state">暂无调用</td></tr>';
  $("#requestPage").textContent = "0 / 0"; $("#requestPrev").disabled = $("#requestNext").disabled = true;
  clearSessionQuota();
}

function clearSessionQuota() {
  sessionQuotaGeneration += 1;
  sessionQuotaData = null;
  els.sessionQuotaPanel.setAttribute("aria-busy", "false");
  els.sessionQuotaStatus.textContent = "选择一个会话查看保存的账号额度读数。";
  els.sessionQuotaTable.innerHTML = '<tr><td colspan="5" class="empty-state">暂无读数</td></tr>';
  els.sessionQuotaPage.textContent = "暂无读数";
  els.sessionQuotaPrev.disabled = els.sessionQuotaNext.disabled = true;
}

async function loadSessionQuota() {
  if (!selectedSession) return;
  const session = selectedSession, scope = selectedSessionScope;
  const selection = `${session}:${scope}`;
  if (sessionQuotaSelection !== selection) sessionQuotaOffset = 0;
  sessionQuotaSelection = selection;
  const generation = ++sessionQuotaGeneration;
  els.sessionQuotaPanel.setAttribute("aria-busy", "true");
  els.sessionQuotaPrev.disabled = els.sessionQuotaNext.disabled = true;
  els.sessionQuotaStatus.textContent = "正在读取此会话日志保存的账号额度读数…";
  try {
    const params = new URLSearchParams({offset: sessionQuotaOffset, limit: pageSize, include_children: String(scope === "tree")});
    const response = await fetch(`/api/sessions/${encodeURIComponent(session)}/quota?${params}`);
    if (!response.ok) throw new Error(response.status === 404 ? restartBackendMessage : "读取会话额度读数失败，请重试。");
    const report = await response.json();
    if (generation !== sessionQuotaGeneration || selectedSession !== session || selectedSessionScope !== scope) return;
    if (!Array.isArray(report.samples)) throw new Error(restartBackendMessage);
    sessionQuotaData = report;
    sessionQuotaOffset = report.offset;
    els.sessionQuotaStatus.textContent = `${formatNumber(report.total)} 个已保存的账号额度读数${scope === "tree" ? " · 包含子会话日志" : " · 此会话自身日志"} · 源日志清空后仍保留`;
    els.sessionQuotaTable.innerHTML = report.samples.map(sample => `<tr><td>${escapeHtml(quotaValueTime(sample.timestamp_utc))}</td><td>${escapeHtml(quotaWindowLabel(sample))}</td><td>${quotaValuePercent(sample.used_percent)}</td><td>${escapeHtml(quotaValueTime(sample.resets_at))}</td><td title="${escapeHtml(sample.session_id)}">${escapeHtml(sample.session_id)}</td></tr>`).join("") || '<tr><td colspan="5" class="empty-state">此会话日志尚未采集到账号额度读数；已保存的 Token 和 API 等价金额仍可查看。</td></tr>';
    els.sessionQuotaPage.textContent = report.total ? `${report.offset + 1}–${Math.min(report.offset + report.samples.length, report.total)} / ${formatNumber(report.total)}` : "暂无读数";
  } catch (error) {
    if (generation !== sessionQuotaGeneration || selectedSession !== session || selectedSessionScope !== scope) return;
    els.sessionQuotaStatus.textContent = error.message;
    if (!sessionQuotaData) els.sessionQuotaTable.innerHTML = `<tr><td colspan="5" class="empty-state">${escapeHtml(error.message)}</td></tr>`;
    else sessionQuotaOffset = sessionQuotaData.offset;
  } finally {
    if (generation === sessionQuotaGeneration) {
      els.sessionQuotaPanel.setAttribute("aria-busy", "false");
      els.sessionQuotaPrev.disabled = !sessionQuotaData || sessionQuotaOffset === 0;
      els.sessionQuotaNext.disabled = !sessionQuotaData?.has_more;
    }
  }
}

async function loadSessions() {
  const key = queryString();
  setStatus("正在汇总会话用量…");
  const response = await fetch(`/api/sessions?${key}`);
  if (!response.ok) throw new Error("读取会话排行失败");
  const data = await response.json();
  if (queryString() !== key) return;
  validatePriceMode(data);
  if (data.sessions.some(row => !Array.isArray(row.members))) throw new Error("会话树需要更新后的后端，请重启服务后刷新页面。");
  sessionData = data;
  let selectedGroup = data.sessions.find(row => selectedSessionScope === "tree"
    ? row.key === selectedSession : row.members.some(member => member.key === selectedSession));
  if (!selectedGroup && selectedSessionScope === "tree") {
    selectedGroup = data.sessions.find(row => row.members.some(member => member.key === selectedSession));
    if (selectedGroup) selectedSessionScope = "self";
  }
  if (!selectedGroup) { selectedSession = data.sessions[0]?.key || null; selectedSessionScope = "tree"; }
  else if (selectedSessionScope === "self" && selectedGroup.has_children) expandedSessions.add(selectedGroup.key);
  syncRangeToUrl();
  for (const expanded of expandedSessions) if (!data.sessions.some(row => row.key === expanded)) expandedSessions.delete(expanded);
  renderPriceNotice(data.inferred_price_calls); paintSessionList();
  setStatus(`已汇总 ${data.sessions.length} 个会话；点击 > 展开自身与子会话，点击标题查看明细。`);
  if (selectedSession) await loadSessionDetail(); else clearSessionDetail();
}

async function loadSessionDetail() {
  const session = selectedSession;
  const scope = selectedSessionScope;
  const requestQuery = () => queryString({session, scope, offset:requestOffset, limit:pageSize, ...usageTables.requests.getSort()});
  const key = requestQuery();
  $("#sessionDetail").setAttribute("aria-busy", "true");
  clearSessionDetail("正在读取会话调用…");
  try {
    const response = await fetch(`/api/sessions/detail?${key}`);
    if (!response.ok) throw new Error((await response.json()).detail || "读取会话明细失败");
    const report = await response.json();
    if (selectedSession !== session || selectedSessionScope !== scope || requestQuery() !== key) return;
    $("#sessionDetailTitle").textContent = `${report.session.title} · ${scope === "tree" && report.session.has_children ? "会话合计" : "自身用量"}`;
    const total = report.total;
    $("#sessionDetailSummary").textContent = `${formatNumber(total.calls)} 次调用 · ${formatNumber(total.total_tokens)} Token · API 等价 ${money.format(total.api_usd_known)}${total.unknown_price_calls ? " + 未知" : ""} · Fast API 加价 ${fastSurcharge(total)} · 价格覆盖 ${total.price_coverage_percent}% · 档位覆盖 ${total.tier_coverage_percent}%`;
    renderTrend(report, $("#sessionTokenChart"), $("#sessionCostChart"), "#sessionTokenTitle", "#sessionCostTitle");
    els.requestTable.innerHTML = `<tr class="request-total"><td>总计</td><td>—</td><td>—</td><td>${formatNumber(total.input_tokens)}</td><td>${formatNumber(total.cached_input_tokens)}</td><td>${formatNumber(total.output_tokens)}</td><td>${moneyPrecise.format(total.api_usd_known)}${total.unknown_price_calls ? " + 未知" : ""}</td><td>${fastSurcharge(total, true)}</td><td>—</td></tr>` + report.requests.map(row => {
      const snapshot = row.price_snapshot;
      const provenance = snapshot ? snapshot.inferred ? "首次采集回填" : "当时已保存价格" : "无快照";
      const detail = snapshot ? `${{override:"手工覆盖",bundled:"内置价格",openai_docs:"官方文档缓存",models_dev:"models.dev 缓存"}[snapshot.source] || "保存的价格"}；价格日期 ${snapshot.price_date}；观察于 ${quotaTime(snapshot.observed_at, {hour12:false})}` : "";
      return `<tr><td>${escapeHtml(quotaTime(row.timestamp, {hour12:false}))}</td><td>${escapeHtml(row.model)}</td><td>${{priority:"Fast",standard:"Standard",unknown:"未知"}[row.service_tier] || "未知"}</td><td>${formatNumber(row.input_tokens)}</td><td>${formatNumber(row.cached_input_tokens)}</td><td>${formatNumber(row.output_tokens)}</td><td>${row.unknown_price_calls ? "未知" : moneyPrecise.format(row.api_usd_known)}</td><td>${fastSurcharge(row, true)}</td><td><span title="${escapeHtml(detail)}" class="coverage${snapshot?.inferred ? " partial" : ""}">${provenance}</span></td></tr>`;
    }).join("");
    $("#requestPage").textContent = report.request_count ? `${requestOffset + 1}–${Math.min(requestOffset + pageSize, report.request_count)} / ${formatNumber(report.request_count)}` : "0 / 0";
    $("#requestPrev").disabled = requestOffset === 0;
    $("#requestNext").disabled = requestOffset + pageSize >= report.request_count;
    await loadSessionQuota();
  } catch (error) {
    if (selectedSession === session && selectedSessionScope === scope && requestQuery() === key) { clearSessionDetail(error.message); setStatus(error.message, "error"); }
  } finally {
    if (selectedSession === session && selectedSessionScope === scope && requestQuery() === key) $("#sessionDetail").setAttribute("aria-busy", "false");
  }
}

els.priceMode.addEventListener("change", () => { renderPriceNotice(); applyFilters({closePicker:false}); });
els.grain.addEventListener("change", () => { renderPriceNotice(); applyFilters({closePicker:false}); });
els.analysisControls.addEventListener("click", event => {
  const button = event.target.closest("[data-grain]");
  if (!button || button.dataset.grain === els.grain.value) return;
  els.grain.value = button.dataset.grain;
  els.grain.dispatchEvent(new Event("change"));
});
els.sessionSearch.addEventListener("input", () => { sessionPage = 0; paintSessionList(); });
els.sessionSort.addEventListener("input", () => {
  sessionPage = 0;
  usageTables.sessions.setSort({cost:"api_usd_known", tokens:"total_tokens", fast:"fast_surcharge_usd"}[els.sessionSort.value]);
});
$("#sessionPrev").addEventListener("click", () => { sessionPage--; paintSessionList(); });
$("#sessionNext").addEventListener("click", () => { sessionPage++; paintSessionList(); });
els.sessionTable.addEventListener("click", event => {
  const toggle = event.target.closest("[data-session-expand]");
  if (toggle) {
    const key = toggle.dataset.sessionExpand;
    if (expandedSessions.has(key)) expandedSessions.delete(key); else expandedSessions.add(key);
    paintSessionList(); return;
  }
  const button = event.target.closest("[data-session]"); if (!button) return;
  const scope = button.dataset.sessionScope || "tree";
  if (selectedSession === button.dataset.session && selectedSessionScope === scope) {
    scrollToDetail($("#sessionDetail"));
    return;
  }
  selectedSession = button.dataset.session; selectedSessionScope = scope; requestOffset = 0;
  syncRangeToUrl();
  paintSessionList(); loadSessionDetail();
});
$("#requestPrev").addEventListener("click", () => { requestOffset = Math.max(0, requestOffset - pageSize); loadSessionDetail(); });
$("#requestNext").addEventListener("click", () => { requestOffset += pageSize; loadSessionDetail(); });
els.sessionQuotaPrev.addEventListener("click", () => {
  if (els.sessionQuotaPrev.disabled) return;
  sessionQuotaOffset = Math.max(0, sessionQuotaOffset - pageSize); loadSessionQuota();
});
els.sessionQuotaNext.addEventListener("click", () => {
  if (els.sessionQuotaNext.disabled) return;
  sessionQuotaOffset += pageSize; loadSessionQuota();
});

function priceValue(value) { return value === null || value === undefined ? "" : String(value); }
function renderPricing(data) {
  els.pricingAsOf.textContent = data.as_of || "—";
  els.pricingFetchedAt.textContent = data.fetched_at ? new Date(data.fetched_at).toLocaleString("zh-CN") : "内置价格";
  els.pricingStatus.textContent = data.refresh_error ? `最近刷新部分失败：${data.refresh_error}` : data.source === "models_dev" ? "正在使用 models.dev 价格缓存；Fast 倍率单独维护。" : data.source === "openai_docs" ? "正在使用旧的官方文档缓存；刷新可切换至 models.dev。" : "正在使用应用内置价格；可手工刷新价格。";
  els.pricingStatus.className = data.refresh_error ? "fine-print error-text" : "fine-print";
  els.pricingTable.innerHTML = data.models.map(item => {
    const rates = item.effective || {}; const overridden = Boolean(item.override);
    return `<tr data-model="${escapeHtml(item.model)}"><td><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.model)}</small></td>
      <td><input data-price-field="input" type="number" min="0" step="any" value="${escapeHtml(priceValue(rates.input))}"></td>
      <td><input data-price-field="cached_input" type="number" min="0" step="any" value="${escapeHtml(priceValue(rates.cached_input))}"></td>
      <td><input data-price-field="cache_write" type="number" min="0" step="any" value="${escapeHtml(priceValue(rates.cache_write))}" placeholder="未知"></td>
      <td><input data-price-field="output" type="number" min="0" step="any" value="${escapeHtml(priceValue(rates.output))}"></td>
      <td><input data-price-field="api_fast_multiplier" type="number" min="0" step="any" value="${escapeHtml(priceValue(rates.api_fast_multiplier))}" placeholder="未知"></td>
      <td><span class="coverage ${overridden ? "partial" : ""}">${overridden ? "手工覆盖" : item.official ? item.source === "models_dev" ? "models.dev" : "缓存 / 内置" : "未定价"}</span></td>
      <td class="price-actions"><button class="button save-price">保存</button><button class="button ghost reset-price" ${overridden ? "" : "disabled"}>恢复</button></td></tr>`;
  }).join("") || '<tr><td colspan="8" class="empty-state">暂无模型</td></tr>';
}

async function loadPricing(force = false) {
  if (state.pricingLoaded && !force) return;
  const response = await fetch("/api/pricing");
  if (!response.ok) throw new Error((await response.json()).detail || "读取价格失败");
  renderPricing(await response.json()); state.pricingLoaded = true; setStatus("本地价格目录已加载。");
}

async function updatePrice(row) {
  const model = row.dataset.model; const values = {};
  row.querySelectorAll("[data-price-field]").forEach(input => { values[input.dataset.priceField] = input.value === "" ? null : Number(input.value); });
  for (const field of ["input", "cached_input", "output"]) {
    if (values[field] === null || !Number.isFinite(values[field]) || values[field] < 0) throw new Error(`${model} 的 ${field} 必须是非负数`);
  }
  if (values.api_fast_multiplier !== null && (!Number.isFinite(values.api_fast_multiplier) || values.api_fast_multiplier < 0)) throw new Error(`${model} 的 Fast 倍率必须留空或为非负数`);
  if (values.cache_write !== null && (!Number.isFinite(values.cache_write) || values.cache_write < 0)) throw new Error(`${model} 的 cache_write 必须留空或为非负数`);
  const response = await fetch(`/api/pricing/models/${encodeURIComponent(model)}/override`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) });
  if (!response.ok) throw new Error((await response.json()).detail || "保存价格失败");
}

function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function presetRange(days) {
  const today = datePicker.today();
  if (days === "1") return { start: today, end: today };
  const end = body.dataset.maximumDate < today ? body.dataset.maximumDate : today;
  if (days === "all") return { start: body.dataset.minimumDate, end };
  const start = new Date(`${end}T12:00:00`);
  start.setDate(start.getDate() - Number(days) + 1);
  return { start: isoDate(start), end };
}
function syncPresets() {
  const fullDays = els.startTime.value === "00:00" && els.endTime.value === "23:59"
    && !els.startAt.value && !els.endAt.value;
  let matched = false;
  document.querySelectorAll(".preset").forEach(button => {
    const range = presetRange(button.dataset.days);
    const selected = !matched && fullDays && els.start.value === range.start && els.end.value === range.end;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
    matched ||= selected;
  });
}
function syncRangeToUrl() {
  const url = new URL(location.href); url.search = queryString(); history.replaceState({}, "", url);
}
async function applyFilters({ closePicker = true } = {}) {
  datePicker.sync();
  syncPresets();
  if (closePicker) datePicker.close();
  syncRangeToUrl(); invalidateUsage();
  try { await loadCurrentPage(); } catch (error) { setStatus(error.message, "error"); }
}

function setMenu(open) {
  body.classList.toggle("menu-open", open); els.menuToggle.setAttribute("aria-expanded", String(open));
  els.menuToggle.setAttribute("aria-label", open ? "关闭导航" : "打开导航"); els.sidebarBackdrop.hidden = !open;
}
async function loadCurrentPage(force = false) {
  const page = currentRoute()[0];
  if (page === "pricing") return loadPricing(force);
  if (page === "projects") return loadProjects(force);
  if (page === "resets") return;
  if (page === "quota-value") return loadQuotaValue();
  if (page === "sessions") return loadSessions();
  return loadReport(force);
}
function activateRoute() {
  if (datePicker.sync()) syncRangeToUrl();
  syncPresets();
  datePicker.close();
  const [page, title, eyebrow, subtitle] = currentRoute();
  if (page === "resets") paintResetRecords();
  document.querySelectorAll(".page").forEach(section => { section.hidden = section.dataset.page !== page; });
  document.querySelectorAll("[data-route]").forEach(link => {
    if (link.dataset.route === page) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  els.dateControls.hidden = page === "pricing" || page === "resets" || page === "quota-value";
  els.analysisControls.hidden = page === "pricing" || page === "resets" || page === "quota-value";
  setStatus(""); els.scan.hidden = page === "resets";
  els.pageTitle.textContent = title;
  els.pageEyebrow.textContent = eyebrow; els.pageSubtitle.textContent = subtitle;
  document.title = `${title} · Codex Token Report`;
  loadCurrentPage().catch(error => setStatus(error.message, "error"));
}

els.refreshQuota.addEventListener("click", () => loadQuota(true));
els.quotaValuePriceMode.addEventListener("change", () => {
  els.priceMode.value = els.quotaValuePriceMode.value;
  renderPriceNotice();
  applyFilters();
});
els.quotaValueHistoryTable.addEventListener("click", event => {
  const button = event.target.closest("[data-quota-value-cycle]");
  if (!button) return;
  const id = Number(button.dataset.quotaValueCycle);
  if (Number.isInteger(id) && id > 0) loadQuotaValueCycle(id);
});
els.quotaValueHistoryPrev.addEventListener("click", () => {
  if (els.quotaValueHistoryPrev.disabled) return;
  quotaValueHistoryOffset = Math.max(0, quotaValueHistoryOffset - quotaValueHistoryPageSize);
  loadQuotaValueHistory();
});
els.quotaValueHistoryNext.addEventListener("click", () => {
  if (els.quotaValueHistoryNext.disabled) return;
  quotaValueHistoryOffset += quotaValueHistoryPageSize;
  loadQuotaValueHistory();
});
els.closeQuotaValueHistoryDetail.addEventListener("click", () => {
  const id = selectedQuotaValueCycle;
  closeQuotaValueHistoryDetail(); renderQuotaValueHistoryRows();
  els.quotaValueHistoryTable.querySelector(`[data-quota-value-cycle="${id}"]`)?.focus();
});
els.refreshQuotaValue.addEventListener("click", async () => {
  if (quotaLoading || quotaValueRefreshing) return;
  quotaValueRefreshing = true; updateQuotaValueButton();
  quotaValueScanning = true;
  quotaValueGeneration += 1;
  els.quotaValueWindows.setAttribute("aria-busy", "true");
  beginQuotaValueHistoryLoad("正在扫描新日志并刷新额度；已保存历史仍可查看…", true);
  els.refreshQuota.disabled = true; els.refreshResets.disabled = true; els.scan.disabled = true;
  els.quotaValueStatus.textContent = "正在扫描新日志并刷新额度…";
  try {
    const response = await fetch("/api/scan", { method: "POST" });
    if (!response.ok) throw new Error("扫描失败，请重试后再换算额度。");
    invalidateUsage();
    quotaValueScanning = false;
    await loadQuota(true);
  } catch (error) {
    quotaValueGeneration += 1;
    els.quotaValueWindows.setAttribute("aria-busy", "false");
    if (quotaValueReport && quotaValueReport.price_mode === els.priceMode.value) {
      renderQuotaValue({...quotaValueReport, saved: true});
      els.quotaValueStatus.textContent += ` · ${error.message}`;
    } else {
      els.quotaValueWindows.replaceChildren();
      els.quotaValueStatus.textContent = error.message;
    }
    if (quotaValueHistoryData) {
      quotaValueHistoryOffset = quotaValueHistoryData.offset;
      els.quotaValueHistoryStatus.textContent = `${error.message} · 已保存历史仍可查看。`;
      els.quotaValueHistoryPanel.setAttribute("aria-busy", "false");
    } else clearQuotaValueHistory(error.message, { resetPage: true });
  } finally {
    quotaValueScanning = false; quotaValueRefreshing = false; updateQuotaValueButton();
    els.refreshQuota.disabled = quotaLoading; els.refreshResets.disabled = quotaLoading; els.scan.disabled = false;
  }
});
els.quotaStatus.addEventListener("click", event => {
  const trigger = event.target.closest(".quota-reset-trigger");
  if (!trigger) return;
  els.quotaResetPopover.showModal();
  trigger.setAttribute("aria-expanded", "true");
});
els.quotaResetPopover.addEventListener("click", event => {
  if (event.target.closest(".quota-reset-close")) els.quotaResetPopover.close();
  else if (event.target === els.quotaResetPopover) {
    const rect = els.quotaResetPopover.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) els.quotaResetPopover.close();
  }
});
els.quotaResetPopover.addEventListener("close", () => {
  els.quotaStatus.querySelector(".quota-reset-trigger")?.setAttribute("aria-expanded", "false");
});
setInterval(updateResetCreditWarning, 60 * 1000);

els.pricingTable.addEventListener("click", async event => {
  const button = event.target.closest("button"); const row = button?.closest("tr[data-model]"); if (!button || !row) return;
  button.disabled = true;
  try {
    if (button.classList.contains("save-price")) await updatePrice(row);
    else if (button.classList.contains("reset-price")) {
      const response = await fetch(`/api/pricing/models/${encodeURIComponent(row.dataset.model)}/override`, { method: "DELETE" });
      if (!response.ok) throw new Error("恢复缓存价格失败");
    } else return;
    invalidateUsage(); state.pricingLoaded = false; await loadPricing(true);
  } catch (error) { els.pricingStatus.textContent = error.message; els.pricingStatus.className = "fine-print error-text"; }
  finally { button.disabled = false; }
});
els.refreshPricing.addEventListener("click", async () => {
  els.refreshPricing.disabled = true; els.refreshPricing.textContent = "刷新中…";
  els.pricingStatus.textContent = "正在从 models.dev 获取 OpenAI 模型价格…";
  try {
    const response = await fetch("/api/pricing/refresh", { method: "POST" });
    if (!response.ok) throw new Error((await response.json()).detail || "刷新价格失败");
    const result = await response.json(); const failures = Object.keys(result.failed_models).length;
    invalidateUsage(); state.pricingLoaded = false; await loadPricing(true);
    els.pricingStatus.textContent = `已更新 ${result.updated_models.length} 个模型${failures ? `，${failures} 个失败并保留旧缓存` : ""}。`;
  } catch (error) { els.pricingStatus.textContent = error.message; els.pricingStatus.className = "fine-print error-text"; }
  finally { els.refreshPricing.disabled = false; els.refreshPricing.textContent = "刷新价格"; }
});

document.querySelectorAll(".preset").forEach(button => button.addEventListener("click", () => {
  const range = presetRange(button.dataset.days);
  els.start.value = range.start;
  els.end.value = range.end;
  els.startTime.value = "00:00";
  els.endTime.value = "23:59";
  els.startAt.value = els.endAt.value = "";
  applyFilters();
}));
els.scan.addEventListener("click", async () => {
  els.scan.disabled = true; els.scan.textContent = "扫描中…"; setStatus("正在增量扫描 Codex 会话日志…");
  try {
    const response = await fetch("/api/scan", { method: "POST" }); if (!response.ok) throw new Error("扫描失败");
    invalidateUsage(); state.pricingLoaded = false; await loadCurrentPage(true);
  } catch (error) { setStatus(error.message, "error"); }
  finally { els.scan.disabled = false; els.scan.textContent = "扫描新日志"; }
});
els.projectSelect.addEventListener("change", () => {
  paintProjectSelection();
  loadProjectDaily(els.projectSelect.value).catch(error => setStatus(error.message, "error"));
});
for (const chart of [els.projectChart, els.projectTotalCostChart, els.projectTable]) chart.addEventListener("click", event => {
  const row = event.target.closest("[data-project-key]"); if (!row) return;
  selectProject(row.dataset.projectKey);
});
for (const chart of [els.projectChart, els.projectTotalCostChart]) chart.addEventListener("keydown", event => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("[data-project-key]"); if (!row) return;
  event.preventDefault(); selectProject(row.dataset.projectKey);
});
document.querySelectorAll("[data-route]").forEach(link => link.addEventListener("click", event => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); const url = new URL(link.href); url.search = queryString(); history.pushState({}, "", url);
  setMenu(false); activateRoute();
}));
window.addEventListener("popstate", () => {
  const params = new URLSearchParams(location.search);
  els.start.value = params.get("start") || body.dataset.defaultStart; els.end.value = params.get("end") || body.dataset.defaultEnd;
  els.startTime.value = params.get("start_time") || "00:00"; els.endTime.value = params.get("end_time") || "23:59";
  els.startAt.value = params.get("start_at") || ""; els.endAt.value = params.get("end_at") || "";
  restoreAnalysis(params); invalidateUsage();
  activateRoute();
});
els.menuToggle.addEventListener("click", () => setMenu(!body.classList.contains("menu-open")));
els.sidebarBackdrop.addEventListener("click", () => setMenu(false));
document.addEventListener("keydown", event => { if (event.key === "Escape" && body.classList.contains("menu-open")) { setMenu(false); els.menuToggle.focus(); } });

const initialParams = new URLSearchParams(location.search);
restoreAnalysis(initialParams);
els.start.value = initialParams.get("start") || body.dataset.defaultStart;
els.end.value = initialParams.get("end") || body.dataset.defaultEnd;
els.startTime.value = initialParams.get("start_time") || "00:00";
els.endTime.value = initialParams.get("end_time") || "23:59";
els.startAt.value = initialParams.get("start_at") || "";
els.endAt.value = initialParams.get("end_at") || "";
const datePicker = new DateRangePicker({
  startInput: els.start,
  endInput: els.end,
  startTimeInput: els.startTime,
  endTimeInput: els.endTime,
  startAtInput: els.startAt,
  endAtInput: els.endAt,
  onChange: options => {
    applyFilters(options);
  },
});
synchronizeChartScrolling(els.tokenChart, els.costChart);
synchronizeChartScrolling(els.projectChart, els.projectTotalCostChart);
synchronizeChartScrolling(els.projectTokenChart, els.projectCostChart);
const usageTables = {
  models: createSortableTable(els.modelTable,
    [null, "calls", "fast_calls", "input_tokens", "cached_input_tokens", "output_tokens", "api_usd_known", "fast_surcharge_usd", "credits_known", "tier_coverage_percent"], renderModelTable),
  daily: createSortableTable(els.dailyTable,
    ["key", "calls", "fast_calls", "input_tokens", "uncached_input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "api_usd_known", "fast_surcharge_usd", "tier_coverage_percent"],
    rows => { els.dailyTable.innerHTML = dailyRows(rows); }),
  projects: createSortableTable(els.projectTable,
    [null, "calls", "fast_calls", "input_tokens", "cached_input_tokens", "output_tokens", "total_tokens", "api_usd_known", "fast_surcharge_usd", "price_coverage_percent"], renderProjectTable),
  sessions: createSortableTable(els.sessionTable,
    [null, null, "last_activity", "calls", "total_tokens", "fast_calls", "api_usd_known", "fast_surcharge_usd"], paintSessionList,
    field => {
      sessionPage = 0;
      els.sessionSort.value = {api_usd_known:"cost", total_tokens:"tokens", fast_surcharge_usd:"fast"}[field] || "";
      paintSessionList();
    }),
  requests: createSortableTable(els.requestTable,
    ["timestamp", null, "service_tier", "input_tokens", "cached_input_tokens", "output_tokens", "api_usd_known", "fast_surcharge_usd", "price_snapshot"], () => {},
    () => { requestOffset = 0; if (selectedSession) loadSessionDetail(); }),
};
loadQuota();
activateRoute();
