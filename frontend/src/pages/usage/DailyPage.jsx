import {useDashboard} from '../../context/DashboardContext';
import {t} from '../../lib/i18n';
import {EmptyState, ErrorNotice, UsageTable} from '../../components/Shared';
import {useSummary, EMPTY_ROWS} from './UsageShared';

export default function DailyPage() {
  const {range, queryString} = useDashboard();
  const query = useSummary();
  return <section className="page" data-page="daily" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/>
    <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">{t('用量明细')}</p><h2>{t(range.grain === 'hourly' ? '每小时明细' : '每日明细')}</h2></div>
      <a id="exportLink" className="button ghost" href={`/api/export.csv?${queryString()}`}>{t('导出 CSV')}</a>
    </div>{query.isPending ? <EmptyState>{t('正在汇总用量…')}</EmptyState> : <div className="table-wrap tall-table"><UsageTable rows={query.data?.[range.grain] || EMPTY_ROWS}/></div>}</section>
  </section>;
}

