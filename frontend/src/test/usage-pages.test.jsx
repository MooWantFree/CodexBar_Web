import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, useLocation} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {DashboardProvider, useDashboard} from '../context/DashboardContext';
import {DailyPage, OverviewPage, ProjectsPage, SessionsPage, sessionMatches, sortUsageRows} from '../pages/UsagePages';
import {CostValue} from '../components/CostValue';

const total = {calls: 2, input_tokens: 100, uncached_input_tokens: 60, cached_input_tokens: 40, output_tokens: 20, reasoning_output_tokens: 5,
  total_tokens: 120, api_usd_known: 8, priced_calls: 2, unknown_price_calls: 0, price_coverage_percent: 100, fast_calls: 1, fast_tokens: 50,
  fast_surcharge_usd: 1, unknown_fast_price_calls: 0, credits_known: 3, unknown_credit_calls: 0, tier_coverage_percent: 100, inferred_price_calls: 1};
const day = {...total, key: '2026-10-01', models: [{...total, key: 'gpt-6-astra', model: 'gpt-6-astra', display_name: 'GPT 6 Astra'}]};
const hour = {...day, key: '2026-10-01T09:00:00+08:00', label: '10-01 09:00'};
const parent = {...total, key: 'parent', title: 'Parent session', title_generated: false, projects: ['Project A'], models: ['GPT 6 Astra'], last_activity: '2026-10-01T01:00:00Z', has_children: true};
const own = {...parent, has_children: false, depth: 0};
const child = {...total, key: 'child', title: 'Child session', title_generated: false, projects: ['Project B'], models: ['GPT 6 Astra'], last_activity: parent.last_activity, depth: 1};
const group = {...parent, members: [own, child]};
const config = {defaultStart: '2026-10-01', defaultEnd: '2026-10-01', timezone: 'Asia/Taipei'};
const json = data => ({ok: true, json: async () => data});

function Probe() {
  const location = useLocation(), dashboard = useDashboard();
  return <><output data-testid="url">{location.search}</output><button onClick={() => dashboard.setRange({start: '2026-09-01', grain: 'hourly'})}>Change range</button></>;
}
function mount(Page, route = '/sessions', dispatch) {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async url => {
    const parsed = new URL(url, 'http://localhost');
    calls.push(parsed);
    if (parsed.pathname === '/api/quota') return json({status: 'ready', windows: []});
    return json(await dispatch(parsed));
  }));
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><DashboardProvider config={config}><Page/><Probe/></DashboardProvider></MemoryRouter></QueryClientProvider>);
  return {calls, client};
}
function sessionDispatch(url) {
  if (url.pathname === '/api/sessions') return {sessions: [group], inferred_price_calls: 1};
  if (url.pathname === '/api/sessions/detail') {
    const selected = url.searchParams.get('session') === 'child' ? child : parent;
    return {session: selected, total, daily: [day], hourly: [hour], requests: [{...total, key: 'request-1', timestamp: '2026-10-01T01:00:00Z', model: 'GPT 6 Astra', service_tier: 'priority', price_snapshot: {source: 'bundled', inferred: false, price_date: '2026-10-01', observed_at: '2026-10-01T01:00:00Z'}}], request_count: 1, offset: 0};
  }
  throw new Error(`Unexpected endpoint ${url.pathname}`);
}

beforeEach(() => {
  document.body.dataset.timezone = 'Asia/Taipei';
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {configurable: true, value: vi.fn()});
});
afterEach(() => vi.unstubAllGlobals());

