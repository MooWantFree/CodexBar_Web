import { systemMessage } from "../../lib/systemMessages";
import { useEffect, useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDashboard } from "../../context/DashboardContext";
import { apiGet } from "../../lib/api";
import { t } from "../../lib/i18n";

import { formatNumber, quotaWindowLabel } from "../../lib/format";
import { EmptyState, ErrorNotice, Pager } from "../../components/Shared";
import { LoadingStatus, UsageSkeleton, UsageTableSkeleton } from "../../components/UsageSkeleton";
import { HistoryNotice, historyContext, planLabel, valueTime, percent, valueMoney } from "./QuotaShared";
import { QuotaUsageChart } from "./QuotaUsageChart";

const conversionNotes = [
  "quota:conversionFormula",
  "quota:conversionLimitations",
  "quota:knownAmountWarning",
  "quota:historyRetentionHint",
];

function QuotaValueTooltip({ paragraphs, label }) {
  const id = useId();
  const triggerRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({});
  function show() {
    const bounds = triggerRef.current.getBoundingClientRect();
    const below = window.innerHeight - bounds.bottom - 16, above = bounds.top - 16;
    const showAbove = below < 320 && above > below;
    setPosition({ top: showAbove ? "auto" : "100%", bottom: showAbove ? "100%" : "auto", maxHeight: Math.max(0, Math.min(600, showAbove ? above : below)) });
    setOpen(true);
  }
  return <div className="quota-value-tooltip quota-value-window-help"
    onMouseEnter={show} onMouseLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setOpen(false); }}
    onFocus={show} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    onKeyDown={event => { if (event.key === "Escape") setOpen(false); }}>
    <button ref={triggerRef} type="button" className="quota-value-tooltip-trigger quota-value-help-trigger" aria-label={label} aria-describedby={id}>?</button>
    <div id={id} role="tooltip" className="quota-value-tooltip-content" style={position} hidden={!open}>{paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>
  </div>;
}

function observationNotes(row) {
  return [systemMessage(row.message), row.total?.unknown_price_calls && t("quota:unpricedCallsWarning", { count: row.total.unknown_price_calls }), row.total?.unknown_tier_calls && t("quota:unknownTierCalls", { count: row.total.unknown_tier_calls }), row.price_mode === "snapshot" && row.total?.inferred_price_calls && t("quota:backfilledCalls", { count: row.total.inferred_price_calls })].filter(Boolean).join(" ");
}

function QuotaValueCard({ window, report, saved }) {
  const total = window.total;
  const partial = total?.unknown_price_calls > 0;
  const coverage = total ? t("quota:callsTokens", { count: Number(total.calls) || 0, tokens: formatNumber(total.total_tokens), coverage: partial ? t("quota:unpricedCalls", { count: Number(total.unknown_price_calls) }) : t("quota:completePricing") }) : t("quota:noCallSamplesForConversion");
  return <article className="panel quota-value-card">
    <div className="panel-heading"><div className="quota-value-window-title"><h2>{quotaWindowLabel(window)}</h2>{window.window_minutes === 10080 && <QuotaValueTooltip label={t("quota:conversionBasis")} paragraphs={conversionNotes.map(note => t(note))} />}</div><span className={`reset-badge${window.cycle_start_estimated ? " estimated" : ""}`}>{t(window.cycle_start_at ? window.cycle_start_estimated ? "quota:estimatedStart" : "quota:confirmedStart" : "quota:unknownStart")}</span></div>
    <div className="quota-value-range"><span>{t("quota:cycleStart")} <strong>{valueTime(window.cycle_start_at)}</strong></span><span>{t("quota:reportingCutoffTime")} <strong>{valueTime(report.fetched_at)}</strong></span><span>{t(saved ? "quota:scheduledResetAtThatReading" : "quota:nextReset")} <strong>{valueTime(window.resets_at)}</strong></span></div>
    <dl className="quota-value-metrics">
      <div><dt>{t("quota:quotaUsedDuringThePeriod")}</dt><dd>{percent(window.used_percent)}</dd>{saved && <small>{t("quota:savedQuotaReading")}</small>}</div>
      <div><dt>{t(partial ? "quota:knownApiEquivalentAmount" : "quota:apiEquivalentAmount")}</dt><dd>{valueMoney(total?.api_usd_known)}</dd><small>{coverage}</small></div>
      <div><dt>{t(partial ? "quota:knownAmountEstimatePer1" : "quota:equivalentDollarsPer1")}</dt><dd>{valueMoney(window.usd_per_percent)}</dd></div>
      <div><dt>{t("quota:fullWindow100Estimate")}</dt><dd>{valueMoney(window.full_quota_usd)}</dd>{partial && <small>{t("quota:extrapolatedFromKnownAmounts")}</small>}</div>
    </dl>
  </article>;
}

