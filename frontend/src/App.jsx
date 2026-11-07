import {Component, useCallback, useEffect, useRef, useState, useSyncExternalStore} from 'react';
import {Navigate, NavLink, Route, Routes, useLocation} from 'react-router-dom';
import {useQueryClient} from '@tanstack/react-query';
import {useDashboard} from './context/DashboardContext';
import {t, useLocale} from "./lib/i18n";
import DateControls from './components/DateControls';
import {ErrorNotice} from './components/Shared';
import {UsageSkeleton} from './components/UsageSkeleton';
import {OverviewPage, DailyPage, ProjectsPage, SessionsPage} from './pages/UsagePages';
import {QuotaSidebar, ResetsPage, QuotaValuePage} from './pages/QuotaPages';
import SettingsPage from './pages/SettingsPage';

const routes = [
  {path: '/overview', title: "common:usageOverview", icon: '◫', component: OverviewPage},
  {path: '/daily', title: "usage:dailyLedger", icon: '≡', component: DailyPage},
  {path: '/projects', title: "common:projectUsage", icon: '◇', component: ProjectsPage},
  {path: '/sessions', title: "common:sessionUsage", icon: '▤', component: SessionsPage},
  {path: '/resets', title: "common:resetHistory", icon: '↻', component: ResetsPage},
  {path: '/quota-value', title: "common:quotaValueInUsd", icon: '≈', component: QuotaValuePage},
  {path: '/settings', title: "settings:settings", icon: '⚙', component: SettingsPage},
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
  const tooltip = [t(currentPrices ? "common:currentPriceDescription" : "common:snapshotPriceDescription"),
    !currentPrices && inferred > 0 && t("common:backfilledCalls", {count: inferred}),
    !currentPrices && inferred > 0 && t("common:backfillWarning"),
  ].filter(Boolean).join('\n');
  return <div className="analysis-controls"><p className="fine-print price-basis-note" title={tooltip}>{t("common:includesFastApiSurcharge")}</p>
    <div className="analysis-options"><label className="price-mode-control"><span>{t("common:pricingBasis")}</span><select value={range.priceMode} onChange={event => setRange({priceMode: event.target.value})}><option value="snapshot">{t("common:savedPriceEstimate")}</option><option value="current">{t("common:recalculateAtCurrentPrices")}</option></select></label>
      <div className="grain-switch" role="group" aria-label={t("common:aggregation")}>{['daily', 'hourly'].map(grain => <button key={grain} aria-pressed={range.grain === grain} onClick={() => setRange({grain})}>{t(grain === 'daily' ? "common:daily" : "common:hourly")}</button>)}</div>
    </div></div>;
}

export class PageErrorBoundary extends Component {
  state = {error: null};
  static getDerivedStateFromError(error) { return {error}; }
  componentDidCatch(error) { console.error(error); }
  render() {
    return this.state.error ? <section className="panel"><ErrorNotice error={t("common:interfaceLoadError")} /><button className="button" onClick={() => window.location.reload()}>{t("common:refreshPage")}</button></section> : this.props.children;
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
    <button ref={menuButton} className="menu-toggle" aria-label={t(menuOpen ? "common:closeNavigation" : "common:openNavigation")} aria-controls="sidebar" aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}>☰</button>
    <button className="sidebar-backdrop" hidden={!menuOpen} aria-label={t("common:closeNavigation")} onClick={() => setMenuOpen(false)} />
    <aside id="sidebar" className="sidebar" aria-label={t("common:mainNavigation")}><div className="brand"><img className="brand-mark" src={`${import.meta.env.BASE_URL}logo.svg`} width="34" height="34" alt="" /><strong>Codex Report</strong></div>
      <nav className="nav-list" aria-label={t("common:navigation")}>{routes.map(item => <div className="nav-item" key={item.path}>{item.path === '/settings' && <div className="nav-divider" role="separator" />}<NavLink to={`${item.path}?${queryString()}`}><span aria-hidden="true">{item.icon}</span>{t(item.title)}</NavLink></div>)}</nav><div className="sidebar-foot"><QuotaSidebar /></div></aside>
    <main className="app-main"><header className="topbar"><div><h1>{t(route.title)}</h1></div><div className="header-actions"><span className="log-directory-chip" title={codexHome} aria-label={`${t("common:logDirectory")}：${codexHome}`}><span className="dot" /><span className="log-directory-label">{t("common:logDirectory")}</span><code>{codexHome}</code></span>{route.path !== '/resets' && <button className="button primary" disabled={scanning} onClick={() => scan().catch(() => {})}>{t(scanning ? "common:scanning" : "common:scanNewLogs")}{scanning && <UsageSkeleton className="usage-inline-skeleton"/>}</button>}</div></header>
      {showRange && <section className="control-panel panel"><DateControls key={location.key} /><AnalysisControls /></section>}<ErrorNotice error={scanError} />
      <PageErrorBoundary key={route.path}><Routes><Route path="/" element={<Navigate to={`/overview${location.search}`} replace />} /><Route path="/pricing" element={<Navigate to={`/settings${location.search}`} replace />} />{routes.map(item => <Route key={item.path} path={item.path} element={<item.component />} />)}<Route path="*" element={<Navigate to={`/overview${location.search}`} replace />} /></Routes></PageErrorBoundary>
    </main>
  </>;
}