describe('React analytics pages', () => {
  it('renders all overview KPIs, model breakdown, unknown costs and model charts', async () => {
    mount(OverviewPage, '/overview', () => ({total: {...total, unknown_price_calls: 1, unknown_credit_calls: 1}, models: [{...day.models[0], unknown_price_calls: 1}], daily: [day], hourly: [hour]}));
    await screen.findByRole('heading', {name: 'Usage by model'});
    expect(document.querySelectorAll('.kpi-card')).toHaveLength(5);
    expect(document.getElementById('costKpi').textContent).toBe('$8.00');
    expect(document.getElementById('costKpi').closest('article').textContent).not.toContain('+ Unknown');
    expect(document.getElementById('costKpi').classList.contains('unknown-cost')).toBe(true);
    expect(document.getElementById('costKpi').title).toContain('unknown for 1 calls');
    expect(document.querySelector('#modelTable .unknown-cost').title).toContain('GPT 6 Astra');
    expect(document.getElementById('creditsKpi')).toBeNull();
    expect(screen.queryByText('Credits')).toBeNull();
    expect(document.querySelector('#modelTable .unknown-cost').textContent).toBe('$8.00');
    expect(document.querySelector('#tokenChart .model-segment').style.background).toBe('rgb(118, 85, 197)');
    expect(document.querySelector('#costChart .model-segment').getAttribute('title')).toContain('$8.00');
    expect(screen.queryByText(/calls use prices backfilled/)).toBeNull();
  });

  it('explains unknown API and Fast amounts in the daily ledger while leaving known zero costs unchanged', async () => {
    const partial = {...day, unknown_price_calls: 1, unknown_fast_price_calls: 1};
    const zero = {...day, key: '2026-10-02', api_usd_known: 0, fast_surcharge_usd: 0};
    mount(DailyPage, '/daily', () => ({total, daily: [partial, zero], hourly: [hour]}));
    await screen.findByText('2026-10-02');
    const rows = [...document.querySelectorAll('[data-page="daily"] tbody tr')];
    const unknown = rows.find(row => row.cells[0].textContent === partial.key).querySelectorAll('.cost-value');
    expect(unknown[0].textContent).toBe('$8.00');
    expect(unknown[0].classList.contains('unknown-cost')).toBe(true);
    expect(unknown[0].title).toContain('required Token rates');
    expect(unknown[1].textContent).toBe('$1.00');
    expect(unknown[1].classList.contains('unknown-cost')).toBe(true);
    expect(unknown[1].title).toContain('1 Fast calls');
    for (const amount of rows.find(row => row.cells[0].textContent === zero.key).querySelectorAll('.cost-value')) {
      expect(amount.textContent).toBe('$0.00');
      expect(amount.classList.contains('unknown-cost')).toBe(false);
      expect(amount.hasAttribute('title')).toBe(false);
    }
  });

  it('explains unpriced model calls in project totals, charts and the project ledger', async () => {
    const partial = {...day, unknown_price_calls: 1, unknown_fast_price_calls: 1,
      models: [{...day.models[0], unknown_price_calls: 1, unknown_fast_price_calls: 1}]};
    const project = {...partial, key: 'project-a', display_name: 'Project A', path: 'E:\\Code\\A'};
    mount(ProjectsPage, '/projects', url => url.pathname === '/api/projects' ? {projects: [project]} : {project, total: partial, daily: [partial], hourly: [hour]});
    await screen.findByRole('heading', {name: 'Project A · usage trend'});
    expect(document.querySelectorAll('#projectTable .unknown-cost')).toHaveLength(2);
    expect(document.querySelector('#projectTable .unknown-cost').title).toContain('GPT 6 Astra');
    expect(document.querySelector('#projectTotalCostChart .unknown-cost').title).toContain('unknown for 1 calls');
    expect(document.querySelector('#projectCostChart .unknown-cost').title).toContain('GPT 6 Astra');
    expect(document.querySelectorAll('#projectDetail table .unknown-cost')).toHaveLength(1);
  });

  it('explains unknown session amounts in the ranking, summary, request total and each affected request', async () => {
    const partial = {...total, unknown_price_calls: 1, unknown_fast_price_calls: 1};
    mount(SessionsPage, '/sessions', url => {
      const response = sessionDispatch(url);
      if (url.pathname === '/api/sessions') return {...response, sessions: [{...group, ...partial}]};
      return {...response, total: partial, requests: [
        {...response.requests[0], key: 'unknown', model: 'Unpriced model', model_id: 'unpriced-model', api_usd_known: 0, priced_calls: 0,
          unknown_price_calls: 1, fast_surcharge_usd: 0, unknown_fast_price_calls: 1},
        {...response.requests[0], key: 'known-zero', api_usd_known: 0, fast_surcharge_usd: 0, service_tier: 'standard'},
      ], request_count: 2};
    });
    await screen.findByRole('heading', {name: 'Parent session · Session total'});
    expect(document.querySelectorAll('#sessionTable .unknown-cost')).toHaveLength(2);
    expect(document.querySelectorAll('#sessionDetailSummary .unknown-cost')).toHaveLength(2);
    const requests = document.querySelectorAll('#requestTable tr');
    expect(requests[0].querySelectorAll('.unknown-cost')).toHaveLength(2);
    const unknown = requests[1].querySelectorAll('.cost-value');
    expect(unknown[0].textContent).toBe('Unknown');
    expect(unknown[0].title).toContain('Unpriced model');
    expect(unknown[1].textContent).toBe('Unknown');
    expect(unknown[1].title).toContain('Fast multiplier');
    expect(requests[1].querySelectorAll('.unknown-cost')).toHaveLength(2);
    expect(requests[2].querySelectorAll('.unknown-cost')).toHaveLength(0);
    expect([...requests[2].querySelectorAll('.cost-value')].map(amount => amount.textContent)).toEqual(['$0.00', '$0.00']);
  });

  it('explains an explicitly missing amount without marking a known zero as unknown', () => {
    const {container} = render(<><CostValue row={{api_usd_known: null}}/><CostValue row={{api_usd_known: 0, unknown_price_calls: 0}}/></>);
    const amounts = container.querySelectorAll('.cost-value');
    expect(amounts[0].textContent).toBe('Unknown');
    expect(amounts[0].title).toContain('Required pricing information is missing');
    expect(amounts[0].classList.contains('unknown-cost')).toBe(true);
    expect(amounts[1].textContent).toBe('$0.00');
    expect(amounts[1].hasAttribute('title')).toBe(false);
    expect(amounts[1].classList.contains('unknown-cost')).toBe(false);
  });

  it('keeps exact ranges, price basis and hourly grain in the CSV export', async () => {
    mount(DailyPage, '/daily?start=2026-10-01&end=2026-10-01&start_time=09:00&end_time=09:01&start_at=2026-10-01T09:00:12%2B08:00&end_at=2026-10-01T09:01:45%2B08:00&grain=hourly&price_mode=current', () => ({total, daily: [day], hourly: [hour]}));
    await screen.findByText('10-01 09:00');
    const url = new URL(screen.getByRole('link', {name: 'Export CSV'}).href);
    expect(url.searchParams.get('start_at')).toBe('2026-10-01T09:00:12+08:00');
    expect(url.searchParams.get('end_at')).toBe('2026-10-01T09:01:45+08:00');
    expect(url.searchParams.get('grain')).toBe('hourly');
    expect(url.searchParams.get('price_mode')).toBe('current');
  });

  it('selects projects through bars and preserves literal project names and paths', async () => {
    const projects = [{...total, key: 'a', display_name: '<img src=x>', path: 'E:\\Code\\<img src=x>', models: day.models}, {...total, key: 'b', display_name: 'Project B', path: 'E:\\Code\\B', models: day.models}];
    const {calls} = mount(ProjectsPage, '/projects', url => url.pathname === '/api/projects' ? {projects} : {
      project: projects.find(row => row.key === url.searchParams.get('project')), daily: [day], hourly: [hour], total,
    });
    await screen.findByRole('heading', {name: '<img src=x> · usage trend'});
    expect(document.querySelector('img')).toBeNull();
    await userEvent.click(within(document.getElementById('projectChart')).getByRole('button', {name: /Project B/}));
    await screen.findByRole('heading', {name: 'Project B · usage trend'});
    expect(calls.some(url => url.pathname === '/api/projects/daily' && url.searchParams.get('project') === 'b')).toBe(true);
    expect(document.getElementById('selectedProjectPath').textContent).toBe('E:\\Code\\B');
  });

  it('expands the session tree and requests child self scope without account quota readings', async () => {
    const {calls} = mount(SessionsPage, '/sessions', sessionDispatch);
    await screen.findByRole('heading', {name: 'Parent session · Session total'});
    await userEvent.click(screen.getByRole('button', {name: 'Expand usage for Parent session'}));
    expect(screen.getByRole('button', {name: 'Parent session (self)'})).toBeTruthy();
    await userEvent.click(screen.getByRole('button', {name: 'Child session'}));
    await screen.findByRole('heading', {name: 'Child session · Own usage'});
    expect(calls.some(url => url.pathname === '/api/sessions/detail' && url.searchParams.get('session') === 'child' && url.searchParams.get('scope') === 'self')).toBe(true);
    expect(calls.some(url => url.pathname.startsWith('/api/sessions/') && url.pathname.endsWith('/quota'))).toBe(false);
    const selectedUrl = new URLSearchParams(screen.getByTestId('url').textContent);
    expect(selectedUrl.get('session')).toBe('child');
    expect(selectedUrl.get('session_scope')).toBe('self');
    expect(document.getElementById('sessionQuotaPanel')).toBeNull();
  });

  it('sends request sorting and pagination to the server while retaining session scope', async () => {
    const {calls} = mount(SessionsPage, '/sessions?session=parent&session_scope=self', url => {
      const response = sessionDispatch(url);
      return url.pathname === '/api/sessions/detail' ? {...response, request_count: 101, offset: Number(url.searchParams.get('offset'))} : response;
    });
    await screen.findByRole('heading', {name: 'Parent session · Own usage'});
    const detail = document.getElementById('sessionDetail');
    await userEvent.click(within(detail).getByRole('button', {name: 'Input: sort ascending'}));
    await waitFor(() => expect(calls.some(url => url.pathname === '/api/sessions/detail' && url.searchParams.get('sort_by') === 'input_tokens' && url.searchParams.get('sort_direction') === 'ascending' && url.searchParams.get('offset') === '0')).toBe(true));
    const requestPager = document.getElementById('requestTable').closest('.table-wrap').nextElementSibling;
    await waitFor(() => expect(within(requestPager).getByRole('button', {name: 'Next'}).disabled).toBe(false));
    await userEvent.click(within(requestPager).getByRole('button', {name: 'Next'}));
    await waitFor(() => expect(calls.some(url => url.pathname === '/api/sessions/detail' && url.searchParams.get('sort_by') === 'input_tokens' && url.searchParams.get('offset') === '50' && url.searchParams.get('scope') === 'self')).toBe(true));
  });

  it('updates session usage when the date filter changes without requesting removed quota readings', async () => {
    const {calls} = mount(SessionsPage, '/sessions', sessionDispatch);
    await screen.findByRole('heading', {name: 'Parent session · Session total'});
    await userEvent.click(screen.getByText('Change range'));
    await waitFor(() => expect(calls.filter(url => url.pathname === '/api/sessions').length).toBe(2));
    expect(calls.some(url => url.pathname.startsWith('/api/sessions/') && url.pathname.endsWith('/quota'))).toBe(false);
    expect(document.getElementById('sessionQuotaPanel')).toBeNull();
  });

  it('preserves real titles that match the generated fallback and escapes user markup', async () => {
    const title = '会话 parent';
    const real = {...parent, title, has_children: false, title_generated: false, members: [{...own, title, title_generated: false}]};
    mount(SessionsPage, '/sessions', url => {
      const response = sessionDispatch(url);
      if (url.pathname === '/api/sessions') return {...response, sessions: [real]};
      if (url.pathname === '/api/sessions/detail') return {...response, session: {...real, title: '<script>alert(1)</script>'}};
      return response;
    });
    await screen.findByRole('button', {name: title});
    await screen.findByRole('heading', {name: '<script>alert(1)</script> · Own usage'});
    expect(document.querySelector('script')).toBeNull();
  });
});