function QuotaValueCardSkeleton({ window }) {
  const metrics = ["quota:quotaUsedDuringThePeriod", "quota:apiEquivalentAmount", "quota:equivalentDollarsPer1", "quota:fullWindow100Estimate"];
  return <article className="panel quota-value-card" aria-hidden="true">
    <div className="panel-heading"><div className="quota-value-window-title"><h2>{window ? quotaWindowLabel(window) : <UsageSkeleton className="usage-heading-skeleton" />}</h2></div><UsageSkeleton className="usage-inline-skeleton" style={{ width: 80 }} /></div>
    <div className="quota-value-range">{["quota:cycleStart", "quota:reportingCutoffTime", "quota:nextReset"].map(label => <span key={label}>{t(label)}<strong><UsageSkeleton className="usage-line-skeleton" style={{ width: 170 }} /></strong></span>)}</div>
    <dl className="quota-value-metrics">{metrics.map(label => <div key={label}><dt>{t(label)}</dt><dd><UsageSkeleton className="usage-kpi-value" /></dd><small><UsageSkeleton className="usage-line-skeleton" /></small></div>)}</dl>
  </article>;
}

const historyHeaders = ["quota:windowPlan", "quota:cycleStart", "quota:lastUsedQuota", "quota:consumedEquivalentAmount", "quota:lastRead", "quota:estimatePer1", "quota:fullQuotaEstimate", "quota:snapshots", "quota:readingDetails"];
const observationHeaders = ["quota:readTime", "quota:usedQuota", "quota:knownApiEquivalentAmount", "quota:estimatePer1", "quota:fullQuotaEstimate", "quota:remainingQuotaEstimate", "quota:notes"];
const compatibilityError = () => new Error(t("quota:incompatibleResponse"));

