import {t} from '../lib/i18n';

export function UsageSkeleton({className = '', style}) {
  return <span className={`usage-skeleton ${className}`} style={style} aria-hidden="true"/>;
}

export function LoadingStatus({loading, children}) {
  return <p className="sr-only" role="status">{loading ? children || t('正在读取…') : ''}</p>;
}

export function UsageTableSkeleton({columns, rows = 4}) {
  return <>{Array.from({length: rows}, (_, row) => <tr key={row} aria-hidden="true">
    {Array.from({length: columns}, (_, column) => <td key={column}>
      <UsageSkeleton className={column === 0 ? 'usage-model-name' : 'usage-table-value'}/>
    </td>)}
  </tr>)}</>;
}

export function AppSkeleton() {
  return <><LoadingStatus loading/><div aria-hidden="true">
    <aside className="sidebar"><div className="brand"><UsageSkeleton className="usage-bootstrap-brand"/></div>
      <div className="nav-list">{Array.from({length: 7}, (_, index) => <UsageSkeleton key={index} className="usage-bootstrap-nav"/>)}</div>
    </aside>
    <main className="app-main"><header className="topbar"><div><UsageSkeleton className="usage-heading-skeleton"/><UsageSkeleton className="usage-line-skeleton"/></div></header>
      <section className="panel control-panel"><UsageSkeleton className="usage-field-skeleton"/></section>
      <section className="kpi-grid">{Array.from({length: 5}, (_, index) => <article key={index} className="kpi-card">
        <p><UsageSkeleton className="usage-line-skeleton"/></p><strong><UsageSkeleton className="usage-kpi-value"/></strong><small><UsageSkeleton className="usage-kpi-detail"/></small>
      </article>)}</section>
      <section className="charts-grid">{[0, 1].map(index => <article key={index} className="panel chart-panel"><div className="panel-heading"><UsageSkeleton className="usage-heading-skeleton"/></div><div className="daily-chart"><UsageChartSkeleton/></div></article>)}</section>
      <section className="panel table-panel"><div className="panel-heading"><UsageSkeleton className="usage-heading-skeleton"/></div><div className="table-wrap"><table><tbody><UsageTableSkeleton columns={9}/></tbody></table></div></section>
    </main>
  </div></>;
}

export function UsageChartSkeleton() {
  return <>{[72, 48, 88, 60, 38, 78].map((width, index) => <div className="chart-row" key={index} aria-hidden="true">
    <span className="chart-date"><UsageSkeleton className="usage-chart-date"/></span>
    <div className="chart-track"><UsageSkeleton className="usage-chart-bar" style={{width: `${width}%`}}/></div>
    <span className="chart-value"><UsageSkeleton className="usage-chart-value"/></span>
  </div>)}</>;
}
