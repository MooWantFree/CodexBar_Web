import {Component, useCallback, useEffect, useRef, useState, useSyncExternalStore} from 'react';
import {Navigate, NavLink, Route, Routes, useLocation} from 'react-router-dom';
import {useQueryClient} from '@tanstack/react-query';
import {useDashboard} from './context/DashboardContext';
import {t, addMessages, useLocale} from './lib/i18n';
import {formatNumber} from './lib/format';
import DateControls from './components/DateControls';
import {ErrorNotice} from './components/Shared';
import {OverviewPage, DailyPage, ProjectsPage, SessionsPage} from './pages/UsagePages';
import {QuotaSidebar, ResetsPage, QuotaValuePage} from './pages/QuotaPages';
import SettingsPage from './pages/SettingsPage';

addMessages({
  en: {'日志目录': 'Log directory', '不保存消息正文 · 不上传数据 · 只监听本机': 'No message content stored · No uploads · Localhost only', '正在读取…': 'Loading…', '请求失败（{status}）': 'Request failed ({status})', '界面加载失败，请刷新页面重试。': 'The interface failed to load. Refresh the page to try again.', '刷新页面': 'Refresh page', '按调用时已保存的价格估算 · 已包含 Fast API 加价': 'Saved price snapshots · Includes Fast API surcharge', '按当前价格重算 · 已包含 Fast API 加价': 'Recalculated at current prices · Includes Fast API surcharge', '统计粒度': 'Aggregation', '主导航': 'Main navigation', '导航': 'Navigation', 'LOCAL ANALYTICS': 'LOCAL ANALYTICS', 'USAGE OVERVIEW': 'USAGE OVERVIEW', 'DAILY LEDGER': 'DAILY LEDGER', 'PROJECT USAGE': 'PROJECT USAGE', 'SESSION USAGE': 'SESSION USAGE', 'MODEL PRICING': 'MODEL PRICING', 'RESET HISTORY': 'RESET HISTORY', 'QUOTA VALUE': 'QUOTA VALUE'},
  ja: {'日志目录': 'ログディレクトリ', '不保存消息正文 · 不上传数据 · 只监听本机': 'メッセージ本文の保存なし · アップロードなし · ローカルのみ', '正在读取…': '読み込み中…', '请求失败（{status}）': 'リクエストに失敗しました（{status}）', '界面加载失败，请刷新页面重试。': '画面を読み込めませんでした。再読み込みしてください。', '刷新页面': '再読み込み', '按调用时已保存的价格估算 · 已包含 Fast API 加价': '保存された価格スナップショットで推計 · Fast API追加料金を含む', '按当前价格重算 · 已包含 Fast API 加价': '現在の価格で再計算 · Fast API追加料金を含む', '统计粒度': '集計単位', '主导航': 'メインナビゲーション', '导航': 'ナビゲーション', 'LOCAL ANALYTICS': 'ローカル分析', 'USAGE OVERVIEW': '使用量の概要', 'DAILY LEDGER': '日別明細', 'PROJECT USAGE': 'プロジェクト使用量', 'SESSION USAGE': 'セッション使用量', 'MODEL PRICING': 'モデル価格', 'RESET HISTORY': 'リセット履歴', 'QUOTA VALUE': 'クォータ相当額'},
});

addMessages({
  en: {
    '按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。': 'Calculated using saved price snapshots, which later price changes do not replace; API equivalent costs include the Fast API surcharge.',
    '按当前有效价格重算；API 等价已包含 Fast API 加价。': 'Recalculated using current effective prices; API equivalent costs include the Fast API surcharge.',
    '快照估算 · {count} 次调用使用首次采集价格回填': 'Snapshot estimate · {count} calls use prices backfilled at first collection',
    '首次采集回填属于估算，无法确认调用当时的官方价格。': 'Backfilled prices are estimates; the official price at the time of the call cannot be confirmed.',
  },
  ja: {
    '按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。': '保存済みの料金スナップショットで計算し、後からの料金変更では上書きしません。API 換算額には Fast API の追加料金を含みます。',
    '按当前有效价格重算；API 等价已包含 Fast API 加价。': '現在の有効な料金で再計算します。API 換算額には Fast API の追加料金を含みます。',
    '快照估算 · {count} 次调用使用首次采集价格回填': 'スナップショット推定 · {count} 回の呼び出しは初回収集時の価格で補完されています',
    '首次采集回填属于估算，无法确认调用当时的官方价格。': '初回収集時の補完価格は推定であり、呼び出し時点の公式価格は確認できません。',
  },
});