export function QuotaValuePage() {
  const { quota, quotaLoading, quotaRefreshing, quotaError, refreshQuota, scan, scanning, range, setRange } = useDashboard();
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
  const lastCurrent = useRef(null), lastHistory = useRef(null), lastDetail = useRef(null);
  const detailPanel = useRef(null), detailTrigger = useRef(null);
  const focusedDetail = useRef(null);
  const enabled = Boolean(quota) && !quotaLoading && !quotaRefreshing && !scanning && !refreshing;
  const current = useQuery({ queryKey: ["quota-value", scope, mode, version], enabled, queryFn: async ({ signal }) => {
    const report = await apiGet(`/api/quota/value?${new URLSearchParams({ price_mode: mode })}`, { signal });
    if (!report || !Array.isArray(report.windows)) throw compatibilityError();
    return report;
  } });
  const history = useQuery({ queryKey: ["quota-value-history", scope, mode, version, page], enabled, queryFn: async ({ signal }) => {
    const report = await apiGet(`/api/quota/value/history?${new URLSearchParams({ price_mode: mode, offset: page * 20, limit: 20, include_current: false })}`, { signal });
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
  if (history.data?.status === "ready") lastHistory.current = { identity: historyIdentity, report: history.data };
  const detailIdentity = `${identity}:${selectedID}`;
  if (detail.data) lastDetail.current = { identity: detailIdentity, report: detail.data };
  const report = current.data || (lastCurrent.current?.identity === identity ? lastCurrent.current.report : null);
  const historyReport = history.data || (lastHistory.current?.identity === historyIdentity ? lastHistory.current.report : null);
  const detailReport = detail.data || (lastDetail.current?.identity === detailIdentity ? lastDetail.current.report : null);
  const saved = Boolean(report?.saved || quota?.status !== "ready" || current.isError || actionError);
  const busy = quotaLoading || quotaRefreshing || scanning || refreshing;
  const accountLoading = !quota && busy && !quotaError;
  const currentLoading = !report && !current.isError && (accountLoading || busy || enabled && current.isPending);
  const historyLoading = !historyReport && !history.isError && (accountLoading || busy || enabled && history.isPending);
  const detailLoading = !detailReport && !detail.isError && (accountLoading || busy || enabled && detail.isPending);
  const basis = t(mode === "current" ? saved ? "quota:currentPriceConversionAtThatReading" : "quota:recalculateAtCurrentPrices" : "quota:savedPriceEstimate");
  let status = busy ? t(scanning || refreshing ? "quota:scanningNewLogsAndRefreshingQuota" : "quota:readingAccountQuota") : currentLoading ? t(quota?.status === "ready" ? "quota:calculatingCurrentCycleQuota" : "quota:readingTheLastSavedConversion")
    : report?.status === "ready" ? [saved && historyContext({ ...quota, ...report, status: quota?.status }), saved && t("quota:lastSavedConversion"), t("quota:quotaReadAt", { plan: planLabel(report), time: valueTime(report.fetched_at), basis }), saved && t("quota:amountsAndPercentagesRemainAsRead")].filter(Boolean).join(" · ")
      : systemMessage(report?.message || quota?.message) || current.error?.message || quotaError?.message || t("quota:quotaUnavailable");
  if (quota?.archive_status === "error" || report?.archive_status === "error") status += ` · ${t("quota:readingArchiveError")}`;
  if (quota?.value_history_status === "error" || report?.value_history_status === "error") status += ` · ${t("quota:quotaValueHistoryCouldNotBeSaved")}`;
  const displayedPage = historyReport?.status === "ready" ? Math.floor(historyReport.offset / 20) : page;
  const cycles = historyReport?.status === "ready" ? historyReport.cycles.filter(cycle => !cycle.is_current) : [];
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
      <div className="panel-heading quota-value-heading"><div className="quota-value-window-title"><h2 id="quotaValueTitle">{t(saved ? "quota:lastSavedConversion" : "quota:currentCycleConversion")}</h2><QuotaValueTooltip label={t(saved ? "quota:lastSavedConversion" : "quota:currentCycleConversion")} paragraphs={[t("quota:conversionRangeDescription"), status]} /></div><div className="quota-value-actions"><label className="price-mode-control"><span>{t("quota:pricingBasis")}</span><select id="quotaValuePriceMode" value={mode} disabled={busy} onChange={event => { setSelection(null); setPage(0); setRange({ priceMode: event.target.value }); }}><option value="snapshot">{t("quota:savedPriceEstimate")}</option><option value="current">{t("quota:recalculateAtCurrentPrices")}</option></select></label><button type="button" id="refreshQuotaValueButton" className="button" disabled={busy} onClick={refresh}>{t(refreshing ? "quota:refreshing" : quotaLoading || quotaRefreshing ? "quota:reading" : "quota:refreshAndConvert")}{busy && <UsageSkeleton className="usage-inline-skeleton" style={{ display: "inline-block", width: 24, height: 8, marginLeft: 8, verticalAlign: "middle" }} />}</button></div></div>
      <HistoryNotice quota={quota} />
      <p id="quotaValueStatus" className="sr-only" role="status">{status}</p>
      {actionError && <ErrorNotice error={actionError} />}{current.error && report && <ErrorNotice error={current.error} />}
    </section>
    <div id="quotaValueWindows" className="quota-value-windows" aria-busy={busy || current.isFetching}>{currentLoading ? (quota?.windows?.length ? quota.windows : [null, null]).map((window, index) => <QuotaValueCardSkeleton key={index} window={window} />) : report?.windows?.length ? report.windows.map((window, index) => <QuotaValueCard key={`${window.limit_id}-${window.slot}-${index}`} window={window} report={report} saved={saved} />) : <div className="panel"><EmptyState>{systemMessage(report?.message || quota?.message) || current.error?.message || quotaError?.message || t("quota:noConvertiblePercentageQuotaWindowsWereReturned")}</EmptyState></div>}</div>
    <LoadingStatus loading={historyLoading}>{t("quota:readingSavedAccountHistory")}</LoadingStatus>
    <section id="quotaValueHistoryPanel" className="panel quota-value-history" aria-labelledby="quotaValueHistoryTitle" aria-busy={busy || history.isFetching}>
      <div className="panel-heading"><h2 id="quotaValueHistoryTitle">{t("quota:quotaValueHistory")}</h2></div>
      <ErrorNotice error={history.error} />
      <div className="table-wrap quota-value-history-table-wrap"><table className="quota-value-history-table"><thead><tr>{historyHeaders.map(header => <th scope="col" key={header}>{t(header)}</th>)}</tr></thead><tbody id="quotaValueHistoryTable">{historyLoading ? <UsageTableSkeleton columns={historyHeaders.length} /> : cycles.map(cycle => {
        const selected = cycle.id === selectedID;
        return <tr key={cycle.id} className={selected ? "selected" : undefined}>
          <td><strong>{quotaWindowLabel(cycle)}</strong><small>{planLabel(cycle)}</small></td>
          <td>{valueTime(cycle.cycle_start_at)}</td>
          <td className="quota-value-primary">{percent(cycle.used_percent)}</td><td className="quota-value-primary">{valueMoney(cycle.total?.api_usd_known)}{cycle.total?.unknown_price_calls > 0 && <small className="unknown">{t("quota:knownAmountsOnly")}</small>}</td><td>{valueTime(cycle.fetched_at)}</td><td>{valueMoney(cycle.usd_per_percent)}</td><td>{valueMoney(cycle.full_quota_usd)}</td><td>{formatNumber(cycle.observation_count)}</td>
          <td><button type="button" className="button ghost" disabled={busy || history.isFetching} aria-controls="quotaValueHistoryDetail" aria-expanded={selected} onClick={event => { detailTrigger.current = event.currentTarget; setSelection(selected ? null : { identity: historyIdentity, id: cycle.id }); }}>{t(selected ? "quota:hideDetails" : "quota:viewReadings")}</button></td>
        </tr>;
      })}{!historyLoading && !cycles.length && <tr><td colSpan="9" className="empty-state">{systemMessage(historyReport?.message || quota?.message) || history.error?.message || quotaError?.message || t("quota:noSavedCycles")}</td></tr>}</tbody></table></div>
      <Pager page={displayedPage} pages={Math.ceil((historyReport?.total || 0) / 20)} loading={historyLoading} disabled={busy || history.isFetching} onPage={next => { setSelection(null); setPage(next); }} />
    </section>
    {selectedID != null && <><LoadingStatus loading={detailLoading}>{t("quota:readingSavedCycleSnapshots")}</LoadingStatus><section ref={detailPanel} id="quotaValueHistoryDetail" className="panel quota-value-history-detail" aria-labelledby="quotaValueHistoryDetailTitle" aria-busy={busy || detail.isFetching} tabIndex={-1}>
      <div className="panel-heading"><h2 id="quotaValueHistoryDetailTitle">{detailReport ? t("quota:windowReadingDetails", { window: quotaWindowLabel(detailReport.cycle) }) : t("quota:cycleReadingDetails")}</h2><button type="button" className="button ghost" onClick={closeDetail}>{t("quota:hideDetails")}</button></div>
      <p id="quotaValueHistoryDetailStatus" className="fine-print" role="status">{detailLoading ? <UsageSkeleton className="usage-line-skeleton" /> : detailReport ? t("quota:cycleReadingSummary", { context: historyContext({ ...quota, ...detailReport, status: quota?.status }), start: valueTime(detailReport.cycle.cycle_start_at), reset: valueTime(detailReport.cycle.resets_at), count: detailReport.observations.length, cycle: t(quota?.status === "ready" && detailReport.cycle.is_current ? "quota:currentCycle" : "quota:historicalReadingWarning") }) : ""}</p>
      <ErrorNotice error={detail.error} />
      {detailLoading ? <UsageSkeleton className="quota-usage-chart-skeleton" /> : detailReport && <QuotaUsageChart key={`chart:${detailIdentity}`} observations={detailReport.observations} />}
      {detailReport && <details key={`list:${detailIdentity}`} className="quota-value-reading-list"><summary>{t("quota:readingList")}</summary>
      <div className="table-wrap quota-value-observations-wrap"><table><thead><tr>{observationHeaders.map(header => <th scope="col" key={header}>{t(header)}</th>)}</tr></thead><tbody id="quotaValueObservationTable">{detailLoading ? <UsageTableSkeleton columns={observationHeaders.length} /> : (detailReport?.observations || []).map((row, index) => <tr key={`${row.fetched_at}-${index}`}><td>{valueTime(row.fetched_at)}</td><td>{percent(row.used_percent)}</td><td>{valueMoney(row.total?.api_usd_known)}</td><td>{valueMoney(row.usd_per_percent)}</td><td>{valueMoney(row.full_quota_usd)}</td><td>{valueMoney(row.remaining_quota_usd)}</td><td className="quota-value-observation-note">{observationNotes(row) || "—"}</td></tr>)}{!detailLoading && detailReport && !detailReport.observations.length && <tr><td colSpan="7" className="empty-state">{t("quota:noSnapshotsAreAvailableForThisCycle")}</td></tr>}</tbody></table></div>
      </details>}
    </section></>}
  </section>;
}

