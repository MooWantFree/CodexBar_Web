import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDashboard } from "../../context/DashboardContext";
import { apiGet } from "../../lib/api";
import { t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatNumber, quotaWindowLabel } from "../../lib/format";
import { EmptyState, ErrorNotice, Pager } from "../../components/Shared";
import { HistoryNotice, historyContext, planLabel, valueTime, percent, valueMoney } from "./QuotaShared";
import "../quotaMessages";

function observationNotes(row) {
  return [systemMessage(row.message), row.total?.unknown_price_calls && t("{count} unpriced calls; amounts and extrapolations include only known prices.", { count: formatNumber(row.total.unknown_price_calls) }), row.total?.unknown_tier_calls && t("{count} calls have unknown tiers and use Standard base prices.", { count: formatNumber(row.total.unknown_tier_calls) }), row.price_mode === "snapshot" && row.total?.inferred_price_calls && t("{count} calls use prices backfilled at the first scan.", { count: formatNumber(row.total.inferred_price_calls) })].filter(Boolean).join(" ");
}

function QuotaValueCard({ window, report, saved }) {
  const total = window.total;
  const partial = total?.unknown_price_calls > 0;
  const coverage = total ? t("{calls} calls · {tokens} tokens · {coverage}", { calls: formatNumber(total.calls), tokens: formatNumber(total.total_tokens), coverage: partial ? t("{count} unpriced calls", { count: formatNumber(total.unknown_price_calls) }) : t("Complete pricing") }) : t("No call samples for conversion");
  const remainingLabel = t(partial ? "Known amount estimate for remaining quota" : "Remaining quota value estimate");
  return <article className="panel quota-value-card">
    <div className="panel-heading"><h2>{quotaWindowLabel(window)}</h2><span className={`reset-badge${window.cycle_start_estimated ? " estimated" : ""}`}>{t(window.cycle_start_at ? window.cycle_start_estimated ? "Estimated start" : "Confirmed start" : "Unknown start")}</span></div>
    <div className="quota-value-range"><span>{t("Cycle start")} <strong>{valueTime(window.cycle_start_at)}</strong></span><span>{t("Reporting cutoff time")} <strong>{valueTime(report.fetched_at)}</strong></span><span>{t(saved ? "Scheduled reset at that reading" : "Next reset")} <strong>{valueTime(window.resets_at)}</strong></span></div>
    <dl className="quota-value-metrics">
      <div><dt>{t("Quota used during the period")}</dt><dd>{percent(window.used_percent)}</dd><small>{t(saved ? "Saved quota reading" : "Server quota reading")}</small></div>
      <div><dt>{t(partial ? "Known API-equivalent amount" : "API-equivalent amount")}</dt><dd>{valueMoney(total?.api_usd_known)}</dd><small>{coverage}</small></div>
      <div><dt>{t(partial ? "Known amount estimate per 1%" : "Equivalent dollars per 1%")}</dt><dd>{valueMoney(window.usd_per_percent)}</dd><small>{t(partial ? "Known amount ÷ used percentage" : "Period amount ÷ used percentage")}</small></div>
      <div><dt>{t("Full window (100%) estimate")}</dt><dd>{valueMoney(window.full_quota_usd)}</dd><small>{t(partial ? "Extrapolated from known amounts" : saved ? "Extrapolated from samples at that reading" : "Extrapolated from current samples")}</small></div>
    </dl>
    <p className="fine-print quota-value-remaining">{saved ? t("At that reading: {label}", { label: remainingLabel }) : remainingLabel}: <strong>{valueMoney(window.remaining_quota_usd)}</strong>{window.remaining_percent != null && ` (${t("{percent} remaining", { percent: percent(window.remaining_percent) })})`}</p>
    {observationNotes({ ...window, price_mode: report.price_mode }) && <p className="fine-print unknown">{observationNotes({ ...window, price_mode: report.price_mode })}</p>}
  </article>;
}

const historyHeaders = ["Window / plan", "Cycle start", "Last used quota", "Consumed equivalent amount", "Last read", "Estimate per 1%", "100% estimate", "Snapshots", "Reading details"];
const observationHeaders = ["Read time", "Used quota", "Known API-equivalent amount", "Estimate per 1%", "100% estimate", "Remaining quota estimate", "Notes"];
const compatibilityError = () => new Error(t("The backend response is incompatible. Restart the application and try again."));

