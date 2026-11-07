import {useMemo, useRef, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useDashboard} from '../../context/DashboardContext';
import {apiGet} from '../../lib/api';
import {t} from '../../lib/i18n';
import {formatNumber, formatCompact, modelColor, modelName} from '../../lib/format';
import {EmptyState, ErrorNotice, UsageTable} from '../../components/Shared';
import {CostValue, costText, unknownCostTitle} from '../../components/CostValue';
import {LoadingStatus, UsageChartSkeleton, UsageSkeleton, UsageTableSkeleton} from '../../components/UsageSkeleton';
import {EMPTY_ROWS, numeric, fixed, priceUnknown, projectName, sortUsageRows, SortableHead, Coverage, TrendPair, useSynchronizedCharts, scrollToDetail, FAST_TITLE} from './UsageShared';

function ProjectChart({rows, metric, selected, onSelect, loading}) {
  const max = Math.max(...rows.map(row => numeric(row[metric])), Number.EPSILON);
  const isCost = metric === 'api_usd_known';
  return <div id={isCost ? 'projectTotalCostChart' : 'projectChart'} className="daily-chart project-chart" tabIndex={0}
    aria-label={t(isCost ? "usage:projectApiEquivalentCostOrderedByToken" : "usage:projectTokenUsage")}>
    {loading ? <UsageChartSkeleton/> : rows.length ? rows.map(row => <div key={row.key} className={`chart-row ${selected === row.key ? 'selected' : ''}`}
      role="button" tabIndex={0} aria-controls="projectDetail" aria-pressed={selected === row.key} title={row.path || t("usage:projectPathUnavailable")}
      onClick={() => onSelect(row.key)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(row.key); } }}>
      <span className="project-label">{projectName(row)}</span><div className="chart-track">{(row.models || []).filter(model => model[metric]).map(model => <span key={model.model || model.key} className="segment model-segment"
        style={{width: `${model[metric] / max * 100}%`, background: modelColor(model.model || model.key)}}
        title={`${modelName(model)}\n${isCost ? costText(model) : `${formatNumber(model[metric])} Token`}${isCost ? `\n${t("usage:priceCoverageOfCalls", {percent: fixed(model.price_coverage_percent)})}` : ''}${isCost && unknownCostTitle(model, 'api', [model]) ? `\n${unknownCostTitle(model, 'api', [model])}` : ''}`}/>)}</div>
      <span className="chart-value">{isCost ? <CostValue row={row} unknownOnly={priceUnknown(row) && !row.priced_calls}/> : formatCompact(row.total_tokens)}
        {isCost && priceUnknown(row) && <small className="chart-warning" title={unknownCostTitle(row)}>{t("usage:priced", {percent: fixed(row.price_coverage_percent, 0)})}</small>}</span>
    </div>) : <EmptyState>{t("usage:noProjectDataInThisDateRange")}</EmptyState>}
  </div>;
}

const PROJECT_COLUMNS = [["usage:project"], ["usage:calls", 'calls'], ["common:fast", 'fast_calls'], ["common:input", 'input_tokens'], ["usage:cached", 'cached_input_tokens'], ["common:output", 'output_tokens'],
  ["usage:totalToken", 'total_tokens'], ["usage:apiEquivalent", 'api_usd_known'], ["usage:fastApiSurcharge", 'fast_surcharge_usd', FAST_TITLE], ["usage:priceCoverage", 'price_coverage_percent']];

