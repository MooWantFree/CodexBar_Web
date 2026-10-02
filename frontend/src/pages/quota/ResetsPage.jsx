import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDashboard } from "../../context/DashboardContext";
import { locale, t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatDateTime, formatNumber, quotaWindowLabel } from "../../lib/format";
import { rangeQuery } from "../../lib/range";
import { EmptyState } from "../../components/Shared";
import { HistoryNotice, historyAvailable, historyContext } from "./QuotaShared";
import "../quotaMessages";

export function groupResetRecords(records = []) {
  const grouped = new Map();
  for (const record of records) {
    const stamp = Date.parse(record.reset_at);
    if (!Number.isFinite(stamp)) continue;
    const key = new Date(stamp).toISOString();
    const entry = grouped.get(key) || { key, stamp, labels: new Set(), estimated: false, methods: new Set() };
    entry.labels.add(quotaWindowLabel(record));
    entry.estimated ||= Boolean(record.time_estimated || record.confidence === "estimated");
    entry.methods.add(record.method);
    grouped.set(key, entry);
  }
  return [...grouped.values()].sort((a, b) => b.stamp - a.stamp);
}

export function localRangeParts(stamp, timezone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(stamp)).map(part => [part.type, part.value]));
  return { date: `${parts.year}-${parts.month}-${parts.day}`, clock: `${parts.hour}:${parts.minute}` };
}

export function ResetsPage() {
  const { quota, quotaLoading, quotaRefreshing, quotaError, refreshQuota, scanning, timezone, range, setRange } = useDashboard();
  const navigate = useNavigate();
  const [selection, setSelection] = useState(null);
  const resets = useMemo(() => groupResetRecords(quota?.reset_records), [quota?.reset_records, locale]);
  const scope = quota?.reset_history_scope;
  const selected = selection && selection.scope === scope && (selection.key === "today" || resets.some(record => record.key === selection.key)) ? selection : null;
  const records = [{ key: "today", stamp: selected?.key === "today" ? selected.stamp : Date.now() - 2 * 60 * 1000, labels: new Set([t("Today")]), methods: new Set(), today: true }, ...resets];
  const busy = quotaLoading || quotaRefreshing || scanning;
  function select(record) {
    if (!selected || selected.key === record.key) { setSelection(selected?.key === record.key ? null : { ...record, scope }); return; }
    const [start, end] = [selected, record].sort((a, b) => a.stamp - b.stamp);
    if (start.stamp === end.stamp) return;
    const startParts = localRangeParts(start.stamp, timezone), endParts = localRangeParts(end.stamp, timezone);
    const next = { ...range, start: startParts.date, end: endParts.date, startTime: startParts.clock, endTime: endParts.clock, startAt: new Date(start.stamp).toISOString(), endAt: new Date(end.stamp).toISOString() };
    setRange(next);
    setSelection(null);
    navigate(`/overview?${rangeQuery(next)}`);
  }
  let status = quotaLoading && !quota ? t("Reading reset records…") : historyAvailable(quota)
    ? t("{context} · {count} reset times · {estimated} include estimated times", { context: historyContext(quota), count: formatNumber(resets.length), estimated: formatNumber(resets.filter(record => record.estimated).length) })
    : systemMessage(quota?.message) || quotaError?.message || t("No local account reset records are available.");
  if (quota?.reset_history_status === "error") status += ` · ${t("The latest reset records could not be read or saved.")}`;
  return <section className="page" data-page="resets"><section className="panel reset-panel">
    <div className="panel-heading"><div><p className="eyebrow">{t("RESET HISTORY")}</p><h2>{t("Quota reset records")}</h2></div><button id="refreshResetsButton" type="button" className="button" disabled={busy} onClick={() => refreshQuota().catch(() => {})}>{t(busy ? "Reading…" : "Refresh records")}</button></div>
    <HistoryNotice quota={quota} />
    <p className="fine-print">{t("Select any two reset times to review usage between them. Times use {timezone}; estimated times are marked separately.", { timezone })}</p>
    <div className="reset-selection" aria-live="polite"><span id="resetSelectionStatus">{selected ? t("Selected {time}. Choose another time.", { time: formatDateTime(selected.stamp) }) : t("Choose the first time")}</span><button type="button" className="button ghost" disabled={!selected} onClick={() => setSelection(null)}>{t("Cancel selection")}</button></div>
    <p id="resetHistoryStatus" className="fine-print" role="status">{status}</p>
    <div id="resetRecords" className="reset-records" aria-busy={busy}>{records.map(record => {
      const parts = localRangeParts(record.stamp, timezone);
      const labels = [...record.labels].join(" · ");
      const picked = selected?.key === record.key;
      const badge = t(record.today ? "Reporting cutoff" : record.estimated ? "Estimated time" : "Confirmed");
      const description = t(record.today ? "Two minutes before the current time" : record.methods.has("early") ? "Early reset confirmed; time inferred from the new cycle" : record.estimated ? "Inferred from the next reset time and window duration" : "Cycle change confirmed by quota snapshots before and after");
      return <button type="button" key={record.key} className={`reset-record${picked ? " selected" : ""}`} aria-pressed={picked} aria-label={t("Select time, {time}, {labels}, {badge}", { time: `${parts.date} ${parts.clock}`, labels, badge })} onClick={() => select(record)} disabled={busy}>
        <span className="reset-record-check" aria-hidden="true">{picked ? "✓" : "○"}</span><span className="reset-record-time"><strong>{parts.date}</strong><time dateTime={new Date(record.stamp).toISOString()}>{parts.clock}</time></span><span className="reset-record-detail"><strong>{labels}</strong><small>{description}</small></span><span className={`reset-badge${record.estimated ? " estimated" : ""}`}>{badge}</span><span className="reset-record-action">{t(picked ? "Selected" : "Select")}</span>
      </button>;
    })}{!resets.length && <EmptyState>{t("No reset records yet. Reading an active quota window will show its estimated cycle start.")}</EmptyState>}</div>
    <p className="fine-print reset-note">{t("Estimated starts subtract the window duration from its next reset time. Missing historical cycles are not reconstructed. The selected range ends immediately before the second reset.")}</p>
  </section></section>;
}

