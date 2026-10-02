import {useSyncExternalStore} from 'react';
import zhMessages from './zhMessages';

const supportedLocales = new Set(["en", "ja", "zh"]);

export function detectLocale(browser = globalThis.navigator) {
  const preferences = browser?.languages?.length ? browser.languages : [browser?.language];
  return Array.from(preferences, language => String(language || "").toLowerCase().split(/[-_]/)[0])
    .find(language => supportedLocales.has(language)) || "en";
}

export const LANGUAGE_STORAGE_KEY = 'codex-token-report.language';
const validPreferences = new Set(['auto', 'en', 'ja', 'zh']);
const normalizePreference = value => validPreferences.has(value) ? value : 'auto';

function readPreference() {
  try { return normalizePreference(globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY)); }
  catch { return 'auto'; }
}

let preference = readPreference();
export let locale = preference === 'auto' ? detectLocale() : preference;
const subscribers = new Set();
const subscribe = listener => { subscribers.add(listener); return () => subscribers.delete(listener); };
const currentLocale = () => locale;
export const getLanguagePreference = () => preference;
export const useLocale = () => useSyncExternalStore(subscribe, currentLocale, currentLocale);
export const useLanguagePreference = () => useSyncExternalStore(subscribe, getLanguagePreference, getLanguagePreference);

function updatePreference(value) {
  const next = normalizePreference(value);
  const nextLocale = next === 'auto' ? detectLocale() : next;
  const changed = preference !== next || locale !== nextLocale;
  preference = next;
  locale = nextLocale;
  if (globalThis.document?.documentElement) document.documentElement.lang = locale;
  if (changed) for (const listener of subscribers) listener();
}

export function setLanguagePreference(value) {
  const next = normalizePreference(value);
  try { globalThis.localStorage?.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* Keep the selection usable when storage is blocked. */ }
  updatePreference(next);
}

if (globalThis.window) {
  window.addEventListener('storage', event => {
    if (event.key === LANGUAGE_STORAGE_KEY || event.key === null) updatePreference(event.key === null ? 'auto' : event.newValue);
  });
  window.addEventListener('languagechange', () => { if (preference === 'auto') updatePreference('auto'); });
}
const messages = { en: Object.create(null), ja: Object.create(null), zh: Object.assign(Object.create(null), zhMessages) };

export function addMessages(catalogs = {}) {
  // Chinese-keyed features already carry their native wording. Keep explicit
  // Chinese translations authoritative, and translate English keys separately.
  for (const source of Object.keys(catalogs.en || {})) {
    if (/\p{Script=Han}/u.test(source) && !Object.hasOwn(messages.zh, source)) messages.zh[source] = source;
  }
  for (const language of supportedLocales) Object.assign(messages[language], catalogs[language] || {});
}

export function t(source, params = {}) {
  const message = messages[locale][source] ?? messages.en[source] ?? source;
  return String(message).replace(/\{(\w+)\}/g, (placeholder, name) =>
    Object.hasOwn(params, name) ? String(params[name]) : placeholder);
}

if (globalThis.document?.documentElement) document.documentElement.lang = locale;

