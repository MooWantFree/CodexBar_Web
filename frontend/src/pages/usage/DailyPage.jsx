import {useDashboard} from '../../context/DashboardContext';
import {t} from '../../lib/i18n';
import {ErrorNotice, UsageTable} from '../../components/Shared';
import {LoadingStatus} from '../../components/UsageSkeleton';
import {useSummary, EMPTY_ROWS} from './UsageShared';

export default function DailyPage() {
  const {range, queryString} = useDashboard();
  const query = useSummary();
  const loading = query.isPending;
  return <><LoadingStatus loading={loading}/><section className="page" data-page="daily" aria-busy={query.isFetching}>
    <ErrorNotice error={query.error}/>
    <section className="panel table-panel"><div className="panel-heading"><div><p className="eyebrow">{t('用量明细')}</p><h2>{t(range.grain === 'hourly' ? '每小时明细' : '每日明细')}</h2></div>
      <a id="exportLink" className="button ghost" href={`/api/export.csv?${queryString()}`}>{t('导出 CSV')}</a>
    </div><div className="table-wrap tall-table"><UsageTable rows={query.data?.[range.grain] || EMPTY_ROWS} loading={loading}/></div></section>
  </section></>;
}

