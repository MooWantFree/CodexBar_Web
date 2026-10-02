import {useState} from 'react';
import {t, addMessages, locale} from '../lib/i18n';
import {formatNumber, formatCompact, modelColor, modelName} from '../lib/format';
import {CostValue, unknownCostTitle, costText} from './CostValue';

addMessages({
  en: {'暂无数据': 'No data', '正在读取…': 'Loading…', '上一页': 'Previous', '下一页': 'Next', '日期': 'Date', '调用': 'Calls', '普通输入': 'Uncached input', '缓存输入': 'Cached input', '缓存': 'Cached', '总 Token': 'Total tokens', 'API 等价': 'API equivalent', 'Fast API 加价': 'Fast API surcharge', '档位覆盖': 'Tier coverage', '价格覆盖': 'Price coverage', '定价覆盖 {percent}% 调用': 'Pricing covers {percent}% of calls', '定价 {percent}%': 'Priced {percent}%', '未知': 'Unknown', '升序': 'ascending', '降序': 'descending', '{label}：点击按{direction}排序': '{label}: sort {direction}', '这个日期范围还没有可统计的记录。': 'No records in this date range.'},
  ja: {'暂无数据': 'データがありません', '正在读取…': '読み込み中…', '上一页': '前へ', '下一页': '次へ', '日期': '日付', '调用': '呼び出し', '普通输入': '非キャッシュ入力', '缓存输入': 'キャッシュ入力', '缓存': 'キャッシュ', '总 Token': '総トークン', 'API 等价': 'API相当額', 'Fast API 加价': 'Fast API追加料金', '档位覆盖': 'ティア判明率', '价格覆盖': '価格判明率', '定价覆盖 {percent}% 调用': '呼び出しの{percent}%に価格あり', '定价 {percent}%': '価格判明 {percent}%', '未知': '不明', '升序': '昇順', '降序': '降順', '{label}：点击按{direction}排序': '{label}：{direction}で並べ替え', '这个日期范围还没有可统计的记录。': 'この期間には記録がありません。'},
});

export function EmptyState({children = t('暂无数据')}) { return <div className="empty-state">{children}</div>; }
export function ErrorNotice({error}) { return error ? <p className="status-strip error-text" role="alert">{error.message || String(error)}</p> : null; }
export function LoadingState() { return <p className="fine-print" role="status">{t('正在读取…')}</p>; }
export function Pager({page, pages, onPage, disabled = false}) {
  return <div className="pager"><button className="button" disabled={disabled || page <= 0} onClick={() => onPage(page - 1)}>{t('上一页')}</button><span aria-live="polite">{pages ? `${formatNumber(page + 1)} / ${formatNumber(pages)}` : '0 / 0'}</span><button className="button" disabled={disabled || page + 1 >= pages} onClick={() => onPage(page + 1)}>{t('下一页')}</button></div>;
}
export function Coverage({value}) { return <span className={`coverage ${value === 100 ? '' : 'partial'}`}>{value?.toFixed(1) || '0'}%</span>; }
export function StackedChart({rows = [], metric = 'total_tokens'}) {
  if (!rows.length) return <EmptyState>{t('这个日期范围还没有可统计的记录。')}</EmptyState>;
  const isCost = metric === 'api_usd_known';
  const max = Math.max(...rows.map(row => row[metric] || 0), Number.EPSILON);
  return <>{[...rows].reverse().map(row => <div className="chart-row" key={row.key}>
    <span className="chart-date" title={row.key}>{row.label || row.key?.slice(5)}</span>
    <div className="chart-track">{(row.models || []).filter(model => model[metric] > 0).map(model => <span key={model.model || model.key} className="segment model-segment" style={{width: `${model[metric] / max * 100}%`, background: modelColor(model.model || model.key)}} title={`${modelName(model)}\n${isCost ? costText(model) : formatNumber(model[metric])}${isCost ? `\n${t('定价覆盖 {percent}% 调用', {percent: model.price_coverage_percent?.toFixed(1)})}` : ''}${isCost && unknownCostTitle(model, 'api', [model]) ? `\n${unknownCostTitle(model, 'api', [model])}` : ''}`} />)}</div>
    <span className="chart-value">{isCost ? <CostValue row={row} unknownOnly={row.unknown_price_calls > 0 && !row.priced_calls}/> : formatCompact(row[metric])}{isCost && row.unknown_price_calls > 0 && <small className="chart-warning" title={unknownCostTitle(row)}>{t('定价 {percent}%', {percent: row.price_coverage_percent?.toFixed(0)})}</small>}</span>
  </div>)}</>;
}
export function UsageTable({rows = [], project = false}) {
  const [sort, setSort] = useState({key: 'api_usd_known', direction: 'descending'});
  const fields = project
    ? [['key', '日期'], ['calls', '调用'], ['input_tokens', 'Input'], ['cached_input_tokens', '缓存'], ['output_tokens', 'Output'], ['total_tokens', '总 Token'], ['api_usd_known', 'API 等价'], ['price_coverage_percent', '价格覆盖']]
    : [['key', '日期'], ['calls', '调用'], ['fast_calls', 'Fast'], ['input_tokens', 'Input'], ['uncached_input_tokens', '普通输入'], ['cached_input_tokens', '缓存输入'], ['output_tokens', 'Output'], ['total_tokens', '总 Token'], ['api_usd_known', 'API 等价'], ['fast_surcharge_usd', 'Fast API 加价'], ['tier_coverage_percent', '档位覆盖']];
  const value = row => {
    if (sort.key === 'api_usd_known' && row.unknown_price_calls && !row.priced_calls) return null;
    if (sort.key === 'fast_surcharge_usd' && row.unknown_fast_price_calls && !row.fast_surcharge_usd) return null;
    return row[sort.key];
  };
  const sorted = [...rows].sort((a, b) => {
    const left = value(a), right = value(b);
    const missingLeft = left == null || (typeof left === 'number' && !Number.isFinite(left));
    const missingRight = right == null || (typeof right === 'number' && !Number.isFinite(right));
    return Number(missingLeft) - Number(missingRight) || (missingLeft ? 0 : (typeof left === 'string' ? left.localeCompare(right, locale) : left - right) * (sort.direction === 'ascending' ? 1 : -1));
  });
  return <table><thead><tr>{fields.map(([key, label]) => <th key={key} aria-sort={sort?.key === key ? sort.direction : 'none'}><button className="table-sort" aria-label={t('{label}：点击按{direction}排序', {label: t(label), direction: t(sort?.key === key && sort.direction === 'ascending' ? '降序' : '升序')})} onClick={() => setSort({key, direction: sort?.key === key && sort.direction === 'ascending' ? 'descending' : 'ascending'})}>{t(label)} <span className="sort-indicator">{sort?.key === key ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></button></th>)}</tr></thead>
    <tbody>{sorted.map(row => <tr key={row.key}>{fields.map(([key]) => <td key={key}>{key === 'key' ? row.label || row.key : key.endsWith('_percent') ? <Coverage value={row[key]} /> : key === 'api_usd_known' ? <CostValue row={row}/> : key === 'fast_surcharge_usd' ? <CostValue row={row} kind="fast"/> : formatNumber(row[key])}</td>)}</tr>)}{!rows.length && <tr><td colSpan={fields.length}><EmptyState /></td></tr>}</tbody></table>;
}