describe('analytics ranking helpers', () => {
  it.each(['ascending', 'descending'])('keeps unpriced costs after known zero costs when sorting %s', direction => {
    const rows = [{key: 'unknown', api_usd_known: 0, unknown_price_calls: 1, priced_calls: 0}, {key: 'zero', api_usd_known: 0, priced_calls: 1}, {key: 'known', api_usd_known: 2, priced_calls: 1}];
    expect(sortUsageRows(rows, {field: 'api_usd_known', direction}).at(-1).key).toBe('unknown');
  });
  it('finds parent groups through child title, project, model and ID without changing display text', () => {
    expect(sessionMatches(group, 'child session')).toBe(true);
    expect(sessionMatches(group, 'project b')).toBe(true);
    expect(sessionMatches(group, 'GPT 6 ASTRA')).toBe(true);
    expect(sessionMatches(group, '  CHILD  ')).toBe(true);
    expect(sessionMatches(group, 'missing')).toBe(false);
  });
});

describe('session label metadata', () => {
  it('localizes generated model and project labels while preserving real and older backend labels', async () => {
    const known = {...parent, has_children: false, members: [own], models: ['未知模型'], projects: ['未知项目'],
      model_entries: [{key: 'unknown', display_name: '未知模型'}, {key: 'custom', display_name: '未知模型'}],
      project_entries: [{key: 'unknown', display_name: '未知项目', path: null}, {key: 'custom-project', display_name: '未知项目', path: 'E:\\Code\\未知项目'}]};
    mount(SessionsPage, '/sessions', url => {
      const response = sessionDispatch(url);
      if (url.pathname === '/api/sessions') return {...response, sessions: [known]};
      if (url.pathname === '/api/sessions/detail') return {...response, session: known, requests: [
        {...response.requests[0], key: 'generated', model: '未知模型', model_id: 'unknown'},
        {...response.requests[0], key: 'custom', model: '未知模型', model_id: 'custom-model'},
        {...response.requests[0], key: 'old-backend', model: '未知模型'},
      ], request_count: 3};
      return response;
    });
    await screen.findByRole('heading', {name: 'Parent session · Own usage'});
    const sessionRow = document.querySelector('#sessionTable tr');
    expect(sessionRow.cells[0].textContent).toContain('Unknown project · 未知项目');
    expect(sessionRow.cells[1].textContent).toBe('Unknown model · 未知模型');
    const requests = document.querySelectorAll('#requestTable tr');
    expect(requests[1].cells[1].textContent).toBe('Unknown model');
    expect(requests[2].cells[1].textContent).toBe('未知模型');
    expect(requests[3].cells[1].textContent).toBe('未知模型');
    await userEvent.type(screen.getByRole('searchbox'), 'Unknown model');
    expect(document.querySelector('#sessionTable tr').textContent).toContain('Parent session');
  });
});
