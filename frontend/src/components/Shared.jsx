import {useState} from 'react';
import {t, locale} from "../lib/i18n";
import {formatNumber, formatCompact, modelColor, modelName} from '../lib/format';
import {CostValue, unknownCostTitle, costText} from './CostValue';
import {LoadingStatus, UsageSkeleton, UsageTableSkeleton} from './UsageSkeleton';

export function EmptyState({children = t("common:noData")}) { return <div className="empty-state">{children}</div>; }
export function ErrorNotice({error}) { return error ? <p className="status-strip error-text" role="alert">{error.message || String(error)}</p> : null; }
export function LoadingState() { return <><LoadingStatus loading/><UsageSkeleton className="usage-line-skeleton"/></>; }
export function Pager({page, pages, onPage, disabled = false, loading = false}) {
  return <div className="pager"><button className="button" disabled={disabled || loading || page <= 0} onClick={() => onPage(page - 1)}>{t("common:previous")}</button><span aria-live="polite">{loading ? <UsageSkeleton className="usage-inline-skeleton"/> : pages ? `${formatNumber(page + 1)} / ${formatNumber(pages)}` : '0 / 0'}</span><button className="button" disabled={disabled || loading || page + 1 >= pages} onClick={() => onPage(page + 1)}>{t("common:next")}</button></div>;
}
export function Coverage({value}) { return <span className={`coverage ${value === 100 ? '' : 'partial'}`}>{value?.toFixed(1) || '0'}%</span>; }
export function StackedChart({rows = [], metric = 'total_tokens'}) {
  if (!rows.length) return <EmptyState>{t("common:noRecordsInThisDateRange")}</EmptyState>;
  const isCost = metric === 'api_usd_known';
  const max = Math.max(...rows.map(row => row[metric] || 0), Number.EPSILON);
  return <>{[...rows].reverse().map(row => <div className="chart-row" key={row.key}>
    <span className="chart-date" title={row.key}>{row.label || row.key?.slice(5)}</span>
    <div className="chart-track">{(row.models || []).filter(model => model[metric] > 0).map(model => <span key={model.model || model.key} className="segment model-segment" style={{width: `${model[metric] / max * 100}%`, background: modelColor(model.model || model.key)}} title={`${modelName(model)}\n${isCost ? costText(model) : formatNumber(model[metric])}${isCost ? `\n${t("usage:priceCoverageOfCalls", {percent: model.price_coverage_percent?.toFixed(1)})}` : ''}${isCost && unknownCostTitle(model, 'api', [model]) ? `\n${unknownCostTitle(model, 'api', [model])}` : ''}`} />)}</div>
    <span className="chart-value">{isCost ? <CostValue row={row} unknownOnly={row.unknown_price_calls > 0 && !row.priced_calls}/> : formatCompact(row[metric])}{isCost && row.unknown_price_calls > 0 && <small className="chart-warning" title={unknownCostTitle(row)}>{t("usage:priced", {percent: row.price_coverage_percent?.toFixed(0)})}</small>}</span>
  </div>)}</>;
}
export function UsageTable({rows = [], project = false, loading = false}) {
  const [sort, setSort] = useState({key: 'api_usd_known', direction: 'descending'});
  const fields = project
    ? [['key', "common:date"], ['calls', "usage:calls"], ['input_tokens', "common:input"], ['cached_input_tokens', "usage:cached"], ['output_tokens', "common:output"], ['total_tokens', "usage:totalToken"], ['api_usd_known', "usage:apiEquivalent"], ['price_coverage_percent', "usage:priceCoverage"]]
    : [['key', "common:date"], ['calls', "usage:calls"], ['fast_calls', "common:fast"], ['input_tokens', "common:input"], ['uncached_input_tokens', "common:uncachedInput"], ['cached_input_tokens', "common:cachedInput"], ['output_tokens', "common:output"], ['total_tokens', "usage:totalToken"], ['api_usd_known', "usage:apiEquivalent"], ['fast_surcharge_usd', "usage:fastApiSurcharge"], ['tier_coverage_percent', "usage:tierCoverage"]];
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
  return <table><thead><tr>{fields.map(([key, label]) => <th key={key} aria-sort={sort?.key === key ? sort.direction : 'none'}><button className="table-sort" aria-label={t("usage:sortAccessibleLabel", {label: t(label), direction: t(sort?.key === key && sort.direction === 'ascending' ? "usage:descending" : "usage:ascending")})} onClick={() => setSort({key, direction: sort?.key === key && sort.direction === 'ascending' ? 'descending' : 'ascending'})}>{t(label)} <span className="sort-indicator">{sort?.key === key ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></button></th>)}</tr></thead>
    <tbody>{loading ? <UsageTableSkeleton columns={fields.length}/> : sorted.map(row => <tr key={row.key}>{fields.map(([key]) => <td key={key}>{key === 'key' ? row.label || row.key : key.endsWith('_percent') ? <Coverage value={row[key]} /> : key === 'api_usd_known' ? <CostValue row={row}/> : key === 'fast_surcharge_usd' ? <CostValue row={row} kind="fast"/> : formatNumber(row[key])}</td>)}</tr>)}{!loading && !rows.length && <tr><td colSpan={fields.length}><EmptyState /></td></tr>}</tbody></table>;
}

