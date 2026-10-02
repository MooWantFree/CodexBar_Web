import {afterEach, describe, expect, it, vi} from 'vitest';
import {readRange, rangeQuery} from '../lib/range';
import {apiGet, apiPut, apiPost, apiDelete} from '../lib/api';
import {offlineQuota} from '../context/DashboardContext';
import {systemMessage} from '../lib/systemMessages';

afterEach(() => vi.unstubAllGlobals());
const config = {defaultStart: '2026-10-02', defaultEnd: '2026-10-02', timezone: 'Asia/Taipei'};

describe('report filters', () => {
  it('round trips precise reset instants without discarding seconds or UTC offset', () => {
    const range = readRange(new URLSearchParams('start=2026-10-01&end=2026-10-02&start_time=09:23&end_time=17:51&start_at=2026-10-01T09:23:45%2B08:00&end_at=2026-10-02T17:51:12%2B08:00&grain=hourly&price_mode=current'), config);
    expect(readRange(new URLSearchParams(rangeQuery(range)), config)).toEqual(range);
    expect(new URLSearchParams(rangeQuery(range, {scope: 'self'})).get('scope')).toBe('self');
    expect(range.startAt).toBe('2026-10-01T09:23:45+08:00');
  });
  it('normalizes unsupported modes and ignores incomplete exact bounds', () => {
    const range = readRange(new URLSearchParams('grain=invalid&price_mode=invalid&start_time=99:99&start_at=2026-10-02T00:00:00Z'), config);
    expect(range).toMatchObject({grain: 'daily', priceMode: 'snapshot', startTime: '00:00'});
    expect(new URLSearchParams(rangeQuery(range)).has('start_at')).toBe(false);
  });
  it('discards stale precise timestamps after date or clock URL changes', () => {
    const range = readRange(new URLSearchParams('start=2026-10-01&end=2026-10-02&start_time=09:24&end_time=17:51&start_at=2026-10-01T09:23:45%2B08:00&end_at=2026-10-02T17:51:12%2B08:00'), config);
    expect(range.startAt).toBe('');
    expect(range.endAt).toBe('');
  });
  it('normalizes invalid/future dates and reversed times without sending invalid bounds', () => {
    const range = readRange(new URLSearchParams('start=2026-02-31&end=2027-01-01&start_time=18:00&end_time=09:00'), config);
    expect(range).toMatchObject({start: '2026-10-02', end: '2026-10-02', startTime: '00:00', endTime: '23:59'});
  });
});

describe('API client', () => {
  it('translates known server errors and preserves unknown diagnostics', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: false, status: 400, json: async () => ({detail: '开始时间不能晚于结束时间'})}));
    await expect(apiGet('/api/summary')).rejects.toThrow(systemMessage('开始时间不能晚于结束时间'));
    expect(systemMessage('用户创建的中文标题')).toBe('用户创建的中文标题');
    expect(systemMessage('gpt-test: 模型缺少价格')).toContain('gpt-test:');
    expect(systemMessage('gpt-test: 模型缺少价格')).not.toContain('模型缺少价格');
  });
  it('sends the correct verbs and JSON payload for price/scan operations', async () => {
    const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({updated: true})});
    vi.stubGlobal('fetch', fetch);
    await apiPut('/api/pricing/models/a/override', {input: 1});
    await apiDelete('/api/pricing/models/a/override');
    await apiPost('/api/scan');
    expect(fetch.mock.calls.map(([, init]) => init.method)).toEqual(['PUT', 'DELETE', 'POST']);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({input: 1});
  });
});

describe('offline quota presentation', () => {
  it('hides cached live percentages on a failed refresh while retaining archive scope', () => {
    const snapshot = {status: 'ready', reset_history_scope: 'account-a', fetched_at: '2026-10-02T00:00:00Z', windows: [{remaining_percent: 75}]};
    const quota = offlineQuota(snapshot, new Error('Network failed'));
    expect(quota).toMatchObject({status: 'error', history_mode: 'offline', reset_history_scope: 'account-a', windows: [], history_fetched_at: snapshot.fetched_at});
    expect(snapshot.windows).toHaveLength(1);
  });
  it('retains the legacy account provenance warning after network failure', () => {
    const snapshot = {reset_history_scope: 'legacy', history_directory_verified: false, history_label: '旧版本本地账号档案（日志目录归属未确认）'};
    expect(offlineQuota(snapshot, new Error('Failed')).history_label).toBe(snapshot.history_label);
  });
});
