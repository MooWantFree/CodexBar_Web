import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider, useQuery} from '@tanstack/react-query';
import App, {AnalysisControls} from '../App';
import {setLanguagePreference, useLocale} from '../lib/i18n';

const dashboard = vi.hoisted(() => ({current: null}));
vi.mock('../context/DashboardContext', () => ({useDashboard: () => dashboard.current}));
vi.mock('../components/DateControls', () => ({default: () => null}));
vi.mock('../pages/UsagePages', () => ({OverviewPage: () => null, DailyPage: () => null, ProjectsPage: () => null, SessionsPage: () => null}));
vi.mock('../pages/QuotaPages', () => ({QuotaSidebar: () => null, ResetsPage: () => null, QuotaValuePage: () => null}));
vi.mock('../pages/SettingsPage', () => ({default: () => null}));

const clients = [];
const originalHome = 'C:\\Users\\reporter\\.codex';
const note = () => document.querySelector('.price-basis-note');

function Controls() {
  useLocale();
  return <AnalysisControls />;
}

function mount(path = '/overview', {application = false, seed, extra = null} = {}) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false, staleTime: Infinity}}});
  clients.push(client);
  seed?.(client);
  const tree = () => <QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>
    {application ? <App /> : <><Controls />{extra}</>}
  </MemoryRouter></QueryClientProvider>;
  const view = render(tree());
  return {...view, client, rerenderDashboard: () => view.rerender(tree())};
}

beforeEach(() => {
  localStorage.clear();
  setLanguagePreference('en');
  dashboard.current = {
    codexHome: originalHome, queryString: () => '', scan: vi.fn().mockResolvedValue({}), scanning: false,
    range: {priceMode: 'snapshot', grain: 'daily'}, rangeKey: 'range-a', setRange: vi.fn(),
  };
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
  vi.unstubAllGlobals();
});

describe('application header and footer', () => {
  it('shows the full current log directory and follows configuration changes while keeping the footer directory', () => {
    const {rerenderDashboard} = mount('/settings', {application: true});
    const chip = document.querySelector('.log-directory-chip');
    expect(chip.querySelector('code').textContent).toBe(originalHome);
    expect(chip.title).toBe(originalHome);
    expect(chip.getAttribute('aria-label')).toBe(`Log directory：${originalHome}`);
    expect(document.querySelector('footer code').textContent).toBe(originalHome);
    expect(screen.queryByText('Local data')).toBeNull();
    expect(document.querySelector('footer').textContent).not.toContain('No message content stored');
    const selectedHome = 'E:\\Very long directory\\中文日志\\saved Codex source\\.codex';
    dashboard.current = {...dashboard.current, codexHome: selectedHome};
    rerenderDashboard();
    expect(chip.querySelector('code').textContent).toBe(selectedHome);
    expect(chip.title).toBe(selectedHome);
    expect(chip.getAttribute('aria-label')).toContain(selectedHome);
    expect(document.querySelector('footer code').textContent).toBe(selectedHome);
  });
});

describe('price basis hover explanations', () => {
  it.each([
    ['/overview', 'summary', {total: {inferred_price_calls: 7}}, 7],
    ['/daily', 'summary', {total: {inferred_price_calls: 8}}, 8],
    ['/projects', 'projects', {projects: [{inferred_price_calls: 2}, {inferred_price_calls: 3}]}, 5],
    ['/sessions', 'sessions', {inferred_price_calls: 11, sessions: [{inferred_price_calls: 50}]}, 11],
  ])('uses the existing %s report cache without fetching or adding a query observer', (path, key, report, count) => {
    const {client} = mount(path, {seed: cache => cache.setQueryData([key, 'range-a'], report)});
    expect(note().textContent).toBe('Saved price snapshots · Includes Fast API surcharge');
    expect(note().title).toContain(`${count} calls use prices backfilled at first collection`);
    expect(note().title).toContain('the official price at the time of the call cannot be confirmed');
    expect(screen.queryByText(/calls use prices backfilled/)).toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(client.getQueryCache().getAll().every(query => query.getObserversCount() === 0)).toBe(true);
  });

  it('keeps the snapshot explanation usable before a report exists', () => {
    const {client} = mount();
    expect(note().title).toContain('later price changes do not replace');
    expect(note().title).not.toContain('backfilled');
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('updates counts from cache writes and drops a previous range count immediately when filters change', () => {
    const {client, rerenderDashboard} = mount('/overview', {seed: cache => cache.setQueryData(['summary', 'range-a'], {total: {inferred_price_calls: 2}})});
    act(() => client.setQueryData(['summary', 'range-a'], {total: {inferred_price_calls: 4}}));
    expect(note().title).toContain('4 calls use prices backfilled');
    act(() => client.setQueryData(['summary', 'unrelated-range'], {total: {inferred_price_calls: 99}}));
    expect(note().title).toContain('4 calls use prices backfilled');
    dashboard.current = {...dashboard.current, rangeKey: 'range-b'};
    rerenderDashboard();
    expect(note().title).not.toContain('calls use prices backfilled');
    act(() => client.setQueryData(['summary', 'range-b'], {total: {inferred_price_calls: 6}}));
    expect(note().title).toContain('6 calls use prices backfilled');
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('does not interfere with the page query fetching and refreshing its report', async () => {
    const requestReport = vi.fn()
      .mockResolvedValueOnce({total: {inferred_price_calls: 9}})
      .mockResolvedValue({total: {inferred_price_calls: 12}});
    function LiveReport() {
      useQuery({queryKey: ['summary', 'range-a'], queryFn: requestReport, staleTime: 0});
      return null;
    }
    const {client} = mount('/overview', {extra: <LiveReport />});
    await waitFor(() => expect(note().title).toContain('9 calls use prices backfilled'));
    expect(requestReport).toHaveBeenCalledTimes(1);
    expect(client.getQueryCache().getAll()[0].getObserversCount()).toBe(1);
    await act(async () => { await client.invalidateQueries({queryKey: ['summary', 'range-a'], exact: true}); });
    expect(requestReport).toHaveBeenCalledTimes(2);
    expect(note().title).toContain('12 calls use prices backfilled');
  });

  it('explains current prices without snapshot backfill details', () => {
    dashboard.current = {...dashboard.current, range: {...dashboard.current.range, priceMode: 'current'}};
    mount('/sessions', {seed: cache => cache.setQueryData(['sessions', 'range-a'], {inferred_price_calls: 7})});
    expect(note().textContent).toBe('Recalculated at current prices · Includes Fast API surcharge');
    expect(note().title).toContain('current effective prices');
    expect(note().title).not.toContain('backfilled');
    expect(note().title).not.toContain('Snapshot estimate');
  });

  it('localizes the snapshot hover details when the interface switches to Japanese', () => {
    mount('/overview', {seed: cache => cache.setQueryData(['summary', 'range-a'], {total: {inferred_price_calls: 3}})});
    act(() => setLanguagePreference('ja'));
    expect(note().title).toContain('3 回の呼び出しは初回収集時の価格で補完されています');
    expect(note().title).toContain('呼び出し時点の公式価格は確認できません');
    expect(note().textContent).toBe('保存された価格スナップショットで推計 · Fast API追加料金を含む');
  });
});