const routes = [
  {path: '/overview', title: '用量总览', eyebrow: 'USAGE OVERVIEW', subtitle: 'Token、模型与 API 等价成本概览。', icon: '◫', component: OverviewPage},
  {path: '/daily', title: '每日明细', eyebrow: 'DAILY LEDGER', subtitle: '逐日核对调用、Token 与等价成本。', icon: '≡', component: DailyPage},
  {path: '/projects', title: '项目用量', eyebrow: 'PROJECT USAGE', subtitle: '按 Git 项目查看总量与每日使用情况。', icon: '◇', component: ProjectsPage},
  {path: '/sessions', title: '会话用量', eyebrow: 'SESSION USAGE', subtitle: '查看会话排行、用量趋势与每次调用。', icon: '▤', component: SessionsPage},
  {path: '/resets', title: '重置日期', eyebrow: 'RESET HISTORY', subtitle: '查看重置时间，选择两个时刻统计期间用量。', icon: '↻', component: ResetsPage},
  {path: '/quota-value', title: '额度等价美元', eyebrow: 'QUOTA VALUE', subtitle: '从本周期已用额度，推算每 1% 和整窗额度的 API 等价美元。', icon: '≈', component: QuotaValuePage},
  {path: '/settings', title: '设置', eyebrow: 'SETTINGS', subtitle: '管理日志目录、界面语言和模型价格。', icon: '⚙', component: SettingsPage},
];

const inferredCount = value => Number.isFinite(Number(value)) && Number(value) > 0 ? Number(value) : 0;

export function AnalysisControls() {
  const {range, setRange, rangeKey} = useDashboard();
  const {pathname} = useLocation();
  const client = useQueryClient();
  const reportKey = pathname === '/projects' ? 'projects' : pathname === '/sessions' ? 'sessions' : 'summary';
  // Observe the page's existing cache without adding a query observer or request.
  const subscribe = useCallback(listener => client.getQueryCache().subscribe(event => {
    if (event.query?.queryKey[0] === reportKey && event.query?.queryKey[1] === rangeKey) listener();
  }), [client, reportKey, rangeKey]);
  const readCount = useCallback(() => {
    const report = client.getQueryData([reportKey, rangeKey]);
    return reportKey === 'projects'
      ? (report?.projects || []).reduce((sum, row) => sum + inferredCount(row.inferred_price_calls), 0)
      : inferredCount(reportKey === 'sessions' ? report?.inferred_price_calls : report?.total?.inferred_price_calls);
  }, [client, reportKey, rangeKey]);
  const inferred = useSyncExternalStore(subscribe, readCount, readCount);
  const currentPrices = range.priceMode === 'current';
  const tooltip = [t(currentPrices ? '按当前有效价格重算；API 等价已包含 Fast API 加价。' : '按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。'),
    !currentPrices && inferred > 0 && t('快照估算 · {count} 次调用使用首次采集价格回填', {count: formatNumber(inferred)}),
    !currentPrices && inferred > 0 && t('首次采集回填属于估算，无法确认调用当时的官方价格。'),
  ].filter(Boolean).join('\n');
  return <div className="analysis-controls"><p className="fine-print price-basis-note" title={tooltip}>{t(currentPrices ? '按当前价格重算 · 已包含 Fast API 加价' : '按调用时已保存的价格估算 · 已包含 Fast API 加价')}</p>
    <div className="analysis-options"><label className="price-mode-control"><span>{t('价格口径')}</span><select value={range.priceMode} onChange={event => setRange({priceMode: event.target.value})}><option value="snapshot">{t('快照估算')}</option><option value="current">{t('当前价格重算')}</option></select></label>
      <div className="grain-switch" role="group" aria-label={t('统计粒度')}>{['daily', 'hourly'].map(grain => <button key={grain} aria-pressed={range.grain === grain} onClick={() => setRange({grain})}>{t(grain === 'daily' ? '按天' : '按小时')}</button>)}</div>
    </div></div>;
}

