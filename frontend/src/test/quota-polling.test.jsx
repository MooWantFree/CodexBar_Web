import {afterEach, describe, expect, it, vi} from 'vitest';
import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {DashboardProvider, useDashboard} from '../context/DashboardContext';
import {ResetsPage} from '../pages/QuotaPages';

const clients = [];
const config = {defaultStart: '2026-10-03', defaultEnd: '2026-10-03', timezone: 'Asia/Taipei'};
const snapshot = {
  status: 'ready', history_mode: 'verified', reset_history_scope: 'account-a',
  windows: [{remaining_percent: 2}], reset_records: [],
};
const json = data => ({ok: true, json: async () => data});

function Probe() {
  const dashboard = useDashboard();
  return <>
    <output data-testid="quota">{JSON.stringify(dashboard.quota)}</output>
    <output data-testid="loading">{String(dashboard.quotaLoading)}</output>
    <button onClick={() => dashboard.refreshQuota().catch(() => {})}>Manual refresh</button>
  </>;
}

function mount(children = <Probe />) {
  // Keep notification timers real so observable UI updates can use waitFor.
  vi.useFakeTimers({toFake: ['setInterval', 'clearInterval']});
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  clients.push(client);
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/resets']}>
    <DashboardProvider config={config}>{children}</DashboardProvider>
  </MemoryRouter></QueryClientProvider>);
}

async function poll() {
  await act(async () => { await vi.advanceTimersByTimeAsync(65_000); });
}

afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('automatic quota reads', () => {
  it('shows a confirmed early reset after two automatic reads without clicking refresh', async () => {
    const record = {
      limit_id: 'codex', window_minutes: 10080, method: 'early', confidence: 'confirmed',
      time_estimated: true, reset_at: '2026-10-02T21:14:00Z',
    };
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(snapshot))
      .mockResolvedValueOnce(json({...snapshot, windows: [{remaining_percent: 100}]}))
      .mockResolvedValue(json({...snapshot, windows: [{remaining_percent: 100}], reset_records: [record]}));
    vi.stubGlobal('fetch', fetch);
    mount(<ResetsPage />);
    await waitFor(() => expect(document.querySelector('#resetHistoryStatus').textContent).toContain('0 reset times'));
    await poll();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(document.querySelector('#resetHistoryStatus').textContent).toContain('0 reset times');
    await poll();
    await waitFor(() => expect(document.querySelector('#resetRecords').textContent).toContain('Early reset confirmed'));
    expect(document.querySelector('#resetRecords').textContent).toContain('05:14');
    expect(fetch.mock.calls.every(([url]) => url === '/api/quota')).toBe(true);
  });

  it('keeps the page usable during polling and recovers after a failed automatic read', async () => {
    let resolvePoll;
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(snapshot))
      .mockImplementationOnce(() => new Promise(resolve => { resolvePoll = resolve; }))
      .mockRejectedValueOnce(new Error('Network unavailable'))
      .mockResolvedValue(json({...snapshot, windows: [{remaining_percent: 100}]}));
    vi.stubGlobal('fetch', fetch);
    mount();
    await waitFor(() => expect(screen.getByTestId('quota').textContent).toContain('"status":"ready"'));
    await poll();
    expect(screen.getByTestId('loading').textContent).toBe('false');
    await act(async () => resolvePoll(json(snapshot)));
    await poll();
    await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent)).toMatchObject({
      status: 'error', windows: [], reset_history_scope: 'account-a', history_mode: 'offline',
    }));
    await poll();
    await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent)).toMatchObject({
      status: 'ready', windows: [{remaining_percent: 100}],
    }));
  });

  it('clears a failed manual refresh when a later automatic read succeeds', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(snapshot))
      .mockRejectedValueOnce(new Error('Manual read failed'))
      .mockResolvedValue(json({...snapshot, windows: [{remaining_percent: 100}]}));
    vi.stubGlobal('fetch', fetch);
    mount();
    await waitFor(() => expect(screen.getByTestId('quota').textContent).toContain('"status":"ready"'));
    fireEvent.click(screen.getByText('Manual refresh'));
    await waitFor(() => expect(screen.getByTestId('quota').textContent).toContain('Manual read failed'));
    await poll();
    await waitFor(() => expect(JSON.parse(screen.getByTestId('quota').textContent)).toMatchObject({
      status: 'ready', windows: [{remaining_percent: 100}],
    }));
  });
});