export function QuotaValuePage() {
  const { quota, quotaLoading, quotaRefreshing, refreshQuota, scan, scanning, range, setRange } = useDashboard();
  const client = useQueryClient();
  const [page, setPage] = useState(0);
  const [selection, setSelection] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [actionError, setActionError] = useState(null);
  const scope = quota?.reset_history_scope || "unavailable";
  const mode = range.priceMode;
  const identity = `${scope}:${mode}`;
  const version = quota?.checked_at || quota?.fetched_at || quota?.history_fetched_at || "initial";
  const historyIdentity = `${identity}:${page}`;
  const selectedID = selection?.identity === historyIdentity ? selection.id : null;
  const lastCurrent = useRef(null), lastHistory = useRef(null);
  const detailPanel = useRef(null), detailTrigger = useRef(null);
  const focusedDetail = useRef(null);
  const enabled = Boolean(quota) && !quotaLoading && !quotaRefreshing && !scanning && !refreshing;
  const current = useQuery({ queryKey: ["quota-value", scope, mode, version], enabled, queryFn: async ({ signal }) => {
    const report = await apiGet(`/api/quota/value?${new URLSearchParams({ price_mode: mode })}`, { signal });
    if (!report || !Array.isArray(report.windows)) throw compatibilityError();
    return report;
  } });
  const history = useQuery({ queryKey: ["quota-value-history", scope, mode, version, page], enabled, queryFn: async ({ signal }) => {
    const report = await apiGet(`/api/quota/value/history?${new URLSearchParams({ price_mode: mode, offset: page * 20, limit: 20 })}`, { signal });
    if (!report || !Array.isArray(report.cycles)) throw compatibilityError();
    return report;
  } });
  const detail = useQuery({ queryKey: ["quota-value-detail", scope, mode, version, selectedID], enabled: enabled && selectedID != null, queryFn: async ({ signal }) => {
    const report = await apiGet(`/api/quota/value/history/${selectedID}?${new URLSearchParams({ price_mode: mode })}`, { signal });
    if (report?.cycle?.id !== selectedID || !Array.isArray(report.observations)) throw compatibilityError();
    return report;
  } });
  useEffect(() => { setPage(0); setSelection(null); setActionError(null); }, [identity]);
  useEffect(() => {
    if (selectedID == null) { focusedDetail.current = null; return; }
    const key = `${identity}:${selectedID}`;
    if (detail.data && focusedDetail.current !== key) {
      focusedDetail.current = key;
      detailPanel.current?.focus();
      detailPanel.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }, [detail.data, selectedID, identity]);
  if (current.data?.status === "ready") lastCurrent.current = { identity, report: current.data };
  if (history.data?.status === "ready") lastHistory.current = { identity, report: history.data };
  const report = current.data || (lastCurrent.current?.identity === identity ? lastCurrent.current.report : null);
  const historyReport = history.data || (lastHistory.current?.identity === identity ? lastHistory.current.report : null);
  const saved = Boolean(report?.saved || quota?.status !== "ready" || current.isError || actionError);
  const busy = quotaLoading || quotaRefreshing || scanning || refreshing;
  const basis = t(mode === "current" ? saved ? "Current-price conversion at that reading" : "Recalculate at current prices" : "Saved price estimate");
  let status = busy ? t(scanning || refreshing ? "Scanning new logs and refreshing quota…" : "Reading account quota…") : !report && current.isPending ? t(quota?.status === "ready" ? "Calculating current cycle quota…" : "Reading the last saved conversion…")
    : report?.status === "ready" ? [saved && historyContext({ ...quota, ...report, status: quota?.status }), saved && t("Last saved conversion"), t("{plan} · quota read at {time} · {basis}", { plan: planLabel(report), time: valueTime(report.fetched_at), basis }), saved && t("Amounts and percentages remain as read")].filter(Boolean).join(" · ")
      : systemMessage(report?.message) || current.error?.message || t("Quota unavailable");
  if (quota?.archive_status === "error" || report?.archive_status === "error") status += ` · ${t("Raw quota readings could not be saved; amounts remain available.")}`;
  if (quota?.value_history_status === "error" || report?.value_history_status === "error") status += ` · ${t("Quota value history could not be saved; current amounts remain available.")}`;
  const displayedPage = historyReport?.status === "ready" ? Math.floor(historyReport.offset / 20) : page;
  const cycles = historyReport?.status === "ready" ? historyReport.cycles : [];
  let historyStatus = historyReport?.status === "ready" ? t("{context} · {count} saved cycles · {basis} · Historical amounts remain as read", { context: historyContext({ ...quota, ...historyReport, status: quota?.status }), count: formatNumber(historyReport.total), basis: t(mode === "current" ? "Current-price conversion at that reading" : "Saved-price conversion at that reading") })
    : systemMessage(historyReport?.message) || t("Reading saved account history…");
  if (history.isError && historyReport) historyStatus += ` · ${history.error.message} · ${t("Displayed records retain values from the previous successful read.")}`;
  if (quota?.value_history_status === "error") historyStatus += ` · ${t("The latest history could not be saved; existing records remain available.")}`;
  async function refresh() {
    if (busy) return;
    setRefreshing(true); setActionError(null); setSelection(null); setPage(0);
    try {
      await scan();
      await refreshQuota();
    } catch (error) { setActionError(error); }
    finally {
      setRefreshing(false);
      void client.invalidateQueries({ predicate: query => String(query.queryKey[0]).startsWith("quota-value") });
    }
  }
  function closeDetail() { setSelection(null); detailTrigger.current?.focus(); }
  return <section className="page" data-page="quota-value">
    <section className="panel quota-value-intro">
      <div className="panel-heading quota-value-heading"><div><p className="eyebrow">{t("QUOTA VALUE")}</p><h2 id="quotaValueTitle">{t(saved ? "Last saved conversion" : "Current cycle conversion")}</h2></div><div className="quota-value-actions"><label className="price-mode-control"><span>{t("Pricing basis")}</span><select id="quotaValuePriceMode" value={mode} disabled={busy} onChange={event => { setSelection(null); setPage(0); setRange({ priceMode: event.target.value }); }}><option value="snapshot">{t("Saved price estimate")}</option><option value="current">{t("Recalculate at current prices")}</option></select></label><button type="button" id="refreshQuotaValueButton" className="button" disabled={busy} onClick={refresh}>{t(refreshing ? "Refreshing…" : quotaLoading || quotaRefreshing ? "Reading…" : "Refresh and convert")}</button></div></div>
      <HistoryNotice quota={quota} />
      <p className="fine-print">{t("API-equivalent dollars are calculated from each window's cycle start through the quota reading time. Estimated start = next reset time − window duration.")}</p>
      <p id="quotaValueStatus" className="fine-print" role="status">{status}</p>
      {actionError && <ErrorNotice error={actionError} />}{current.error && report && <ErrorNotice error={current.error} />}
    </section>
    <div id="quotaValueWindows" className="quota-value-windows" aria-busy={busy || current.isFetching}>{report?.windows?.length ? report.windows.map((window, index) => <QuotaValueCard key={`${window.limit_id}-${window.slot}-${index}`} window={window} report={report} saved={saved} />) : !current.isPending && <div className="panel"><EmptyState>{systemMessage(report?.message) || current.error?.message || t("No convertible percentage quota windows were returned.")}</EmptyState></div>}</div>
    <section id="quotaValueHistoryPanel" className="panel quota-value-history" aria-labelledby="quotaValueHistoryTitle" aria-busy={busy || history.isFetching}>
      <div className="panel-heading"><div><p className="eyebrow">{t("SAVED HISTORY")}</p><h2 id="quotaValueHistoryTitle">{t("Quota value history")}</h2></div><span className="fine-print">{t("20 cycles per page")}</span></div>
      <p id="quotaValueHistoryStatus" className="fine-print" role="status">{historyStatus}</p>
      {history.error && !historyReport && <ErrorNotice error={history.error} />}
      <p className="fine-print">{t("Each cycle shows its last successful quota and amount reading. A historical cycle's last reading may precede its reset and does not represent its final total usage.")}</p>
      <div className="table-wrap quota-value-history-table-wrap"><table className="quota-value-history-table"><thead><tr>{historyHeaders.map(header => <th scope="col" key={header}>{t(header)}</th>)}</tr></thead><tbody id="quotaValueHistoryTable">{cycles.map(cycle => {
        const selected = cycle.id === selectedID;
        const isCurrent = quota?.status === "ready" && cycle.is_current;
        return <tr key={cycle.id} className={selected ? "selected" : undefined}>
          <td><strong>{quotaWindowLabel(cycle)}</strong><small>{planLabel(cycle)} <span className={`coverage${isCurrent ? "" : " partial"}`}>{t(isCurrent ? "Current cycle" : "Historical cycle")}</span></small></td>
          <td>{valueTime(cycle.cycle_start_at)}<small>{t(cycle.cycle_start_at ? cycle.cycle_start_estimated ? "Estimated start" : "Confirmed start" : "Unknown start")} · {t("Scheduled reset at that reading")} {valueTime(cycle.resets_at)}</small></td>
          <td className="quota-value-primary">{percent(cycle.used_percent)}</td><td className="quota-value-primary">{valueMoney(cycle.total?.api_usd_known)}{cycle.total?.unknown_price_calls > 0 && <small className="unknown">{t("Known amounts only")}</small>}</td><td>{valueTime(cycle.fetched_at)}</td><td>{valueMoney(cycle.usd_per_percent)}</td><td>{valueMoney(cycle.full_quota_usd)}</td><td>{formatNumber(cycle.observation_count)}</td>
          <td><button type="button" className="button ghost" disabled={busy || history.isFetching} aria-controls="quotaValueHistoryDetail" aria-expanded={selected} onClick={event => { detailTrigger.current = event.currentTarget; setSelection(selected ? null : { identity: historyIdentity, id: cycle.id }); }}>{t(selected ? "Hide details" : "View readings")}</button></td>
        </tr>;
      })}{!cycles.length && <tr><td colSpan="9" className="empty-state">{history.isPending ? t("Reading saved account history…") : systemMessage(historyReport?.message) || history.error?.message || t("No saved quota value history yet. Recording begins after reading a recognizable quota cycle.")}</td></tr>}</tbody></table></div>
      <Pager page={displayedPage} pages={Math.ceil((historyReport?.total || 0) / 20)} disabled={busy || history.isFetching} onPage={next => { setSelection(null); setPage(next); }} />
    </section>
    {selectedID != null && <section ref={detailPanel} id="quotaValueHistoryDetail" className="panel quota-value-history-detail" aria-labelledby="quotaValueHistoryDetailTitle" aria-busy={detail.isFetching} tabIndex={-1}>
      <div className="panel-heading"><h2 id="quotaValueHistoryDetailTitle">{detail.data ? t("{window} · cycle reading details", { window: quotaWindowLabel(detail.data.cycle) }) : t("Cycle reading details")}</h2><button type="button" className="button ghost" onClick={closeDetail}>{t("Hide details")}</button></div>
      <p id="quotaValueHistoryDetailStatus" className="fine-print" role="status">{detail.isPending ? t("Reading saved cycle snapshots…") : detail.data ? t("{context} · cycle start {start} · scheduled reset {reset} · {count} saved readings · {cycle}", { context: historyContext({ ...quota, ...detail.data, status: quota?.status }), start: valueTime(detail.data.cycle.cycle_start_at), reset: valueTime(detail.data.cycle.resets_at), count: formatNumber(detail.data.observations.length), cycle: t(quota?.status === "ready" && detail.data.cycle.is_current ? "Current cycle" : "Historical cycle; its last reading is not final usage at reset") }) : ""}</p>
      <ErrorNotice error={detail.error} />
      <p className="fine-print">{t("Readings show saved amounts in reverse chronological order. Values per 1%, for 100%, and for remaining quota use that reading's proportions.")}</p>
      <div className="table-wrap quota-value-observations-wrap"><table><thead><tr>{observationHeaders.map(header => <th scope="col" key={header}>{t(header)}</th>)}</tr></thead><tbody id="quotaValueObservationTable">{(detail.data?.observations || []).map((row, index) => <tr key={`${row.fetched_at}-${index}`}><td>{valueTime(row.fetched_at)}</td><td>{percent(row.used_percent)}</td><td>{valueMoney(row.total?.api_usd_known)}</td><td>{valueMoney(row.usd_per_percent)}</td><td>{valueMoney(row.full_quota_usd)}</td><td>{valueMoney(row.remaining_quota_usd)}</td><td className="quota-value-observation-note">{observationNotes(row) || "—"}</td></tr>)}{detail.data && !detail.data.observations.length && <tr><td colSpan="7" className="empty-state">{t("No snapshots are available for this cycle.")}</td></tr>}</tbody></table></div>
    </section>}
    <section className="panel quota-value-notes"><h2>{t("Conversion basis")}</h2>{[
      "Dollars per 1% = period API-equivalent amount ÷ used percentage. Full window estimate = dollars per 1% × 100. Estimates use this cycle's model and Fast mix and change with usage.",
      "Window ranges may overlap; view their amounts separately. Amounts come from local calls in this log directory, whose account ownership cannot be verified. Other devices and cloud usage are excluded. This is an API-equivalent estimate, not a subscription bill or a purchase price for quota.",
      "Unpriced calls are excluded. Known amounts still estimate 1%, the full window, and remaining quota and are marked accordingly. Refresh and convert scans new logs and reads quota; changing pages reuses the latest reading.",
      "Every successful quota read saves both pricing bases. Historical amounts never recalculate after price changes and remain after source logs are deleted. Failed live reads show saved history; an unidentified account uses the last saved account with an offline label. Unrecorded historical cycles cannot be reconstructed.",
    ].map(note => <p className="fine-print" key={note}>{t(note)}</p>)}</section>
  </section>;
}