export class PageErrorBoundary extends Component {
  state = {error: null};
  static getDerivedStateFromError(error) { return {error}; }
  componentDidCatch(error) { console.error(error); }
  render() {
    return this.state.error ? <section className="panel"><ErrorNotice error={t('界面加载失败，请刷新页面重试。')} /><button className="button" onClick={() => window.location.reload()}>{t('刷新页面')}</button></section> : this.props.children;
  }
}

export default function App() {
  const language = useLocale();
  const location = useLocation();
  const {queryString, scan, scanning, scanError, codexHome} = useDashboard();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef(null);
  const route = routes.find(item => item.path === (location.pathname === '/pricing' ? '/settings' : location.pathname)) || routes[0];
  useEffect(() => { document.title = `${t(route.title)} · Codex Token Report`; setMenuOpen(false); }, [route, location.pathname, language]);
  useEffect(() => {
    document.body.classList.toggle('menu-open', menuOpen);
    function escape(event) { if (event.key === 'Escape' && menuOpen) { setMenuOpen(false); menuButton.current?.focus(); } }
    document.addEventListener('keydown', escape);
    return () => { document.body.classList.remove('menu-open'); document.removeEventListener('keydown', escape); };
  }, [menuOpen]);
  const showRange = !['/settings', '/resets', '/quota-value'].includes(route.path);
  return <>
    <button ref={menuButton} className="menu-toggle" aria-label={t(menuOpen ? '关闭导航' : '打开导航')} aria-controls="sidebar" aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}>☰</button>
    <button className="sidebar-backdrop" hidden={!menuOpen} aria-label={t('关闭导航')} onClick={() => setMenuOpen(false)} />
    <aside id="sidebar" className="sidebar" aria-label={t('主导航')}><div className="brand"><span className="brand-mark">C</span><div><strong>Codex Report</strong><small>{t('LOCAL ANALYTICS')}</small></div></div>
      <nav className="nav-list" aria-label={t('导航')}>{routes.map(item => <div className="nav-item" key={item.path}>{item.path === '/settings' && <div className="nav-divider" role="separator" />}<NavLink to={`${item.path}?${queryString()}`}><span aria-hidden="true">{item.icon}</span>{t(item.title)}</NavLink></div>)}</nav><div className="sidebar-foot"><QuotaSidebar /></div></aside>
    <main className="app-main"><header className="topbar"><div><p className="eyebrow">{t(route.eyebrow)}</p><h1>{t(route.title)}</h1><p className="subtitle">{t(route.subtitle)}</p></div><div className="header-actions"><span className="log-directory-chip" title={codexHome} aria-label={`${t('日志目录')}：${codexHome}`}><span className="dot" /><span className="log-directory-label">{t('日志目录')}</span><code>{codexHome}</code></span>{route.path !== '/resets' && <button className="button primary" disabled={scanning} onClick={() => scan().catch(() => {})}>{t(scanning ? '扫描中…' : '扫描新日志')}</button>}</div></header>
      {showRange && <section className="control-panel panel"><DateControls key={location.key} /><AnalysisControls /></section>}<ErrorNotice error={scanError} />
      <PageErrorBoundary key={route.path}><Routes><Route path="/" element={<Navigate to={`/overview${location.search}`} replace />} /><Route path="/pricing" element={<Navigate to={`/settings${location.search}`} replace />} />{routes.map(item => <Route key={item.path} path={item.path} element={<item.component />} />)}<Route path="*" element={<Navigate to={`/overview${location.search}`} replace />} /></Routes></PageErrorBoundary>
    </main>
  </>;
}
