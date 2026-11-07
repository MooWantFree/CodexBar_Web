import wireMessages from '../../locales/backend-messages.json';
import {useEffect, useRef} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useDashboard} from '../../context/DashboardContext';
import {apiGet} from '../../lib/api';
import {t} from '../../lib/i18n';
import {money} from '../../lib/format';
import {StackedChart} from '../../components/Shared';
import {UsageChartSkeleton} from '../../components/UsageSkeleton';

export const PAGE_SIZE = 50;
export const EMPTY_ROWS = [];
export const numeric = value => Number(value || 0);
export const fixed = (value, digits = 1) => numeric(value).toFixed(digits);
export const priceUnknown = row => row.unknown_price_calls > 0;
export const cost = (row, precise = false) => money(row.api_usd_known, precise);
export const projectName = row => !row.path && row.display_name === wireMessages.legacyLabels.unknownProject ? t("usage:unknownProject") : row.display_name || row.key;
export const sessionTitle = row => row.title_generated
  ? t("usage:session", {id: String(row.key).slice(0, 12)}) : row.title || row.key;

function sortValue(row, field) {
  if (['timestamp', 'last_activity', 'key'].includes(field)) return Date.parse(row[field]);
  if (field === 'api_usd_known' && priceUnknown(row) && !row.priced_calls) return null;
  if (field === 'credits_known' && row.unknown_credit_calls) return null;
  if (field === 'fast_surcharge_usd' && row.unknown_fast_price_calls && !row.fast_surcharge_usd) return null;
  return row[field] == null ? null : Number(row[field]);
}

export function sortUsageRows(rows, sort) {
  return [...rows].sort((left, right) => {
    const a = sortValue(left, sort.field), b = sortValue(right, sort.field);
    const missingA = a === null || !Number.isFinite(a), missingB = b === null || !Number.isFinite(b);
    return Number(missingA) - Number(missingB)
      || (missingA ? 0 : (a - b) * (sort.direction === 'ascending' ? 1 : -1));
  });
}

export function SortableHead({columns, sort, onSort}) {
  return <thead><tr>{columns.map(([label, field, title], index) => {
    const active = sort.field === field;
    const direction = active && sort.direction === 'ascending' ? 'descending' : 'ascending';
    return <th key={`${label}-${index}`} scope="col" title={title && t(title)} aria-sort={field ? active ? sort.direction : 'none' : undefined}>
      {field ? <button type="button" className="table-sort"
        aria-label={t("usage:sortAccessibleLabel", {label: t(label), direction: t(direction === 'ascending' ? "usage:ascending" : "usage:descending")})}
        onClick={() => onSort({field, direction})}>{t(label)}<span className="sort-indicator" aria-hidden="true">{active ? sort.direction === 'ascending' ? '↑' : '↓' : '↕'}</span></button> : t(label)}
    </th>;
  })}</tr></thead>;
}

export function Coverage({value}) {
  return <span className={`coverage ${numeric(value) === 100 ? '' : 'partial'}`}>{fixed(value)}%</span>;
}

export function useSynchronizedCharts(ref, rows) {
  useEffect(() => {
    const charts = ref.current?.querySelectorAll('.daily-chart');
    if (!charts || charts.length !== 2) return;
    const [first, second] = charts;
    first.scrollTop = second.scrollTop = 0;
    let active = null, timer;
    const claim = source => {
      active = source;
      clearTimeout(timer);
      timer = setTimeout(() => { active = null; }, 200);
    };
    const unbind = [];
    for (const [source, target] of [[first, second], [second, first]]) {
      const start = () => claim(source);
      const scroll = () => {
        if (active && active !== source) return;
        claim(source);
        if (target.scrollTop !== source.scrollTop) target.scrollTop = source.scrollTop;
      };
      for (const event of ['wheel', 'pointerdown', 'touchstart', 'keydown']) {
        source.addEventListener(event, start, {passive: true});
        unbind.push(() => source.removeEventListener(event, start));
      }
      source.addEventListener('scroll', scroll, {passive: true});
      unbind.push(() => source.removeEventListener('scroll', scroll));
    }
    return () => { clearTimeout(timer); unbind.forEach(remove => remove()); };
  }, [ref, rows]);
}

export function TrendPair({report, nested = false, prefix = '', loading = false}) {
  const {range} = useDashboard();
  const rows = report?.[range.grain] || EMPTY_ROWS;
  const ref = useRef(null);
  useSynchronizedCharts(ref, rows);
  const grain = t(range.grain === 'hourly' ? "usage:hourly" : "usage:daily");
  return <section ref={ref} className={`charts-grid ${nested ? 'nested-charts' : ''}`}>
    {['total_tokens', 'api_usd_known'].map((metric, index) => {
      const title = t(index === 0 ? "usage:tokenByModel" : "usage:apiEquivalentUsdByModel", {grain});
      return <article key={metric} className={nested ? undefined : 'panel chart-panel'}>
        {nested ? <h3>{title}</h3> : <div className="panel-heading"><h2>{title}</h2></div>}
        <div id={prefix ? `${prefix}${index ? 'CostChart' : 'TokenChart'}` : index ? 'costChart' : 'tokenChart'} className={`daily-chart ${range.grain === 'hourly' ? 'hourly-chart' : ''}`}>
          {loading ? <UsageChartSkeleton/> : <StackedChart rows={rows} metric={metric}/>}
        </div>
      </article>;
    })}
  </section>;
}

export function useSummary() {
  const {rangeKey, queryString} = useDashboard();
  return useQuery({queryKey: ['summary', rangeKey], queryFn: ({signal}) => apiGet(`/api/summary?${queryString()}`, {signal})});
}

export const FAST_TITLE = "usage:fastSurchargeDescription";
export const MODEL_COLUMNS = [["usage:model"], ["usage:calls", 'calls'], ["common:fast", 'fast_calls'], ["common:input", 'input_tokens'], ["usage:cached", 'cached_input_tokens'],
  ["common:output", 'output_tokens'], ["usage:apiEquivalent", 'api_usd_known'], ["usage:fastApiSurcharge", 'fast_surcharge_usd', FAST_TITLE],
  ["usage:tierCoverage", 'tier_coverage_percent']];

export function scrollToDetail(ref) {
  ref.current?.focus({preventScroll: true});
  ref.current?.scrollIntoView({behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start'});
}

