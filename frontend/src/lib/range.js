const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const timePattern = /^([01]\d|2[0-3]):[0-5]\d$/;
const hasTimezone = /(Z|[+-]\d{2}:\d{2})$/i;

function validDate(value) {
  if (!datePattern.test(value || '')) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function localInstant(value, timezone) {
  if (!hasTimezone.test(value || '') || !Number.isFinite(Date.parse(value))) return null;
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: timezone || 'UTC', hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return {date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}`};
}

export function readRange(params, config) {
  const date = (key, fallback) => validDate(params.get(key)) ? params.get(key) : fallback;
  const time = (key, fallback) => timePattern.test(params.get(key) || '') ? params.get(key) : fallback;
  const range = {
    start: date('start', config.defaultStart), end: date('end', config.defaultEnd),
    startTime: time('start_time', '00:00'), endTime: time('end_time', '23:59'),
    startAt: params.get('start_at') || '', endAt: params.get('end_at') || '',
    priceMode: params.get('price_mode') === 'current' ? 'current' : 'snapshot',
    grain: params.get('grain') === 'hourly' ? 'hourly' : 'daily',
  };
  const today = config.defaultEnd;
  if (range.start > today) range.start = today;
  if (range.end > today) range.end = today;
  if (range.start > range.end) range.start = range.end;
  if (range.start === range.end && range.startTime > range.endTime) { range.startTime = '00:00'; range.endTime = '23:59'; }
  const start = localInstant(range.startAt, config.timezone), end = localInstant(range.endAt, config.timezone);
  if (!start || !end || start.date !== range.start || end.date !== range.end || start.time !== range.startTime || end.time !== range.endTime || Date.parse(range.startAt) >= Date.parse(range.endAt)) {
    range.startAt = range.endAt = '';
  }
  return range;
}

export function rangeQuery(range, extra = {}) {
  const params = new URLSearchParams({
    start: range.start, end: range.end, start_time: range.startTime, end_time: range.endTime,
    price_mode: range.priceMode, grain: range.grain,
  });
  if (range.startAt && range.endAt) { params.set('start_at', range.startAt); params.set('end_at', range.endAt); }
  for (const [key, value] of Object.entries(extra)) if (value !== undefined && value !== null) params.set(key, value);
  return params.toString();
}
