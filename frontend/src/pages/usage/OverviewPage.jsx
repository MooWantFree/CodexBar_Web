import {useMemo, useState} from 'react';
import {t} from '../../lib/i18n';
import {formatNumber, formatCompact, fastSurcharge, modelColor, modelName} from '../../lib/format';
import {EmptyState, ErrorNotice} from '../../components/Shared';
import {useSummary, sortUsageRows, numeric, fixed, cost, priceUnknown, EMPTY_ROWS, SnapshotNotice, TrendPair, SortableHead, Coverage, MODEL_COLUMNS} from './UsageShared';

export default function OverviewPage() {
  const query = useSummary();
  const [sort, setSort] = useState({field: 'api_usd_known', direction: 'descending'});
  const total = query.data?.total;
  const models = query.data?.models || EMPTY_ROWS;
  const sorted = useMemo(() => sortUsageRows(models, sort), [models, sort]);
  if (!total) return <><ErrorNotice error={query.error}/><EmptyState>{t(query.isPending ? '正在汇总用量…' : '暂无数据')}</EmptyState></>;
  const cacheRate = total.input_tokens ? total.cached_input_tokens / total.input_tokens * 100 : 0;
  const kpis = [
    ['accent-blue', '总 Input', formatCompact(total.input_tokens), formatNumber(total.input_tokens), t('普通输入 {count}', {count: formatCompact(total.uncached_input_tokens)}), 'inputKpi'],
    ['accent-cyan', '缓存 Input', formatCompact(total.cached_input_tokens), formatNumber(total.cached_input_tokens), t('占 Input {percent}%', {percent: fixed(cacheRate)}), 'cachedKpi'],
    ['accent-violet', '总 Output', formatCompact(total.output_tokens), formatNumber(total.output_tokens), t('其中推理 {count}', {count: formatCompact(total.reasoning_output_tokens)}), 'outputKpi'],
    ['accent-amber', 'API 等价成本', cost(total), '', t('定价覆盖 {percent}% 调用', {percent: fixed(total.price_coverage_percent)}), 'costKpi'],
    ['accent-green', 'Credits 用量估算', total.unknown_credit_calls ? `${formatNumber(Number(fixed(total.credits_known, 3)))} + ${t('未知')}` : formatNumber(Number(fixed(total.credits_known, 3))), '', t('公开 token 费率估算'), 'creditsKpi'],
    ['accent-pink', 'Fast 调用', formatNumber(total.fast_calls), `Fast tokens ${formatNumber(total.fast_tokens)}`, t('档位覆盖 {percent}%', {percent: fixed(total.tier_coverage_percent)}), 'fastKpi'],
  ];
  return <section className="page" data-page="overview" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/>
    <SnapshotNotice inferred={total.inferred_price_calls}/>
    <section className="kpi-grid">{kpis.map(([accent, title, value, tooltip, detail, id]) => <article key={id} className={`kpi-card ${accent}`}>
      <p>{t(title)}</p><strong id={id} title={tooltip}>{value}</strong><small>{detail}</small>
    </article>)}</section>
    <TrendPair report={query.data}/>
    <section className="panel table-panel"><div className="panel-heading model-heading"><div><p className="eyebrow">{t('模型汇总')}</p><h2>{t('按模型统计')}</h2></div>
      <div id="modelLegend" className="legend model-legend" aria-label={t('模型图例')}>{models.map(row => <span key={row.key}><i style={{background: modelColor(row.key)}}/>{modelName(row)}</span>)}</div>
    </div><div className="table-wrap"><table><SortableHead columns={MODEL_COLUMNS} sort={sort} onSort={setSort}/><tbody id="modelTable">
      {sorted.map(row => <tr key={row.key}><td><i className="model-dot" style={{background: modelColor(row.key)}}/>{modelName(row)}</td>
        <td>{formatNumber(row.calls)}</td><td>{formatNumber(row.fast_calls)}</td><td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.cached_input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td>
        <td className={priceUnknown(row) ? 'unknown' : ''}>{cost(row)}</td><td>{fastSurcharge(row)}</td><td>{row.unknown_credit_calls ? '—' : formatNumber(Number(fixed(row.credits_known, 3)))}</td><td><Coverage value={row.tier_coverage_percent}/></td>
      </tr>)}{!models.length && <tr><td colSpan={10}><EmptyState>{t('暂无数据')}</EmptyState></td></tr>}
    </tbody></table></div></section>
  </section>;
}

