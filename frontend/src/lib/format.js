import {locale, t} from "./i18n";

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
  return value == null || value === '' ? t("common:unknown") : new Date(value).toLocaleString(locale, {timeZone: document.body.dataset.timezone || 'UTC', hour12: false, ...options});
}
export function fastSurcharge(row, precise = false) {
  const amount = money(row.fast_surcharge_usd, precise);
  return row.unknown_fast_price_calls && !row.fast_surcharge_usd ? t("common:unknown") : amount;
}
const colors = {'gpt-6-astra': '#7655c5', 'gpt-5.6-sol': '#277ad9', 'gpt-5.6-terra': '#2f8a57', 'gpt-5.6-luna': '#168e94', 'codex-auto-review': '#b66a12'};
export function modelName(row) {
  const identity = row.model || row.key;
  return identity === 'unknown' ? t("common:unknownModel") : row.display_name || identity || t("common:unknownModel");
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
  let label = t(window.slot === 'primary' ? "common:primaryQuotaWindow" : "common:secondaryQuotaWindow");
  if (minutes === 10080) label = t("dates:weeklyQuota");
  else if (minutes && minutes % 1440 === 0) label = t("common:dayQuota", {count: minutes / 1440});
  else if (minutes && minutes % 60 === 0) label = t("common:hourQuota", {count: minutes / 60});
  else if (minutes) label = t("common:minuteQuota", {count: minutes});
  return window.limit_id === 'codex' ? label : `${window.limit_name || window.limit_id || ''} · ${label}`;
}
