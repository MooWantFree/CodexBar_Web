import {locale, t, addMessages} from './i18n';

addMessages({
  en: {'未知模型': 'Unknown model', '未知': 'Unknown', '主额度窗口': 'Primary quota window', '次额度窗口': 'Secondary quota window', '每周额度': 'Weekly quota', '{count} 天额度': '{count}-day quota', '{count} 小时额度': '{count}-hour quota', '{count} 分钟额度': '{count}-minute quota'},
  ja: {'未知模型': '不明なモデル', '未知': '不明', '主额度窗口': '主要クォータ枠', '次额度窗口': '副次クォータ枠', '每周额度': '週間クォータ', '{count} 天额度': '{count}日間のクォータ', '{count} 小时额度': '{count}時間のクォータ', '{count} 分钟额度': '{count}分間のクォータ'},
});

const formatterCache = new Map();
function formatters() {
  if (!formatterCache.has(locale)) formatterCache.set(locale, {
    number: new Intl.NumberFormat(locale),
    compact: new Intl.NumberFormat(locale, {notation: 'compact', maximumFractionDigits: 2}),
    currency: new Intl.NumberFormat(locale, {style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2, maximumFractionDigits: 2}),
  });
  return formatterCache.get(locale);
}
export const formatNumber = value => formatters().number.format(value || 0);
export const formatCompact = value => formatters().compact.format(value || 0);
export const money = value => formatters().currency.format(value || 0);
export function formatDateTime(value, options = {}) {
  return value == null || value === '' ? t('未知') : new Date(value).toLocaleString(locale, {timeZone: document.body.dataset.timezone || 'UTC', hour12: false, ...options});
}
export function fastSurcharge(row, precise = false) {
  const amount = money(row.fast_surcharge_usd, precise);
  return row.unknown_fast_price_calls && !row.fast_surcharge_usd ? t('未知') : amount;
}
const colors = {'gpt-6-astra': '#7655c5', 'gpt-5.6-sol': '#277ad9', 'gpt-5.6-terra': '#2f8a57', 'gpt-5.6-luna': '#168e94', 'codex-auto-review': '#b66a12'};
export function modelName(row) {
  const identity = row.model || row.key;
  return identity === 'unknown' ? t('未知模型') : row.display_name || identity || t('未知模型');
}

export function modelColor(model) {
  const normalized = String(model || 'unknown').toLowerCase();
  if (colors[normalized]) return colors[normalized];
  let hash = 0;
  for (const char of normalized) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `hsl(${((hash % 360) + 360) % 360} 52% 52%)`;
}
export function quotaWindowLabel(window) {
  const minutes = window.window_minutes;
  let label = t(window.slot === 'primary' ? '主额度窗口' : '次额度窗口');
  if (minutes === 10080) label = t('每周额度');
  else if (minutes && minutes % 1440 === 0) label = t('{count} 天额度', {count: formatNumber(minutes / 1440)});
  else if (minutes && minutes % 60 === 0) label = t('{count} 小时额度', {count: formatNumber(minutes / 60)});
  else if (minutes) label = t('{count} 分钟额度', {count: formatNumber(minutes)});
  return window.limit_id === 'codex' ? label : `${window.limit_name || window.limit_id || ''} · ${label}`;
}
