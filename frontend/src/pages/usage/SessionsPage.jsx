import {Fragment, useEffect, useMemo, useRef, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {useQuery} from '@tanstack/react-query';
import {useDashboard} from '../../context/DashboardContext';
import {apiGet} from '../../lib/api';
import {locale, t} from '../../lib/i18n';
import {formatNumber, money, formatDateTime, fastSurcharge, modelName} from '../../lib/format';
import {EmptyState, ErrorNotice, Pager} from '../../components/Shared';
import {PAGE_SIZE, EMPTY_ROWS, numeric, fixed, priceUnknown, cost, sessionTitle, projectName, sortUsageRows, SortableHead, SnapshotNotice, TrendPair, scrollToDetail, FAST_TITLE} from './UsageShared';

const sessionModels = row => Array.isArray(row.model_entries) ? row.model_entries.map(modelName) : row.models || [];
const sessionProjects = row => Array.isArray(row.project_entries) ? row.project_entries.map(projectName) : row.projects || [];

export function sessionMatches(row, search) {
  const query = search.trim().toLocaleLowerCase(locale);
  return [row, ...(row.members || [])].some(member =>
    [member.title, sessionTitle(member), member.key, ...(member.projects || []), ...(member.models || []), ...sessionProjects(member), ...sessionModels(member)].join(' ').toLocaleLowerCase(locale).includes(query));
}

function SessionRow({row, group, selection, expanded, onExpand, onSelect}) {
  const member = Boolean(group), ownParent = member && row.key === group.key;
  const scope = member ? 'self' : 'tree';
  const selected = selection?.key === row.key && selection.scope === scope;
  const title = ownParent ? t('{title}（本身）', {title: sessionTitle(row)}) : sessionTitle(row);
  const description = [sessionProjects(row).join(' · ')];
  if (member) description.push(t(ownParent ? '父会话自身用量' : '子会话自身用量'));
  else if (row.has_children) description.push(t('含自身及 {count} 个子会话', {count: formatNumber(row.members.length - 1)}));
  if (row.parent_unknown) description.push(t('子代理 · 归属未知'));
  const depth = member ? Math.max(1, Math.min(8, numeric(row.depth))) : 0;
  return <tr className={`${member ? 'session-member' : 'session-parent'}${selected ? ' selected' : ''}`}>
    <td><div className="session-name" style={{'--session-depth': depth}}>
      {!member && row.has_children ? <button type="button" className="session-expand" aria-expanded={expanded} data-session-expand={row.key}
        aria-label={t(expanded ? '收起{title}的会话用量' : '展开{title}的会话用量', {title: sessionTitle(row)})} onClick={() => onExpand(row.key)}><span aria-hidden="true">{expanded ? '⌄' : '>'}</span></button> : <span className="session-expand-spacer" aria-hidden="true"/>}
      <div><button type="button" className="session-pick" aria-pressed={selected} data-session={row.key} data-session-scope={scope} onClick={() => onSelect({key: row.key, scope})}>{title}</button><small>{description.filter(Boolean).join(' · ')}</small></div>
    </div></td><td>{sessionModels(row).join(' · ') || '—'}</td><td>{row.last_activity ? formatDateTime(row.last_activity, {hour12: false}) : '—'}</td>
    <td>{formatNumber(row.calls)}</td><td>{formatNumber(row.total_tokens)}</td><td>{formatNumber(row.fast_calls)}</td><td>{cost(row)}</td><td>{fastSurcharge(row)}</td>
  </tr>;
}

const SESSION_COLUMNS = [['会话 / 项目'], ['模型'], ['最后调用', 'last_activity'], ['调用', 'calls'], ['Token', 'total_tokens'], ['Fast', 'fast_calls'],
  ['API 等价', 'api_usd_known'], ['Fast API 加价', 'fast_surcharge_usd', FAST_TITLE]];
const REQUEST_COLUMNS = [['调用时间', 'timestamp'], ['模型'], ['档位', 'service_tier'], ['Input', 'input_tokens'], ['缓存', 'cached_input_tokens'], ['Output', 'output_tokens'],
  ['API 等价', 'api_usd_known'], ['Fast API 加价', 'fast_surcharge_usd', FAST_TITLE], ['保存的价格快照', 'price_snapshot']];

function SnapshotBadge({snapshot}) {
  const provenance = t(snapshot ? snapshot.inferred ? '首次采集回填' : '当时已保存价格' : '无快照');
  const source = {override: '手工覆盖', bundled: '内置价格', openai_docs: '官方文档缓存', models_dev: 'models.dev 缓存'}[snapshot?.source] || '保存的价格';
  const detail = snapshot ? t('{source}；价格日期 {date}；观察于 {observed}', {source: t(source), date: snapshot.price_date || '—', observed: formatDateTime(snapshot.observed_at, {hour12: false})}) : '';
  return <span title={detail} className={`coverage ${snapshot?.inferred ? 'partial' : ''}`}>{provenance}</span>;
}

function SessionDetail({selection, detailRef}) {
  const {rangeKey, queryString} = useDashboard();
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState({field: 'api_usd_known', direction: 'descending'});
  useEffect(() => { setPage(0); }, [rangeKey, selection?.key, selection?.scope]);
  const query = useQuery({queryKey: ['session-detail', rangeKey, selection?.key, selection?.scope, page, sort.field, sort.direction], enabled: Boolean(selection?.key),
    queryFn: ({signal}) => apiGet(`/api/sessions/detail?${queryString({session: selection.key, scope: selection.scope, offset: page * PAGE_SIZE, limit: PAGE_SIZE, sort_by: sort.field, sort_direction: sort.direction})}`, {signal})});
  const report = query.data, total = report?.total;
  const pages = Math.max(1, Math.ceil(numeric(report?.request_count) / PAGE_SIZE));
  const summary = total ? t('{calls} 次调用 · {tokens} Token · API 等价 {cost} · Fast API 加价 {fast} · 价格覆盖 {price}% · 档位覆盖 {tier}%', {
    calls: formatNumber(total.calls), tokens: formatNumber(total.total_tokens), cost: cost(total), fast: fastSurcharge(total), price: fixed(total.price_coverage_percent), tier: fixed(total.tier_coverage_percent),
  }) : t(query.isPending && selection ? '正在读取会话调用…' : '选择一个会话查看每次调用。');
  return <section id="sessionDetail" className="panel table-panel" ref={detailRef} tabIndex={-1} aria-busy={query.isFetching}>
    <div className="panel-heading"><div><p className="eyebrow">{t('会话明细标题')}</p><h2 id="sessionDetailTitle">{report ? t('{title} · {scope}', {title: sessionTitle(report.session), scope: t(selection.scope === 'tree' && report.session.has_children ? '会话合计' : '自身用量')}) : t('会话明细')}</h2><p id="sessionDetailSummary" className="fine-print">{summary}</p></div></div>
    <ErrorNotice error={query.error}/><TrendPair report={report} nested prefix="session"/>
    <div className="table-wrap request-table-wrap"><table><SortableHead columns={REQUEST_COLUMNS} sort={sort} onSort={next => { setSort(next); setPage(0); }}/><tbody id="requestTable">
      {total && <tr className="request-total"><td>{t('总计')}</td><td>—</td><td>—</td><td>{formatNumber(total.input_tokens)}</td><td>{formatNumber(total.cached_input_tokens)}</td><td>{formatNumber(total.output_tokens)}</td><td>{cost(total, true)}</td><td>{fastSurcharge(total, true)}</td><td>—</td></tr>}
      {(report?.requests || []).map(row => <tr key={row.key}><td>{formatDateTime(row.timestamp, {hour12: false})}</td><td>{Object.hasOwn(row, 'model_id') ? modelName({key: row.model_id, display_name: row.model}) : row.model}</td><td>{row.service_tier === 'priority' ? 'Fast' : row.service_tier === 'standard' ? 'Standard' : t('未知')}</td>
        <td>{formatNumber(row.input_tokens)}</td><td>{formatNumber(row.cached_input_tokens)}</td><td>{formatNumber(row.output_tokens)}</td><td>{priceUnknown(row) ? t('未知') : money(row.api_usd_known, true)}</td><td>{fastSurcharge(row, true)}</td><td><SnapshotBadge snapshot={row.price_snapshot}/></td>
      </tr>)}{!report?.requests?.length && <tr><td colSpan={9}><EmptyState>{t('暂无调用')}</EmptyState></td></tr>}
    </tbody></table></div><Pager page={page} pages={pages} onPage={setPage} disabled={query.isFetching || !report}/>
  </section>;
}

export default function SessionsPage() {
  const {rangeKey, queryString} = useDashboard();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selection, setSelection] = useState(() => searchParams.get('session') ? {key: searchParams.get('session'), scope: searchParams.get('session_scope') === 'self' ? 'self' : 'tree'} : null);
  const [expanded, setExpanded] = useState(new Set());
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState({field: 'api_usd_known', direction: 'descending'});
  const [page, setPage] = useState(0);
  const detailRef = useRef(null);
  const query = useQuery({queryKey: ['sessions', rangeKey], queryFn: ({signal}) => apiGet(`/api/sessions?${queryString()}`, {signal})});
  const sessions = query.data?.sessions || EMPTY_ROWS;
  const rows = useMemo(() => sortUsageRows(sessions.filter(row => sessionMatches(row, search)), sort), [sessions, search, sort, locale]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const saveSelection = next => {
    setSelection(next);
    setSearchParams(previous => {
      const values = new URLSearchParams(previous);
      if (next) { values.set('session', next.key); values.set('session_scope', next.scope); }
      else { values.delete('session'); values.delete('session_scope'); }
      return values;
    }, {replace: true});
  };
  useEffect(() => { setPage(0); }, [rangeKey, search, sort]);
  useEffect(() => {
    if (!query.data) return;
    const selectedGroup = sessions.find(row => selection?.scope === 'tree' ? row.key === selection.key : row.members?.some(member => member.key === selection?.key));
    const containingGroup = !selectedGroup && selection?.scope === 'tree' ? sessions.find(row => row.members?.some(member => member.key === selection.key)) : selectedGroup;
    if (!containingGroup && (selection || sessions.length)) saveSelection(sessions[0] ? {key: sessions[0].key, scope: 'tree'} : null);
    else if (!selectedGroup && containingGroup) saveSelection({key: selection.key, scope: 'self'});
    if (containingGroup && (selection?.scope === 'self' || !selectedGroup) && containingGroup.has_children) {
      setExpanded(previous => previous.has(containingGroup.key) ? previous : new Set([...previous, containingGroup.key]));
    }
  }, [query.data, sessions, selection]);
  useEffect(() => {
    const key = searchParams.get('session'), scope = searchParams.get('session_scope') === 'self' ? 'self' : 'tree';
    if (key && (key !== selection?.key || scope !== selection?.scope)) setSelection({key, scope});
  }, [searchParams]);
  const select = next => {
    saveSelection(next);
    scrollToDetail(detailRef);
  };
  const toggle = key => setExpanded(previous => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  const ranking = {api_usd_known: 'cost', total_tokens: 'tokens', fast_surcharge_usd: 'fast'}[sort.field] || '';
  return <section className="page" data-page="sessions" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/><SnapshotNotice inferred={query.data?.inferred_price_calls}/>
    <section className="panel table-panel"><div className="panel-heading session-heading"><div><p className="eyebrow">{t('会话排行')}</p><h2>{t('会话用量排行')}</h2>
      <small id="sessionCount" className="fine-print">{t('{count} 个会话 · 父会话汇总自身及所有子会话 · 用量均在当前筛选区间内', {count: formatNumber(rows.length)})}</small></div>
      <div className="session-tools"><label>{t('搜索会话')}<input id="sessionSearch" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder={t('标题、项目或会话 ID')}/></label>
        <label>{t('排序')}<select id="sessionSort" value={ranking} onChange={event => setSort({field: {cost: 'api_usd_known', tokens: 'total_tokens', fast: 'fast_surcharge_usd'}[event.target.value], direction: 'descending'})}>
          <option value="cost">{t('API 等价成本')}</option><option value="tokens">{t('总 Token')}</option><option value="fast">{t('Fast API 加价')}</option><option value="" disabled>{t('按表头排序')}</option>
        </select></label></div>
    </div><p className="fine-print">{t('已扫描的调用、Token 和价格快照保存在本地数据库；源日志被清空后仍可查看。新日志需要在清空前完成扫描。')}</p>
      <div className="table-wrap"><table><SortableHead columns={SESSION_COLUMNS} sort={sort} onSort={setSort}/><tbody id="sessionTable">
        {rows.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(row => <Fragment key={row.key}>
          <SessionRow row={row} selection={selection} expanded={expanded.has(row.key)} onExpand={toggle} onSelect={select}/>
          {row.has_children && expanded.has(row.key) && row.members.map(member => <SessionRow key={`${member.key}:self`} row={member} group={row} selection={selection} onSelect={select}/>)}</Fragment>)}
        {!rows.length && <tr><td colSpan={8}><EmptyState>{t(query.isPending ? '正在汇总用量…' : '当前范围没有匹配的会话。')}</EmptyState></td></tr>}
      </tbody></table></div><Pager page={currentPage} pages={pages} onPage={setPage}/>
    </section><SessionDetail selection={selection} detailRef={detailRef}/>
  </section>;
}
