import {describe, expect, it, vi, afterEach} from 'vitest';
import {render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, useNavigate, useLocation} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {DashboardProvider, useDashboard} from '../context/DashboardContext';

afterEach(() => vi.unstubAllGlobals());
const config = {defaultStart: '2026-10-02', defaultEnd: '2026-10-02', timezone: 'Asia/Taipei'};
function Probe() {
  const dashboard = useDashboard();
  const navigate = useNavigate();
  const location = useLocation();
  return <><output data-testid="range">{JSON.stringify(dashboard.range)}</output><output data-testid="quota">{JSON.stringify(dashboard.quota || {})}</output><output data-testid="url">{location.search}</output>
    <button onClick={() => dashboard.setRange({priceMode: 'current', grain: 'hourly'})}>Filters</button>
    <button onClick={() => navigate(-1)}>Back</button>
    <button onClick={() => dashboard.refreshQuota().catch(() => {})}>Refresh</button>
    <button onClick={() => dashboard.scan().catch(() => {})}>Scan</button></>;
}
function mount(entries = ['/overview']) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={entries}><DashboardProvider config={config}><Probe /></DashboardProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
const json = data => ({ok: true, json: async () => data});
it('changes filters through the URL and preserves session selection and exact instants', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({status: 'ready', windows: []})));
  mount(['/overview?start=2026-10-01&end=2026-10-02&start_time=09:23&end_time=17:51&start_at=2026-10-01T09:23:45%2B08:00&end_at=2026-10-02T17:51:12%2B08:00&session=parent&session_scope=self']);
  await userEvent.click(screen.getByText('Filters'));
  const params = new URLSearchParams(screen.getByTestId('url').textContent);
  expect(params.get('session')).toBe('parent');
  expect(params.get('session_scope')).toBe('self');
  expect(params.get('grain')).toBe('hourly');
  expect(params.get('price_mode')).toBe('current');
  expect(params.get('start_at')).toBe('2026-10-01T09:23:45+08:00');
});
it('restores range modes on browser history navigation', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({status: 'ready', windows: []})));
  mount(['/overview?start=2026-09-20&grain=hourly&price_mode=current', '/daily?start=2026-10-01']);
  expect(JSON.parse(screen.getByTestId('range').textContent).start).toBe('2026-10-01');
  await userEvent.click(screen.getByText('Back'));
  expect(JSON.parse(screen.getByTestId('range').textContent)).toMatchObject({start: '2026-09-20', grain: 'hourly', priceMode: 'current'});
});
it('moves failed live refreshes to offline display, then changes account without retaining old percentages', async () => {
  const snapshot = {status: 'ready', reset_history_scope: 'account-a', windows: [{remaining_percent: 75}], fetched_at: '2026-10-01T02:00:00Z'};
  const fetch = vi.fn().mockResolvedValueOnce(json(snapshot)).mockRejectedValueOnce(new Error('Network failed')).mockResolvedValueOnce(json({status: 'ready', reset_history_scope: 'account-b', windows: [{remaining_percent: 10}]}));
  vi.stubGlobal('fetch', fetch);
  mount();
  await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent).status).toBe('ready'));
  await userEvent.click(screen.getByText('Refresh'));
  await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent)).toMatchObject({status: 'error', windows: [], history_mode: 'offline', reset_history_scope: 'account-a'}));
  await userEvent.click(screen.getByText('Refresh'));
  await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent)).toMatchObject({status: 'ready', reset_history_scope: 'account-b', windows: [{remaining_percent: 10}]}));
});
describe('scan invalidation', () => {
  it('invalidates cached reports while preserving the latest explicit quota snapshot', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json({status: 'ready', windows: []})));
    const client = mount();
    client.setQueryData(['summary', 'date-range'], {total: {calls: 3}});
    await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent).status).toBe('ready'));
    await userEvent.click(screen.getByText('Scan'));
    await waitFor(() => expect(client.getQueryState(['summary', 'date-range']).isInvalidated).toBe(true));
    expect(client.getQueryState(['quota']).isInvalidated).toBe(false);
  });
});