export default function ProjectsPage() {
  const {rangeKey, range, queryString} = useDashboard();
  const query = useQuery({queryKey: ['projects', rangeKey], queryFn: ({signal}) => apiGet(`/api/projects?${queryString()}`, {signal})});
  const rows = query.data?.projects || EMPTY_ROWS;
  const [selected, setSelected] = useState(null);
  const [sort, setSort] = useState({field: 'api_usd_known', direction: 'descending'});
  const selectedKey = rows.some(row => row.key === selected) ? selected : rows[0]?.key || null;
  const detail = useQuery({queryKey: ['project-daily', rangeKey, selectedKey], enabled: Boolean(selectedKey),
    queryFn: ({signal}) => apiGet(`/api/projects/daily?${queryString({project: selectedKey})}`, {signal})});
  const loading = query.isPending;
  const detailLoading = loading || (Boolean(selectedKey) && detail.isPending);
  const sorted = useMemo(() => sortUsageRows(rows, sort), [rows, sort]);
  const detailRef = useRef(null), chartsRef = useRef(null);
  useSynchronizedCharts(chartsRef, rows);
  const select = key => { setSelected(key); scrollToDetail(detailRef); };
  return <><LoadingStatus loading={loading || detailLoading}/><section className="page" data-page="projects" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/>
    <section className="charts-grid project-summary-charts" ref={chartsRef}>
      {['total_tokens', 'api_usd_known'].map((metric, index) => <article key={metric} className="panel chart-panel"><div className="panel-heading"><div>
        <h2>{t(index ? "usage:projectApiEquivalentCost" : "usage:totalProjectUsage")}</h2>
      </div></div><ProjectChart rows={rows} metric={metric} selected={selectedKey} onSelect={select} loading={loading}/></article>)}
    </section>
    <section className="panel table-panel"><div className="panel-heading"><h2>{t("usage:projectSummary")}</h2></div><div className="table-wrap"><table>
      <SortableHead columns={PROJECT_COLUMNS} sort={sort} onSort={setSort}/><tbody id="projectTable">{loading ? <UsageTableSkeleton columns={PROJECT_COLUMNS.length}/> : sorted.map(row => <tr key={row.key} className={row.key === selectedKey ? 'selected' : ''} onClick={() => select(row.key)}>
        <td className="project-name"><button type="button" className="session-pick" aria-pressed={row.key === selectedKey}>{projectName(row)}</button><small title={row.path || ''}>{row.path || t("usage:projectPathUnavailable")}</small></td>
        <td>{formatNumber(row.calls)}</td><td>{formatNumber(row.fast_calls)}</td><td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.cached_input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td>
        <td>{formatNumber(row.total_tokens)}</td><td><CostValue row={row}/></td><td><CostValue row={row} kind="fast"/></td><td><Coverage value={row.price_coverage_percent}/></td>
      </tr>)}{!loading && !rows.length && <tr><td colSpan={10}><EmptyState>{t("common:noData")}</EmptyState></td></tr>}</tbody>
    </table></div></section>
    <section id="projectDetail" className="panel project-detail-panel" tabIndex={-1} ref={detailRef} aria-busy={loading || detail.isFetching}>
      <div className="panel-heading project-selector-heading"><div><h2 id="selectedProjectTitle">{detailLoading ? <UsageSkeleton className="usage-heading-skeleton"/> : detail.data ? t("usage:usageTrend", {name: projectName(detail.data.project)}) : t("usage:projectUsageTrend")}</h2>
        <small id="selectedProjectPath" className="path-label">{detailLoading ? <UsageSkeleton className="usage-line-skeleton"/> : detail.data?.project.path || (selectedKey ? t("usage:projectPathUnavailable") : '')}</small></div>
        <label>{t("usage:selectProject")}{loading ? <UsageSkeleton className="usage-field-skeleton"/> : <select id="projectSelect" value={selectedKey || ''} disabled={!rows.length} onChange={event => setSelected(event.target.value)}>
          {!rows.length && <option value="">{t("usage:selectAProjectFirst")}</option>}{rows.map(row => <option key={row.key} value={row.key}>{projectName(row)} — {formatCompact(row.total_tokens)}</option>)}
        </select>}</label>
      </div><ErrorNotice error={detail.error}/>
      {detailLoading || selectedKey ? <><TrendPair report={detail.data} nested prefix="project" loading={detailLoading}/><div className="table-wrap"><UsageTable rows={detail.data?.[range.grain] || EMPTY_ROWS} project loading={detailLoading}/></div></> : <EmptyState>{t("usage:selectAProjectFirst")}</EmptyState>}
    </section>
  </section></>;
}

