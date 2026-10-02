import {useMemo, useRef, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useDashboard} from '../../context/DashboardContext';
import {apiGet} from '../../lib/api';
import {t} from '../../lib/i18n';
import {formatNumber, formatCompact, money, fastSurcharge, modelColor, modelName} from '../../lib/format';
import {EmptyState, ErrorNotice, UsageTable} from '../../components/Shared';
import {EMPTY_ROWS, numeric, fixed, cost, priceUnknown, projectName, sortUsageRows, SortableHead, Coverage, SnapshotNotice, TrendPair, useSynchronizedCharts, scrollToDetail, FAST_TITLE} from './UsageShared';

function ProjectChart({rows, metric, selected, onSelect}) {
  const max = Math.max(...rows.map(row => numeric(row[metric])), Number.EPSILON);
  const isCost = metric === 'api_usd_known';
  return <div id={isCost ? 'projectTotalCostChart' : 'projectChart'} className="daily-chart project-chart" tabIndex={0}
    aria-label={t(isCost ? '项目 API 等价成本，按 Token 用量排序' : '项目 Token 用量')}>
    {rows.length ? rows.map(row => <div key={row.key} className={`chart-row ${selected === row.key ? 'selected' : ''}`}
      role="button" tabIndex={0} aria-controls="projectDetail" aria-pressed={selected === row.key} title={row.path || t('无法识别项目路径')}
      onClick={() => onSelect(row.key)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(row.key); } }}>
      <span className="project-label">{projectName(row)}</span><div className="chart-track">{(row.models || []).filter(model => model[metric]).map(model => <span key={model.model || model.key} className="segment model-segment"
        style={{width: `${model[metric] / max * 100}%`, background: modelColor(model.model || model.key)}}
        title={`${modelName(model)}\n${isCost ? money(model[metric], true) : `${formatNumber(model[metric])} Token`}${isCost ? `\n${t('定价覆盖 {percent}% 调用', {percent: fixed(model.price_coverage_percent)})}` : ''}`}/>)}</div>
      <span className="chart-value">{isCost ? priceUnknown(row) && !row.priced_calls ? t('未知') : money(row.api_usd_known, true) : formatCompact(row.total_tokens)}
        {isCost && priceUnknown(row) && <small className="chart-warning">{t('定价 {percent}%', {percent: fixed(row.price_coverage_percent, 0)})}</small>}</span>
    </div>) : <EmptyState>{t('这个日期范围还没有项目数据。')}</EmptyState>}
  </div>;
}

const PROJECT_COLUMNS = [['项目'], ['调用', 'calls'], ['Fast', 'fast_calls'], ['Input', 'input_tokens'], ['缓存', 'cached_input_tokens'], ['Output', 'output_tokens'],
  ['总 Token', 'total_tokens'], ['API 等价', 'api_usd_known'], ['Fast API 加价', 'fast_surcharge_usd', FAST_TITLE], ['价格覆盖', 'price_coverage_percent']];

export default function ProjectsPage() {
  const {rangeKey, range, queryString} = useDashboard();
  const query = useQuery({queryKey: ['projects', rangeKey], queryFn: ({signal}) => apiGet(`/api/projects?${queryString()}`, {signal})});
  const rows = query.data?.projects || EMPTY_ROWS;
  const [selected, setSelected] = useState(null);
  const [sort, setSort] = useState({field: 'api_usd_known', direction: 'descending'});
  const selectedKey = rows.some(row => row.key === selected) ? selected : rows[0]?.key || null;
  const detail = useQuery({queryKey: ['project-daily', rangeKey, selectedKey], enabled: Boolean(selectedKey),
    queryFn: ({signal}) => apiGet(`/api/projects/daily?${queryString({project: selectedKey})}`, {signal})});
  const sorted = useMemo(() => sortUsageRows(rows, sort), [rows, sort]);
  const detailRef = useRef(null), chartsRef = useRef(null);
  useSynchronizedCharts(chartsRef, rows);
  const select = key => { setSelected(key); scrollToDetail(detailRef); };
  return <section className="page" data-page="projects" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/><SnapshotNotice inferred={rows.reduce((sum, row) => sum + numeric(row.inferred_price_calls), 0)}/>
    <section className="charts-grid project-summary-charts" ref={chartsRef}>
      {['total_tokens', 'api_usd_known'].map((metric, index) => <article key={metric} className="panel chart-panel"><div className="panel-heading"><div>
        <p className="eyebrow">{t(index ? '项目成本' : '项目总量')}</p><h2>{t(index ? '项目 API 等价成本' : '项目总使用量')}</h2>
      </div></div>{query.isPending ? <EmptyState>{t('正在读取项目统计…')}</EmptyState> : <ProjectChart rows={rows} metric={metric} selected={selectedKey} onSelect={select}/>}</article>)}
    </section>
    <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">{t('项目明细')}</p><h2>{t('项目汇总')}</h2></div></div><div className="table-wrap"><table>
      <SortableHead columns={PROJECT_COLUMNS} sort={sort} onSort={setSort}/><tbody id="projectTable">{sorted.map(row => <tr key={row.key} className={row.key === selectedKey ? 'selected' : ''} onClick={() => select(row.key)}>
        <td className="project-name"><button type="button" className="session-pick" aria-pressed={row.key === selectedKey}>{projectName(row)}</button><small title={row.path || ''}>{row.path || t('无法识别项目路径')}</small></td>
        <td>{formatNumber(row.calls)}</td><td>{formatNumber(row.fast_calls)}</td><td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.cached_input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td>
        <td>{formatNumber(row.total_tokens)}</td><td>{cost(row)}</td><td>{fastSurcharge(row)}</td><td><Coverage value={row.price_coverage_percent}/></td>
      </tr>)}{!rows.length && <tr><td colSpan={10}><EmptyState>{t('暂无数据')}</EmptyState></td></tr>}</tbody>
    </table></div></section>
    <section id="projectDetail" className="panel project-detail-panel" tabIndex={-1} ref={detailRef} aria-busy={detail.isFetching}>
      <div className="panel-heading project-selector-heading"><div><p className="eyebrow">{t('项目趋势')}</p><h2 id="selectedProjectTitle">{detail.data ? t('{name} · 用量趋势', {name: projectName(detail.data.project)}) : t('项目用量趋势')}</h2>
        <small id="selectedProjectPath" className="path-label">{detail.data?.project.path || (selectedKey ? t('无法识别项目路径') : '')}</small></div>
        <label>{t('选择项目')}<select id="projectSelect" value={selectedKey || ''} disabled={!rows.length} onChange={event => setSelected(event.target.value)}>
          {!rows.length && <option value="">{t('请先选择项目')}</option>}{rows.map(row => <option key={row.key} value={row.key}>{projectName(row)} — {formatCompact(row.total_tokens)}</option>)}
        </select></label>
      </div><ErrorNotice error={detail.error}/>
      {detail.isPending && selectedKey ? <EmptyState>{t('正在读取项目趋势…')}</EmptyState> : selectedKey ? <><TrendPair report={detail.data} nested prefix="project"/><div className="table-wrap"><UsageTable rows={detail.data?.[range.grain] || EMPTY_ROWS} project/></div></> : <EmptyState>{t('请先选择项目')}</EmptyState>}
    </section>
  </section>;
}