addMessages({
  en: {
    "开启导航": "Open navigation", "打开导航": "Open navigation", "关闭导航": "Close navigation", "主导航": "Main navigation",
    "用量总览": "Usage overview", "每日明细": "Daily usage", "项目用量": "Project usage", "会话用量": "Session usage",
    "模型定价": "Model pricing", "重置日期": "Reset history", "额度等价美元": "Quota value in USD",
    "本地数据": "Local data", "扫描新日志": "Scan new logs", "扫描中…": "Scanning…",
    "价格口径": "Pricing basis", "快照估算": "Saved price estimate", "当前价格重算": "Recalculate at current prices",
    "按天": "Daily", "按小时": "Hourly", "统计粒度": "Time interval",
    "Token、模型与 API 等价成本概览。": "An overview of tokens, models, and API equivalent costs.",
    "管理 models.dev 价格缓存与本地手工覆盖。": "Manage cached models.dev prices and local overrides.",
    "逐日核对调用、Token 与等价成本。": "Review daily calls, tokens, and equivalent costs.",
    "按 Git 项目查看总量与每日使用情况。": "View totals and daily usage by Git project.",
    "查看重置时间，选择两个时刻统计期间用量。": "Select two reset times to review usage between them.",
    "从本周期已用额度，推算每 1% 和整窗额度的 API 等价美元。": "Estimate the API equivalent value of 1% and the full quota window from this cycle's usage.",
    "查看会话排行、用量趋势与每次调用。": "View session rankings, usage trends, and individual calls.",
    "USAGE OVERVIEW": "USAGE OVERVIEW", "DAILY LEDGER": "DAILY LEDGER", "PROJECT USAGE": "PROJECT USAGE",
    "SESSION USAGE": "SESSION USAGE", "MODEL PRICING": "MODEL PRICING", "RESET HISTORY": "RESET HISTORY",
    "QUOTA VALUE": "QUOTA VALUE", "LOCAL ANALYTICS": "LOCAL ANALYTICS",
    "加载中…": "Loading…", "正在加载…": "Loading…", "读取中…": "Loading…", "加载失败": "Failed to load", "读取失败": "Failed to load", "重试": "Retry", "刷新": "Refresh", "暂无数据": "No data", "日志目录": "Log directory", "日志目录：": "Log directory: ", "不保存消息正文 · 不上传数据 · 只监听本机": "No message content stored · No uploads · Local access only",
  },
  ja: {
    "开启导航": "ナビゲーションを開く", "打开导航": "ナビゲーションを開く", "关闭导航": "ナビゲーションを閉じる", "主导航": "メインナビゲーション",
    "用量总览": "使用量の概要", "每日明细": "日別の使用量", "项目用量": "プロジェクトの使用量", "会话用量": "セッションの使用量",
    "模型定价": "モデル料金", "重置日期": "リセット履歴", "额度等价美元": "利用枠のドル換算",
    "本地数据": "ローカルデータ", "扫描新日志": "新しいログをスキャン", "扫描中…": "スキャン中…",
    "价格口径": "料金の基準", "快照估算": "保存済み料金で推計", "当前价格重算": "現在の料金で再計算",
    "按天": "日別", "按小时": "時間別", "统计粒度": "集計単位",
    "Token、模型与 API 等价成本概览。": "トークン、モデル、API 換算コストの概要。",
    "管理 models.dev 价格缓存与本地手工覆盖。": "models.dev の料金キャッシュとローカルの手動設定を管理します。",
    "逐日核对调用、Token 与等价成本。": "呼び出し、トークン、換算コストを日別に確認します。",
    "按 Git 项目查看总量与每日使用情况。": "Git プロジェクト別に合計と日々の使用状況を確認します。",
    "查看重置时间，选择两个时刻统计期间用量。": "2 つのリセット時刻を選択して、その間の使用量を確認します。",
    "从本周期已用额度，推算每 1% 和整窗额度的 API 等价美元。": "今周期の使用量から、利用枠の 1% と全体の API 換算額を推計します。",
    "查看会话排行、用量趋势与每次调用。": "セッションの順位、使用量の推移、各呼び出しを確認します。",
    "USAGE OVERVIEW": "使用量の概要", "DAILY LEDGER": "日別明細", "PROJECT USAGE": "プロジェクトの使用量",
    "SESSION USAGE": "セッションの使用量", "MODEL PRICING": "モデル料金", "RESET HISTORY": "リセット履歴",
    "QUOTA VALUE": "利用枠の換算額", "LOCAL ANALYTICS": "ローカル分析",
    "加载中…": "読み込み中…", "正在加载…": "読み込み中…", "读取中…": "読み込み中…", "加载失败": "読み込みに失敗しました", "读取失败": "読み込みに失敗しました", "重试": "再試行", "刷新": "更新", "暂无数据": "データがありません", "日志目录": "ログディレクトリ", "日志目录：": "ログディレクトリ：", "不保存消息正文 · 不上传数据 · 只监听本机": "メッセージ本文を保存しません · データを送信しません · ローカル接続のみ",
  },
});
