import React, { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
const dashboard = vi.hoisted(() => ({ current: null }));
vi.mock('../context/DashboardContext', () => ({ useDashboard: () => dashboard.current }));
let DateControls;
let todayInTimeZone;
const baseRange = { start: '2026-10-02', end: '2026-10-02', startTime: '00:00', endTime: '23:59', startAt: '', endAt: '', priceMode: 'snapshot', grain: 'daily' };
const exactRange = { ...baseRange, start: '2026-09-30', startTime: '18:23', endTime: '01:04', startAt: '2026-09-30T10:23:31Z', endAt: '2026-10-01T17:04:22Z' };
async function loadComponent(language = 'en-US') {
  vi.resetModules();
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue([language]);
  vi.spyOn(navigator, 'language', 'get').mockReturnValue(language);
  const module = await import('../components/DateControls');
  DateControls = module.default;
  todayInTimeZone = module.todayInTimeZone;
}
function mount(initialRange = baseRange, quota = {}) {
  const setRange = vi.fn();
  function Harness({ quota }) {
    const [range, updateRange] = useState(initialRange);
    dashboard.current = { range, quota, setRange: patch => { setRange(patch); updateRange(previous => ({ ...previous, ...patch })); } };
    return <DateControls />;
  }
  const view = render(<Harness quota={quota} />);
  return { ...view, setRange, rerenderQuota: next => view.rerender(<Harness quota={next} />) };
}
const day = value => document.querySelector(`button[data-date="${value}"]`);
const openPicker = () => fireEvent.click(screen.getByRole('button', { name: /^Select date range,/ }));
beforeEach(async () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-01T17:00:00Z'));
  Object.assign(document.body.dataset, { timezone: 'Asia/Taipei', minimumDate: '2026-08-01', maximumDate: '2026-10-02' });
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: vi.fn(function () { this.setAttribute('open', ''); }) });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: vi.fn(function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); }) });
  await loadComponent();
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('date controls', () => {
  it('uses report timezone and limits historical presets to the last recorded date', () => {
    expect(todayInTimeZone()).toBe('2026-10-02');
    document.body.dataset.maximumDate = '2026-10-01';
    const { setRange } = mount(exactRange);
    fireEvent.click(screen.getByRole('button', { name: 'Last 7 days' }));
    expect(setRange).toHaveBeenLastCalledWith({ start: '2026-09-25', end: '2026-10-01', startTime: '00:00', endTime: '23:59', startAt: '', endAt: '' });
    fireEvent.click(screen.getByRole('button', { name: 'All time' }));
    expect(setRange).toHaveBeenLastCalledWith({ start: '2026-08-01', end: '2026-10-01', startTime: '00:00', endTime: '23:59', startAt: '', endAt: '' });
    fireEvent.click(screen.getByRole('button', { name: 'Today' }));
    expect(setRange).toHaveBeenLastCalledWith(expect.objectContaining({ start: '2026-10-02', end: '2026-10-02' }));
    document.body.dataset.timezone = 'America/Los_Angeles';
    expect(todayInTimeZone()).toBe('2026-10-01');
  });
  it('shows exact seconds until a time edit switches to minute precision', () => {
    const { setRange } = mount(exactRange);
    expect(document.querySelector('#rangeStartLabel').textContent).toContain('18:23:31');
    expect(document.querySelector('#rangeEndLabel').textContent).toContain('01:04:22');
    openPicker();
    expect(screen.getByText('This range uses exact reset times. Editing the date or time switches to minute precision.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('End minute'), { target: { value: '05' } });
    expect(setRange).toHaveBeenLastCalledWith({ start: '2026-09-30', end: '2026-10-02', startTime: '18:23', endTime: '01:05', startAt: '', endAt: '' });
    expect(document.querySelector('#rangeEndLabel').textContent).toContain('01:05');
    expect(document.querySelector('#calendarPrecision')).toBeNull();
    expect(document.querySelector('#dateRangeDialog').open).toBe(true);
  });
  it('commits complete dates with chosen times and clears exact boundaries', () => {
    const { setRange } = mount({ ...exactRange, startTime: '09:15', endTime: '18:45', startAt: '', endAt: '' });
    openPicker(); fireEvent.click(day('2026-10-01'));
    expect(setRange).not.toHaveBeenCalled();
    fireEvent.click(day('2026-10-02'));
    expect(setRange).toHaveBeenLastCalledWith({ start: '2026-10-01', end: '2026-10-02', startTime: '09:15', endTime: '18:45', startAt: '', endAt: '' });
    expect(document.querySelector('#dateRangeDialog').open).toBe(false);
    expect(document.activeElement.id).toBe('dateRangeButton');
  });
  it('supports the same day and rejects reversed times without changing applied filters', () => {
    const { setRange } = mount({ ...baseRange, startTime: '09:15', endTime: '18:45' });
    openPicker(); fireEvent.click(day('2026-10-01')); fireEvent.click(day('2026-10-01'));
    expect(setRange).toHaveBeenLastCalledWith(expect.objectContaining({ start: '2026-10-01', end: '2026-10-01' }));
    openPicker(); setRange.mockClear();
    fireEvent.change(screen.getByLabelText('End hour'), { target: { value: '08' } });
    expect(setRange).not.toHaveBeenCalled();
    expect(screen.getByText('The end time cannot precede the start time. Adjust the date or time.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('End hour'), { target: { value: '10' } });
    expect(setRange).toHaveBeenLastCalledWith(expect.objectContaining({ endTime: '10:45' }));
  });
  it('restarts an incomplete range when an earlier end date is chosen', () => {
    const { setRange } = mount();
    openPicker(); fireEvent.click(day('2026-10-02')); fireEvent.click(day('2026-10-01'));
    expect(setRange).not.toHaveBeenCalled();
    expect(day('2026-10-01').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(day('2026-10-02'));
    expect(setRange).toHaveBeenCalledWith(expect.objectContaining({ start: '2026-10-01', end: '2026-10-02' }));
  });
  it('localizes reset highlights and future-date accessibility labels', async () => {
    await loadComponent('ja-JP');
    mount(baseRange, { reset_events: [{ date: '2026-10-01', window_minutes: 10080, limit_id: 'codex' }, { date: '2026-10-03', window_minutes: 10080, limit_id: 'codex' }] });
    fireEvent.click(screen.getByRole('button', { name: /^日付範囲を選択、/ }));
    const reset = day('2026-10-01');
    expect(reset.className).toContain('quota-reset-day');
    expect(reset.getAttribute('aria-label')).toContain('週間利用枠がリセット済み');
    expect(reset.getAttribute('aria-label')).toContain('2026年10月1日');
    expect(reset.title).toBe('週間利用枠がリセット済み');
    expect(day('2026-10-03').disabled).toBe(true);
    expect(day('2026-10-03').getAttribute('aria-label')).toContain('未来の日付は選択できません');
    expect(day('2026-10-03').className).not.toContain('quota-reset-day');
    expect(document.querySelector('#calendarMonth1').textContent).toBe('2026年10月');
  });
  it('highlights estimated history beside confirmed resets without treating an estimated time as an estimated event', () => {
    vi.setSystemTime(new Date('2026-10-03T02:00:00Z'));
    const estimated = { date: '2026-09-27', reset_at: '2026-09-27T05:16:11+08:00', window_minutes: 10080, limit_id: 'codex', method: 'estimated', confidence: 'estimated' };
    const confirmed = { date: '2026-10-03', reset_at: '2026-10-03T05:14:00+08:00', window_minutes: 10080, limit_id: 'codex', method: 'early', confidence: 'confirmed', time_estimated: true };
    mount(baseRange, { reset_records: [estimated, confirmed], reset_events: [confirmed] });
    openPicker();
    expect(day('2026-09-27').className).toContain('quota-reset-day');
    expect(day('2026-09-27').title).toBe('Weekly quota reset (estimated)');
    expect(day('2026-09-27').getAttribute('aria-label')).toContain('Weekly quota reset (estimated)');
    expect(day('2026-10-03').className).toContain('quota-reset-day');
    expect(day('2026-10-03').title).toBe('Weekly quota reset');
    expect(day('2026-10-03').getAttribute('aria-label')).not.toContain('(estimated)');
    expect(document.querySelector('.calendar-footer').textContent).toContain('including estimates');
  });
  it('keeps an explicitly empty record list from restoring stale legacy events', () => {
    mount(baseRange, {
      reset_records: [],
      reset_events: [{ date: '2026-09-27', window_minutes: 10080, limit_id: 'codex' }],
    });
    openPicker();
    expect(day('2026-09-27').className).not.toContain('quota-reset-day');
    expect(day('2026-09-27').getAttribute('title')).toBeNull();
  });
  it('continues highlighting legacy snapshots that only contain reset events', () => {
    mount(baseRange, { reset_events: [{ date: '2026-09-27', window_minutes: 300, limit_id: 'codex' }] });
    openPicker();
    expect(day('2026-09-27').className).toContain('quota-reset-day');
    expect(day('2026-09-27').title).toBe('5-hour quota reset');
  });
  it.each([
    ['Asia/Taipei', '2026-09-27', '2026-09-26'],
    ['America/Los_Angeles', '2026-09-26', '2026-09-27'],
  ])('uses the reset timestamp in %s instead of a previously stored date', (timezone, actualDate, staleDate) => {
    document.body.dataset.timezone = timezone;
    mount(baseRange, { reset_records: [{
      date: staleDate, reset_at: '2026-09-26T21:16:11Z', window_minutes: 10080,
      limit_id: 'codex', method: 'estimated', confidence: 'estimated',
    }] });
    openPicker();
    expect(day(actualDate).className).toContain('quota-reset-day');
    expect(day(staleDate).className).not.toContain('quota-reset-day');
  });
  it('falls back to valid record dates when timestamps are missing or invalid', () => {
    mount(baseRange, { reset_records: [
      { date: '2026-09-25', window_minutes: 10080, limit_id: 'codex', confidence: 'estimated' },
      { date: '2026-09-26', reset_at: 'invalid timestamp', window_minutes: 300, limit_id: 'codex', method: 'regular' },
      { date: '2026-09-31', reset_at: 'invalid timestamp', window_minutes: 10080, limit_id: 'codex' },
      { date: 'invalid date', window_minutes: 10080, limit_id: 'codex' },
    ] });
    openPicker();
    expect(day('2026-09-25').title).toBe('Weekly quota reset (estimated)');
    expect(day('2026-09-26').title).toBe('5-hour quota reset');
    expect(document.querySelectorAll('.quota-reset-day')).toHaveLength(2);
  });
  it('does not highlight future record timestamps even when their stored dates are in the past', () => {
    mount(baseRange, { reset_records: [{
      date: '2026-09-27', reset_at: '2026-10-03T05:14:00+08:00', window_minutes: 10080,
      limit_id: 'codex', method: 'early', confidence: 'confirmed',
    }] });
    openPicker();
    expect(day('2026-09-27').className).not.toContain('quota-reset-day');
    expect(day('2026-10-03').disabled).toBe(true);
    expect(day('2026-10-03').className).not.toContain('quota-reset-day');
    expect(document.querySelectorAll('.quota-reset-day')).toHaveLength(0);
  });
  it('updates an open calendar when automatic reads replace the record list', () => {
    const quota = { reset_records: [], reset_events: [] };
    const { rerenderQuota } = mount(baseRange, quota);
    openPicker();
    expect(day('2026-09-27').className).not.toContain('quota-reset-day');
    rerenderQuota({ ...quota, reset_records: [{
      date: '2026-09-27', reset_at: '2026-09-27T05:16:11+08:00', window_minutes: 10080,
      limit_id: 'codex', method: 'estimated', confidence: 'estimated',
    }] });
    expect(document.querySelector('#dateRangeDialog').open).toBe(true);
    expect(day('2026-09-27').title).toBe('Weekly quota reset (estimated)');
    expect(day('2026-09-27').className).toContain('quota-reset-day');
    rerenderQuota({ ...quota, reset_records: [] });
    expect(day('2026-09-27').className).not.toContain('quota-reset-day');
    expect(day('2026-09-27').getAttribute('title')).toBeNull();
  });
  it('localizes estimated record tooltips in Japanese', async () => {
    await loadComponent('ja-JP');
    mount(baseRange, { reset_records: [{
      date: '2026-09-27', window_minutes: 10080, limit_id: 'codex', method: 'estimated',
    }] });
    fireEvent.click(screen.getByRole('button', { name: /^日付範囲を選択、/ }));
    expect(day('2026-09-27').title).toBe('週間利用枠リセット（推定）');
    expect(day('2026-09-27').getAttribute('aria-label')).toContain('週間利用枠リセット（推定）');
  });
  it('moves keyboard focus between months and clamps forward navigation to today', () => {
    mount(); openPicker(); fireEvent.keyDown(day('2026-10-01'), { key: 'ArrowRight' });
    expect(document.activeElement.dataset.date).toBe('2026-10-02');
    fireEvent.keyDown(day('2026-10-02'), { key: 'ArrowRight' });
    expect(document.activeElement.dataset.date).toBe('2026-10-02');
    fireEvent.keyDown(day('2026-10-02'), { key: 'Home' });
    expect(document.activeElement.dataset.date).toBe('2026-09-27');
    fireEvent.keyDown(day('2026-09-27'), { key: 'PageUp' });
    expect(document.activeElement.dataset.date).toBe('2026-08-27');
    expect(document.querySelector('#calendarMonth0').textContent).toBe('August 2026');
  });
  it('resets only the draft and restores focus on cancel', () => {
    const { setRange } = mount(exactRange); openPicker();
    fireEvent.click(screen.getByRole('button', { name: 'Reset', exact: true }));
    expect(setRange).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Start hour').value).toBe('00');
    expect(screen.getByLabelText('End minute').value).toBe('59');
    fireEvent(document.querySelector('#dateRangeDialog'), new Event('cancel', { cancelable: true }));
    expect(document.querySelector('#dateRangeDialog').open).toBe(false);
    expect(document.activeElement.id).toBe('dateRangeButton');
    expect(document.querySelector('#rangeStartLabel').textContent).toContain('18:23:31');
  });
});
