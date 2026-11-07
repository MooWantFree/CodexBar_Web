import {t} from "../lib/i18n";
import {money, fastSurcharge, modelName} from '../lib/format';

const amountField = kind => kind === 'fast' ? 'fast_surcharge_usd' : 'api_usd_known';
const unknownField = kind => kind === 'fast' ? 'unknown_fast_price_calls' : 'unknown_price_calls';
export const amountUnknown = (row, kind = 'api') => Number(row?.[unknownField(kind)]) > 0 || row?.[amountField(kind)] === null;

export function unknownCostTitle(row, kind = 'api', models = row?.models) {
  if (!amountUnknown(row, kind)) return undefined;
  const count = Number(row?.[unknownField(kind)]) || 0;
  let reason = count > 0 ? t(kind === 'fast'
    ? "costs:unknownFastSurcharge"
    : "costs:unknownApiCost", {count})
    : t("costs:missingPrices");
  const fallback = Number(row?.fast_standard_fallback_calls) || Number(Boolean(row?.api_standard_fallback));
  if (kind === 'api' && fallback > 0) reason += `\n${t("costs:standardRateFallback", {count: fallback})}`;
  const names = [...new Set((Array.isArray(models) ? models : []).filter(model => model && typeof model === 'object' && amountUnknown(model, kind)).map(modelName))];
  if (!names.length && (row?.model || Object.hasOwn(row || {}, 'model_id'))) names.push(modelName({key: row.model_id, model: row.model_id || row.model, display_name: row.model}));
  return names.length ? `${reason}\n${t("costs:modelsWithUnpricedCalls", {models: names.join(' · ')})}` : reason;
}

export function costText(row, kind = 'api', {unknownOnly = false} = {}) {
  const unknown = amountUnknown(row, kind);
  if (unknown && (unknownOnly || row?.[amountField(kind)] === null)) return t("common:unknown");
  if (kind === 'fast') return fastSurcharge(row);
  return money(row?.api_usd_known);
}

export function CostValue({row, kind = 'api', as: Tag = 'span', unknownOnly = false, models, className = '', ...props}) {
  const unknown = amountUnknown(row, kind);
  return <Tag {...props} className={`cost-value${unknown ? ' unknown-cost' : ''}${className ? ` ${className}` : ''}`}
    title={unknownCostTitle(row, kind, models)}>{costText(row, kind, {unknownOnly})}</Tag>;
}
