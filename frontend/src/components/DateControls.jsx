import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useDashboard } from '../context/DashboardContext';
import { addMessages, locale, t } from '../lib/i18n';

addMessages({
  en: {
    '日期快捷选项': 'Date shortcuts', '今天': 'Today', '近 7 天': 'Last 7 days', '近 30 天': 'Last 30 days',
    '近 90 天': 'Last 90 days', '全部': 'All time', '开始时间': 'Start time', '结束时间': 'End time',
    '选择日期范围': 'Select date range', '重置': 'Reset', '关闭日历': 'Close calendar',
    '开始日期': 'Start date', '结束日期': 'End date', '开始小时': 'Start hour', '开始分钟': 'Start minute',
    '结束小时': 'End hour', '结束分钟': 'End minute', '上个月': 'Previous month', '下个月': 'Next month',
    '请选择': 'Select a date', '请选择开始日期': 'Select the start date',
    '请选择结束日期 · 同一天也可选择': 'Select the end date · The same day is allowed',
    '结束时间不能早于开始时间，请调整日期或时分': 'The end time cannot precede the start time. Adjust the date or time.',
    '当前范围精确到重置时刻；手动修改日期或时分后按分钟筛选。': 'This range uses exact reset times. Editing the date or time switches to minute precision.',
    '加粗日期': 'Bold dates', '表示额度重置记录（含推测）· 日期选完或修改时间后自动更新统计。': 'mark quota reset records, including estimates · Statistics update after selecting dates or changing the time.',
    '选择日期范围，{start} 至 {end}': 'Select date range, {start} to {end}',
    '未来日期不可选': 'Future dates are unavailable', '每周额度': 'Weekly quota',
    '{hours} 小时额度': '{hours}-hour quota', '{minutes} 分钟额度': '{minutes}-minute quota',
    '{window}已重置': '{window} reset',
    '{window}重置（推测）': '{window} reset (estimated)',
    '按当前价格重算 · 已包含 Fast API 加价': 'Recalculated at current prices · Includes the Fast API surcharge',
    '按调用时已保存的价格估算 · 已包含 Fast API 加价': 'Estimated at saved prices · Includes the Fast API surcharge',
    '快照估算 · {count} 次调用使用首次采集价格回填': 'Saved price estimate · {count} calls use the first collected price',
    '按当前有效价格重算；API 等价已包含 Fast API 加价。': 'Recalculated using current effective prices; API equivalent costs include the Fast API surcharge.',
    '按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。': 'Calculated using saved price snapshots, which later price changes do not replace; API equivalent costs include the Fast API surcharge.',
    '其中 {count} 次旧调用使用首次采集价格，属于回填估算，无法确认当时官方价。': '{count} older calls use the first collected price as an estimate; their original official price is unknown.',
    '小时趋势仅显示有调用的小时。': 'Hourly trends show only hours with calls.',
  },
  ja: {
    '日期快捷选项': '日付のショートカット', '今天': '今日', '近 7 天': '過去 7 日間', '近 30 天': '過去 30 日間',
    '近 90 天': '過去 90 日間', '全部': '全期間', '开始时间': '開始時刻', '结束时间': '終了時刻',
    '选择日期范围': '日付範囲を選択', '重置': 'リセット', '关闭日历': 'カレンダーを閉じる',
    '开始日期': '開始日', '结束日期': '終了日', '开始小时': '開始時', '开始分钟': '開始分',
    '结束小时': '終了時', '结束分钟': '終了分', '上个月': '前の月', '下个月': '次の月',
    '请选择': '日付を選択', '请选择开始日期': '開始日を選択してください',
    '请选择结束日期 · 同一天也可选择': '終了日を選択してください · 同じ日も選択できます',
    '结束时间不能早于开始时间，请调整日期或时分': '終了時刻を開始時刻より前にはできません。日付または時刻を調整してください。',
    '当前范围精确到重置时刻；手动修改日期或时分后按分钟筛选。': '現在の範囲は正確なリセット時刻を使用しています。日付や時刻を変更すると分単位の絞り込みに切り替わります。',
    '加粗日期': '太字の日付', '表示额度重置记录（含推测）· 日期选完或修改时间后自动更新统计。': 'は利用枠のリセット記録（推定を含む）です · 日付の選択や時刻の変更後に統計が自動更新されます。',
    '选择日期范围，{start} 至 {end}': '日付範囲を選択、{start} から {end}',
    '未来日期不可选': '未来の日付は選択できません', '每周额度': '週間利用枠',
    '{hours} 小时额度': '{hours} 時間の利用枠', '{minutes} 分钟额度': '{minutes} 分の利用枠',
    '{window}已重置': '{window}がリセット済み',
    '{window}重置（推测）': '{window}リセット（推定）',
    '按当前价格重算 · 已包含 Fast API 加价': '現在の料金で再計算 · Fast API の追加料金を含む',
    '按调用时已保存的价格估算 · 已包含 Fast API 加价': '保存済み料金で推計 · Fast API の追加料金を含む',
    '快照估算 · {count} 次调用使用首次采集价格回填': '保存済み料金で推計 · {count} 回の呼び出しに初回取得料金を適用',
    '按当前有效价格重算；API 等价已包含 Fast API 加价。': '現在の有効な料金で再計算します。API 換算額には Fast API の追加料金を含みます。',
    '按保存的价格快照计算，后续价格修改不会覆盖；API 等价已包含 Fast API 加价。': '保存済みの料金スナップショットで計算し、後からの料金変更では上書きしません。API 換算額には Fast API の追加料金を含みます。',
    '其中 {count} 次旧调用使用首次采集价格，属于回填估算，无法确认当时官方价。': '過去の {count} 回の呼び出しには初回取得料金を推計として適用しています。当時の公式料金は確認できません。',
    '小时趋势仅显示有调用的小时。': '時間別の推移には呼び出しがあった時間のみを表示します。',
  },
});

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
  return date ? date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' }) : t('请选择');
}

