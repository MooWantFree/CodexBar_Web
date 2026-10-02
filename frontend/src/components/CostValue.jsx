import {t, addMessages} from '../lib/i18n';
import {formatNumber, money, fastSurcharge, modelName} from '../lib/format';

addMessages({
  en: {
    '有 {count} 次调用的 API 等价金额未知。计算所需的模型或 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知部分。': 'API equivalent cost is unknown for {count} calls. The model or required Token rates are missing, or the Fast multiplier is unknown; saved price snapshots may also lack these prices. Displayed amounts include only the known portion.',
    '有 {count} 次 Fast 调用的 API 加价未知。模型或所需 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知加价。': 'API surcharge is unknown for {count} Fast calls. The model or required Token rates are missing, or the Fast multiplier is unknown; saved price snapshots may also lack these prices. Displayed amounts include only known surcharges.',
    '计算所需的价格信息缺失，无法确定金额。': 'Required pricing information is missing, so the amount cannot be determined.',
    '未能计价的模型：{models}。': 'Models with unpriced calls: {models}.',
  },
  ja: {
    '有 {count} 次调用的 API 等价金额未知。计算所需的模型或 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知部分。': '{count} 回の呼び出しの API 相当額が不明です。モデルまたは必要な Token 単価がないか、Fast 倍率が不明です。保存済み価格スナップショットにこれらの価格がない場合もあります。表示額は判明分のみです。',
    '有 {count} 次 Fast 调用的 API 加价未知。模型或所需 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知加价。': '{count} 回の Fast 呼び出しの API 追加料金が不明です。モデルまたは必要な Token 単価がないか、Fast 倍率が不明です。保存済み価格スナップショットにこれらの価格がない場合もあります。表示額は判明した追加料金のみです。',
    '计算所需的价格信息缺失，无法确定金额。': '必要な価格情報がないため、金額を算出できません。',
    '未能计价的模型：{models}。': '価格不明の呼び出しがあるモデル：{models}。',
  },
});

const amountField = kind => kind === 'fast' ? 'fast_surcharge_usd' : 'api_usd_known';
const unknownField = kind => kind === 'fast' ? 'unknown_fast_price_calls' : 'unknown_price_calls';
export const amountUnknown = (row, kind = 'api') => Number(row?.[unknownField(kind)]) > 0 || row?.[amountField(kind)] === null;

export function unknownCostTitle(row, kind = 'api', models = row?.models) {
  if (!amountUnknown(row, kind)) return undefined;
  const count = Number(row?.[unknownField(kind)]) || 0;
  const reason = count > 0 ? t(kind === 'fast'
    ? '有 {count} 次 Fast 调用的 API 加价未知。模型或所需 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知加价。'
    : '有 {count} 次调用的 API 等价金额未知。计算所需的模型或 Token 单价缺失，或 Fast 倍率未知；历史价格快照也可能未保存这些价格。显示金额仅包含已知部分。', {count: formatNumber(count)})
    : t('计算所需的价格信息缺失，无法确定金额。');
  const names = [...new Set((Array.isArray(models) ? models : []).filter(model => model && typeof model === 'object' && amountUnknown(model, kind)).map(modelName))];
  if (!names.length && (row?.model || Object.hasOwn(row || {}, 'model_id'))) names.push(modelName({key: row.model_id, model: row.model_id || row.model, display_name: row.model}));
  return names.length ? `${reason}\n${t('未能计价的模型：{models}。', {models: names.join(' · ')})}` : reason;
}

export function costText(row, kind = 'api', {unknownOnly = false} = {}) {
  const unknown = amountUnknown(row, kind);
  if (unknown && (unknownOnly || row?.[amountField(kind)] === null)) return t('未知');
  if (kind === 'fast') return fastSurcharge(row);
  return money(row?.api_usd_known);
}

export function CostValue({row, kind = 'api', as: Tag = 'span', unknownOnly = false, models, className = '', ...props}) {
  const unknown = amountUnknown(row, kind);
  return <Tag {...props} className={`cost-value${unknown ? ' unknown-cost' : ''}${className ? ` ${className}` : ''}`}
    title={unknownCostTitle(row, kind, models)}>{costText(row, kind, {unknownOnly})}</Tag>;
}
