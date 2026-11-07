import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useDashboard } from '../context/DashboardContext';
import {locale, t} from "../lib/i18n";

const pad = value => String(value).padStart(2, '0');
const iso = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const timeZone = () => document.body.dataset.timezone || undefined;

export function parseDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
  const date = new Date(`${value}T12:00:00`);
  return !Number.isNaN(date.getTime()) && iso(date) === value ? date : null;
}

export function todayInTimeZone() {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timeZone(), year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function localFields(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return null;
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: timeZone(), hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return { date: `${values.year}-${values.month}-${values.day}`, time: `${values.hour}:${values.minute}`, clock: `${values.hour}:${values.minute}:${values.second}` };
}

function displayDate(value) {
  const date = parseDate(value);
  return date ? date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' }) : t("dates:selectADate");
}

function copyRange(range) {
  return { start: parseDate(range.start) ? range.start : '', end: parseDate(range.end) ? range.end : '',
    startTime: range.startTime || '00:00', endTime: range.endTime || '23:59',
    startAt: range.startAt || '', endAt: range.endAt || '' };
}

function TimeControl({ side, value, onChange }) {
  const [hour, minute] = value.split(':');
  const labels = side === 'start'
    ? {time: 'dates:startTime', hour: 'dates:startHour', minute: 'dates:startMinute'}
    : {time: 'dates:endTime', hour: 'dates:endHour', minute: 'dates:endMinute'};
  return <div className="calendar-time"><span>{t(labels.time)}</span><div>
    <select id={`calendar${side === 'start' ? 'Start' : 'End'}Hour`} aria-label={t(labels.hour)} value={hour}
      onChange={event => onChange(`${event.target.value}:${minute}`)}>
      {Array.from({ length: 24 }, (_, value) => <option key={value} value={pad(value)}>{pad(value)}</option>)}
    </select><span aria-hidden="true">:</span>
    <select id={`calendar${side === 'start' ? 'Start' : 'End'}Minute`} aria-label={t(labels.minute)} value={minute}
      onChange={event => onChange(`${hour}:${event.target.value}`)}>
      {Array.from({ length: 60 }, (_, value) => <option key={value} value={pad(value)}>{pad(value)}</option>)}
    </select>
  </div></div>;
}

export default function DateControls() {
  const { range, setRange, quota } = useDashboard();
  const today = todayInTimeZone();
  const anchor = parseDate(today);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(() => copyRange(range));
  const [phase, setPhase] = useState('start');
  const [hoverDate, setHoverDate] = useState(null);
  const [focusedDate, setFocusedDate] = useState(null);
  const [month, setMonth] = useState(() => new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1, 12));
  const dialogRef = useRef(null);
  const triggerRef = useRef(null);
  const startRef = useRef(null);
  const monthsRef = useRef(null);
  const wasOpen = useRef(false);

  const resetDates = useMemo(() => {
    const dates = new Map();
    const records = Array.isArray(quota?.reset_records) ? quota.reset_records : quota?.reset_events || [];
    for (const event of records) {
      const date = localFields(event.reset_at)?.date || event.date;
      if (!parseDate(date) || date > today) continue;
      const minutes = Number(event.window_minutes);
      if (!Number.isFinite(minutes) || minutes <= 0) continue;
      const window = minutes === 10080 ? t("dates:weeklyQuota") : minutes % 60 === 0
        ? t("dates:hourQuota", { hours: minutes / 60 }) : t("dates:minuteQuota", { minutes });
      const label = event.limit_id === 'codex' ? window : `${event.limit_name || event.limit_id} · ${window}`;
      const labels = dates.get(date) || new Set();
      const estimated = event.confidence === 'estimated' || event.method === 'estimated';
      labels.add(t(estimated ? "dates:resetEstimated" : "dates:windowReset", { window: label }));
      dates.set(date, labels);
    }
    return dates;
  }, [quota?.reset_records, quota?.reset_events, today, locale]);

  const exactStart = localFields(range.startAt);
  const exactEnd = localFields(range.endAt);
  const exact = Boolean(exactStart && exactEnd && exactStart.date === range.start && exactEnd.date === range.end
    && exactStart.time === range.startTime && exactEnd.time === range.endTime
    && new Date(range.startAt) < new Date(range.endAt));
  const startLabel = `${displayDate(range.start)} ${exact ? exactStart.clock : range.startTime}`;
  const endLabel = `${displayDate(range.end)} ${exact ? exactEnd.clock : range.endTime}`;
  const invalid = Boolean(draft.start && draft.end && `${draft.start}T${draft.startTime}` > `${draft.end}T${draft.endTime}`);
  const hint = invalid ? t("dates:invalidRange")
    : t(phase === 'start' ? "dates:selectStartDate" : "dates:selectEndDate");

  function position() {
    const dialog = dialogRef.current;
    const trigger = triggerRef.current;
    if (!dialog?.open || !trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = dialog.offsetWidth;
    const height = dialog.offsetHeight;
    dialog.style.left = `${Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12))}px`;
    dialog.style.top = `${rect.bottom + height + 20 <= window.innerHeight ? rect.bottom + 8
      : Math.max(12, Math.min(rect.top - height - 8, window.innerHeight - height - 12))}px`;
  }

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (open) {
      if (!dialog.open) dialog.showModal();
      position();
      if (!wasOpen.current) startRef.current?.focus();
    } else if (dialog.open) dialog.close();
    wasOpen.current = open;
  }, [open, month, draft]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener('resize', position);
    return () => window.removeEventListener('resize', position);
  }, [open]);

  useLayoutEffect(() => {
    if (open && focusedDate) monthsRef.current?.querySelector(`[data-date="${focusedDate}"]`)?.focus();
  }, [open, month, focusedDate]);

  function openPicker() {
    setDraft(copyRange(range));
    setPhase('start');
    setHoverDate(null);
    setFocusedDate(null);
    setMonth(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1, 12));
    setOpen(true);
  }

  function closePicker() {
    setOpen(false);
    if (open) triggerRef.current?.focus();
  }

  function commit() {
    if (!draft.start || !draft.end || invalid) return;
    setRange(draft);
    closePicker();
  }

  function select(value) {
    if (!parseDate(value) || value > today) return;
    setFocusedDate(value);
    setHoverDate(null);
    if (phase === 'start' || !draft.start || value < draft.start) {
      setDraft({ ...draft, start: value, end: '', startAt: '', endAt: '' });
      setPhase('end');
    } else {
      setDraft({ ...draft, end: value, startAt: '', endAt: '' });
      setPhase('start');
    }
  }

  function changeTime(side, value) {
    setDraft({ ...draft, [`${side}Time`]: value, startAt: '', endAt: '' });
  }

  function moveMonth(amount) {
    const next = new Date(month.getFullYear(), month.getMonth() + amount, 1, 12);
    if (iso(next) > today) return;
    setMonth(next);
    setHoverDate(null);
    setFocusedDate(null);
  }

  function onDayKey(event, value) {
    const date = parseDate(value);
    const offsets = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7,
      Home: -date.getDay(), End: 6 - date.getDay() };
    if (Object.hasOwn(offsets, event.key)) date.setDate(date.getDate() + offsets[event.key]);
    else if (event.key === 'PageUp' || event.key === 'PageDown') {
      const currentDay = date.getDate();
      date.setDate(1);
      date.setMonth(date.getMonth() + (event.key === 'PageUp' ? -1 : 1));
      date.setDate(Math.min(currentDay, new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()));
    } else return;
    event.preventDefault();
    const nextValue = iso(date) > today ? today : iso(date);
    if (!monthsRef.current?.querySelector(`[data-date="${nextValue}"]`)) {
      const target = parseDate(nextValue);
      setMonth(new Date(target.getFullYear(), target.getMonth(), 1, 12));
    }
    setFocusedDate(nextValue);
    if (phase === 'end') setHoverDate(nextValue);
  }

  function presetRange(days) {
    if (days === 1) return { start: today, end: today };
    const maximum = document.body.dataset.maximumDate;
    const end = parseDate(maximum) && maximum < today ? maximum : today;
    if (days === 'all') return { start: document.body.dataset.minimumDate || end, end };
    const start = parseDate(end);
    start.setDate(start.getDate() - Number(days) + 1);
    return { start: iso(start), end };
  }

  const weekdays = Array.from({ length: 7 }, (_, index) =>
    new Date(2024, 0, 7 + index, 12).toLocaleDateString(locale, { weekday: 'short' }));
  const visibleMonths = [0, 1].map(offset => {
    const first = new Date(month.getFullYear(), month.getMonth() + offset, 1, 12);
    const count = new Date(first.getFullYear(), first.getMonth() + 1, 0, 12).getDate();
    return { first, days: Array.from({ length: 42 }, (_, index) => {
      const day = index - first.getDay() + 1;
      return day < 1 || day > count ? null : new Date(first.getFullYear(), first.getMonth(), day, 12);
    }) };
  });
  const allDates = visibleMonths.flatMap(({ days }) => days.filter(Boolean).map(iso)).filter(value => value <= today);
  const tabDate = [focusedDate, draft.start].find(value => allDates.includes(value)) || allDates[0];
  const previewEnd = phase === 'end' && hoverDate >= draft.start ? hoverDate : draft.end;
  let matchedPreset = false;

  return <div id="dateControls">
    <div className="date-toolbar">
      <div className="presets" aria-label={t("dates:dateShortcuts")}>
        {[[1, "dates:today"], [7, "dates:last7Days"], [30, "dates:last30Days"], [90, "dates:last90Days"], ['all', "dates:allTime"]].map(([days, label]) => {
          const preset = presetRange(days);
          const active = !matchedPreset && range.startTime === '00:00' && range.endTime === '23:59'
            && !range.startAt && !range.endAt && range.start === preset.start && range.end === preset.end;
          matchedPreset ||= active;
          return <button type="button" key={days} className={`preset${active ? ' active' : ''}`} data-days={days}
            aria-pressed={active} onClick={() => { setRange({ ...preset, startTime: '00:00', endTime: '23:59', startAt: '', endAt: '' }); closePicker(); }}>{t(label)}</button>;
        })}
      </div>
      <div id="dateRangePicker" className="date-range-picker">
        <button type="button" id="dateRangeButton" ref={triggerRef} className="date-range-button" aria-haspopup="dialog"
          aria-controls="dateRangeDialog" aria-expanded={open} aria-label={t("dates:rangeAccessibleLabel", { start: startLabel, end: endLabel })}
          onClick={openPicker}>
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M7 3v4M17 3v4M3 11h18" /></svg>
          <span className="date-range-value"><small>{t("dates:startTime")}</small><strong id="rangeStartLabel">{startLabel}</strong></span>
          <span className="date-range-arrow" aria-hidden="true">→</span>
          <span className="date-range-value"><small>{t("dates:endTime")}</small><strong id="rangeEndLabel">{endLabel}</strong></span>
          <span className="date-range-chevron" aria-hidden="true">⌄</span>
        </button>
        <dialog id="dateRangeDialog" ref={dialogRef} className="date-range-dialog" aria-labelledby="calendarTitle" aria-describedby="calendarHint"
          onCancel={event => { event.preventDefault(); closePicker(); }} onClose={() => { setOpen(false); triggerRef.current?.focus(); }}
          onClick={event => {
            if (event.target !== event.currentTarget) return;
            const rect = event.currentTarget.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closePicker();
          }}>
          <div className="calendar-heading"><h2 id="calendarTitle">{t("dates:selectDateRange")}</h2><div>
            <button type="button" id="calendarReset" className="button ghost" onClick={() => {
              setDraft({ start: '', end: '', startTime: '00:00', endTime: '23:59', startAt: '', endAt: '' }); setPhase('start'); setHoverDate(null); setFocusedDate(null);
            }}>{t("dates:reset")}</button>
            <button type="button" id="calendarClose" className="calendar-icon-button" aria-label={t("dates:closeCalendar")} onClick={closePicker}>×</button>
          </div></div>
          <div className="calendar-selection">
            <button type="button" id="calendarStart" ref={startRef} className={`calendar-selection-button${phase === 'start' ? ' active' : ''}`}
              onClick={() => setPhase('start')}><small>{t("dates:startDate")}</small><strong>{displayDate(draft.start)}</strong></button>
            <span aria-hidden="true">→</span>
            <button type="button" id="calendarEnd" className={`calendar-selection-button${phase === 'end' ? ' active' : ''}`}
              onClick={() => setPhase(draft.start ? 'end' : 'start')}><small>{t("dates:endDate")}</small><strong>{displayDate(draft.end)}</strong></button>
          </div>
          <div className="calendar-times"><TimeControl side="start" value={draft.startTime} onChange={value => changeTime('start', value)} />
            <span aria-hidden="true">→</span><TimeControl side="end" value={draft.endTime} onChange={value => changeTime('end', value)} /></div>
          <div className="calendar-navigation"><button type="button" id="calendarPrevious" className="calendar-icon-button" aria-label={t("dates:previousMonth")} onClick={() => moveMonth(-1)}>‹</button>
            <p id="calendarHint" className={invalid ? 'error-text' : undefined} aria-live="polite">{hint}</p>
            <button type="button" id="calendarNext" className="calendar-icon-button" aria-label={t("dates:nextMonth")}
              disabled={iso(new Date(month.getFullYear(), month.getMonth() + 1, 1, 12)) > today} onClick={() => moveMonth(1)}>›</button></div>
          <div id="calendarMonths" ref={monthsRef} className="calendar-months" onPointerLeave={() => setHoverDate(null)}>
            {visibleMonths.map(({ first, days }, offset) => <section key={iso(first)} className="calendar-month" aria-labelledby={`calendarMonth${offset}`}>
              <h3 id={`calendarMonth${offset}`}>{first.toLocaleDateString(locale, { year: 'numeric', month: 'long' })}</h3>
              <div className="calendar-weekdays" aria-hidden="true">{weekdays.map((day, index) => <span key={index}>{day}</span>)}</div>
              <div className="calendar-days">{days.map((date, index) => {
                if (!date) return <div key={`empty-${index}`} className="calendar-cell empty" aria-hidden="true" />;
                const value = iso(date);
                const disabled = value > today;
                const reset = resetDates.get(value);
                const resetLabel = reset ? Array.from(reset).join(' · ') : '';
                const isStart = value === draft.start;
                const isEnd = value === previewEnd;
                const classes = ['calendar-cell', draft.start && previewEnd && value >= draft.start && value <= previewEnd ? 'in-range' : '',
                  isStart ? 'range-start' : '', isEnd ? 'range-end' : '', isStart && (!previewEnd || isEnd) ? 'single-day' : ''].filter(Boolean).join(' ');
                const label = [date.toLocaleDateString(locale, { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' }),
                  disabled ? t("dates:futureDatesAreUnavailable") : '', resetLabel].filter(Boolean).join(' · ');
                return <div key={value} className={classes} data-cell-date={value}><button type="button" data-date={value}
                  className={['calendar-day', reset ? 'quota-reset-day' : '', isStart ? 'selected-start' : '', isEnd ? 'selected-end' : ''].filter(Boolean).join(' ')}
                  aria-label={label} aria-pressed={isStart || isEnd} title={resetLabel || undefined} disabled={disabled} tabIndex={value === tabDate ? 0 : -1}
                  onClick={() => select(value)} onKeyDown={event => onDayKey(event, value)}
                  onPointerOver={() => { if (phase === 'end' && !disabled) setHoverDate(value); }}>{date.getDate()}</button></div>;
              })}</div>
            </section>)}
          </div>
          {exact && <p id="calendarPrecision" className="fine-print">{t("dates:exactRangeHint")}</p>}
          <div className="calendar-footer">
            <p><strong>{t("dates:boldDates")}</strong> {t("dates:markQuotaResetRecordsIncludingEstimates")}</p>
            <button type="button" id="calendarConfirm" className="button primary" disabled={!draft.start || !draft.end || invalid} onClick={commit}>{t("dates:confirm")}</button>
          </div>
        </dialog>
      </div>
    </div>
  </div>;
}