function copyRange(range) {
  return { start: parseDate(range.start) ? range.start : '', end: parseDate(range.end) ? range.end : '',
    startTime: range.startTime || '00:00', endTime: range.endTime || '23:59' };
}

function TimeControl({ side, value, onChange }) {
  const [hour, minute] = value.split(':');
  const label = side === 'start' ? '开始' : '结束';
  return <div className="calendar-time"><span>{t(`${label}时间`)}</span><div>
    <select id={`calendar${side === 'start' ? 'Start' : 'End'}Hour`} aria-label={t(`${label}小时`)} value={hour}
      onChange={event => onChange(`${event.target.value}:${minute}`)}>
      {Array.from({ length: 24 }, (_, value) => <option key={value} value={pad(value)}>{pad(value)}</option>)}
    </select><span aria-hidden="true">:</span>
    <select id={`calendar${side === 'start' ? 'Start' : 'End'}Minute`} aria-label={t(`${label}分钟`)} value={minute}
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
      const window = minutes === 10080 ? t('每周额度') : minutes % 60 === 0
        ? t('{hours} 小时额度', { hours: minutes / 60 }) : t('{minutes} 分钟额度', { minutes });
      const label = event.limit_id === 'codex' ? window : `${event.limit_name || event.limit_id} · ${window}`;
      const labels = dates.get(date) || new Set();
      const estimated = event.confidence === 'estimated' || event.method === 'estimated';
      labels.add(t(estimated ? '{window}重置（推测）' : '{window}已重置', { window: label }));
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
  const hint = invalid ? t('结束时间不能早于开始时间，请调整日期或时分')
    : t(phase === 'start' ? '请选择开始日期' : '请选择结束日期 · 同一天也可选择');

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

  function commit(next, close = true) {
    if (!next.start || !next.end || `${next.start}T${next.startTime}` > `${next.end}T${next.endTime}`) return;
    setRange({ ...next, startAt: '', endAt: '' });
    if (close) closePicker();
  }

  function select(value) {
    if (!parseDate(value) || value > today) return;
    setFocusedDate(value);
    setHoverDate(null);
    if (phase === 'start' || !draft.start || value < draft.start) {
      setDraft({ ...draft, start: value, end: '' });
      setPhase('end');
    } else {
      const next = { ...draft, end: value };
      setDraft(next);
      commit(next);
    }
  }

  function changeTime(side, value) {
    const next = { ...draft, [`${side}Time`]: value };
    setDraft(next);
    commit(next, false);
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
      <div className="presets" aria-label={t('日期快捷选项')}>
        {[[1, '今天'], [7, '近 7 天'], [30, '近 30 天'], [90, '近 90 天'], ['all', '全部']].map(([days, label]) => {
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
          aria-controls="dateRangeDialog" aria-expanded={open} aria-label={t('选择日期范围，{start} 至 {end}', { start: startLabel, end: endLabel })}
          onClick={openPicker}>
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M7 3v4M17 3v4M3 11h18" /></svg>
          <span className="date-range-value"><small>{t('开始时间')}</small><strong id="rangeStartLabel">{startLabel}</strong></span>
          <span className="date-range-arrow" aria-hidden="true">→</span>
          <span className="date-range-value"><small>{t('结束时间')}</small><strong id="rangeEndLabel">{endLabel}</strong></span>
          <span className="date-range-chevron" aria-hidden="true">⌄</span>
        </button>
        <dialog id="dateRangeDialog" ref={dialogRef} className="date-range-dialog" aria-labelledby="calendarTitle" aria-describedby="calendarHint"
          onCancel={event => { event.preventDefault(); closePicker(); }} onClose={() => { setOpen(false); triggerRef.current?.focus(); }}
          onClick={event => {
            if (event.target !== event.currentTarget) return;
            const rect = event.currentTarget.getBoundingClientRect();
            if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closePicker();
          }}>
          <div className="calendar-heading"><h2 id="calendarTitle">{t('选择日期范围')}</h2><div>
            <button type="button" id="calendarReset" className="button ghost" onClick={() => {
              setDraft({ start: '', end: '', startTime: '00:00', endTime: '23:59' }); setPhase('start'); setHoverDate(null); setFocusedDate(null);
            }}>{t('重置')}</button>
            <button type="button" id="calendarClose" className="calendar-icon-button" aria-label={t('关闭日历')} onClick={closePicker}>×</button>
          </div></div>
          <div className="calendar-selection">
            <button type="button" id="calendarStart" ref={startRef} className={`calendar-selection-button${phase === 'start' ? ' active' : ''}`}
              onClick={() => setPhase('start')}><small>{t('开始日期')}</small><strong>{displayDate(draft.start)}</strong></button>
            <span aria-hidden="true">→</span>
            <button type="button" id="calendarEnd" className={`calendar-selection-button${phase === 'end' ? ' active' : ''}`}
              onClick={() => setPhase(draft.start ? 'end' : 'start')}><small>{t('结束日期')}</small><strong>{displayDate(draft.end)}</strong></button>
          </div>
          <div className="calendar-times"><TimeControl side="start" value={draft.startTime} onChange={value => changeTime('start', value)} />
            <span aria-hidden="true">→</span><TimeControl side="end" value={draft.endTime} onChange={value => changeTime('end', value)} /></div>
          <div className="calendar-navigation"><button type="button" id="calendarPrevious" className="calendar-icon-button" aria-label={t('上个月')} onClick={() => moveMonth(-1)}>‹</button>
            <p id="calendarHint" className={invalid ? 'error-text' : undefined} aria-live="polite">{hint}</p>
            <button type="button" id="calendarNext" className="calendar-icon-button" aria-label={t('下个月')}
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
                  disabled ? t('未来日期不可选') : '', resetLabel].filter(Boolean).join(' · ');
                return <div key={value} className={classes} data-cell-date={value}><button type="button" data-date={value}
                  className={['calendar-day', reset ? 'quota-reset-day' : '', isStart ? 'selected-start' : '', isEnd ? 'selected-end' : ''].filter(Boolean).join(' ')}
                  aria-label={label} aria-pressed={isStart || isEnd} title={resetLabel || undefined} disabled={disabled} tabIndex={value === tabDate ? 0 : -1}
                  onClick={() => select(value)} onKeyDown={event => onDayKey(event, value)}
                  onPointerOver={() => { if (phase === 'end' && !disabled) setHoverDate(value); }}>{date.getDate()}</button></div>;
              })}</div>
            </section>)}
          </div>
          {exact && <p id="calendarPrecision" className="fine-print">{t('当前范围精确到重置时刻；手动修改日期或时分后按分钟筛选。')}</p>}
          <p className="calendar-footer"><strong>{t('加粗日期')}</strong> {t('表示额度重置记录（含推测）· 日期选完或修改时间后自动更新统计。')}</p>
        </dialog>
      </div>
    </div>
  </div>;
}
