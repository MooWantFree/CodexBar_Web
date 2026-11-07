import { systemMessage } from "../../lib/systemMessages";
import { useEffect, useRef, useState } from "react";
import { useDashboard } from "../../context/DashboardContext";
import { t } from "../../lib/i18n";

import { formatDateTime, formatNumber, quotaWindowLabel } from "../../lib/format";
import { LoadingStatus, UsageSkeleton } from "../../components/UsageSkeleton";
import { planLabel, valueTime, percent } from "./QuotaShared";

export function QuotaSidebar() {
  const { quota, quotaLoading, quotaRefreshing, quotaError, refreshQuota, scanning } = useDashboard();
  const dialog = useRef(null);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 60000); return () => clearInterval(timer); }, []);
  useEffect(() => { dialog.current?.close?.(); setOpen(false); }, [quota?.reset_history_scope, quota?.status]);
  const ready = quota?.status === "ready";
  const windows = ready ? quota.windows || [] : [];
  const credits = quota?.reset_credits || [];
  const count = ready ? Number(quota.reset_credits_available) || 0 : 0;
  const urgent = ready && credits.some(credit => credit.expires_at != null && credit.expires_at * 1000 > now && credit.expires_at * 1000 - now <= 72 * 60 * 60 * 1000);
  const notices = ready ? [
    !windows.length && t("quota:noPercentageQuotaWasReturned"),
    quota.archive_status === "error" && t("quota:rawQuotaReadingsCouldNotBeSaved"),
    quota.reset_history_status === "error" && t("quota:resetRecordsCouldNotBeSaved"),
    quota.value_history_status === "error" && t("quota:readingHistorySaveError"),
  ].filter(Boolean) : [systemMessage(quota?.message) || quotaError?.message || t("quota:quotaUnavailable")];
  const resetLabel = t("quota:availableQuotaResets", { count });
  const busy = quotaLoading || quotaRefreshing || scanning;
  const loading = !quota && busy && !quotaError;
  function showCredits() {
    dialog.current?.showModal?.();
    setOpen(true);
  }
  function closeCredits() { dialog.current?.close?.(); setOpen(false); }
  return <><LoadingStatus loading={loading}>{t("quota:readingAccountQuota")}</LoadingStatus><section id="quotaPanel" className="sidebar-quota" aria-labelledby="quotaTitle" aria-busy={busy}>
    <div className="quota-heading"><h2 id="quotaTitle">{t("quota:currentAccount")}</h2><span id="quotaPlan" className={`quota-plan${loading ? " quota-skeleton" : ""}`} aria-hidden={loading || undefined} title={loading ? undefined : ready ? planLabel(quota) : t("quota:liveQuotaUnavailable")}>{loading ? "" : ready ? planLabel(quota) : t("quota:liveQuotaUnavailable")}</span></div>
    <div id="quotaWindows" className="quota-grid">
      {loading ? [0, 1].map(index => <div className="quota-skeleton-window" key={index} aria-hidden="true"><div className="quota-window-heading"><span className="quota-skeleton skeleton-label" /><span className="quota-skeleton skeleton-value" /></div><span className="quota-skeleton skeleton-bar" /><span className="quota-skeleton skeleton-reset" /></div>)
        : windows.length ? windows.map((window, index) => {
          const remaining = window.remaining_percent;
          const label = quotaWindowLabel(window);
          const reset = window.resets_at == null ? t("quota:resetTimeUnavailable") : t("quota:resetsAt", { time: formatDateTime(window.resets_at * 1000, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) });
          return <article className={`quota-window${remaining != null && remaining <= 20 ? " low" : ""}`} key={`${window.limit_id}-${window.slot}-${index}`}>
            <div className="quota-window-heading"><p>{t("quota:remainingLabel", { window: label })}</p><strong>{remaining == null ? "—" : percent(remaining)}</strong></div>
            {remaining != null && <progress max="100" value={remaining} aria-label={t("quota:remainingAccessibleLabel", { window: label, percent: percent(remaining) })} />}
            <small title={window.resets_at == null ? reset : t("quota:resetsAt", { time: valueTime(window.resets_at * 1000) })}>{reset}</small>
          </article>;
        }) : <div className="quota-empty">{t("quota:quotaUnavailable")}</div>}
    </div>
    {loading ? <p id="quotaStatus" className="fine-print" aria-hidden="true"><UsageSkeleton className="usage-line-skeleton" /></p> : (notices.length > 0 || count > 0) && <p id="quotaStatus" className={`fine-print${quota?.status === "error" ? " error-text" : ""}`} aria-live="polite" title={[count > 0 && resetLabel, ...notices].filter(Boolean).join(" · ")}>
      {count > 0 && <><button type="button" className={`quota-reset-trigger${urgent ? " expiring" : ""}`} aria-controls="quotaResetPopover" aria-haspopup="dialog" aria-expanded={open} onClick={showCredits}>{resetLabel}</button>{notices.length > 0 ? " · " : ""}</>}{notices.join(" · ")}
    </p>}
    <dialog ref={dialog} id="quotaResetPopover" className="quota-reset-popover" aria-label={t("quota:availableResetExpirationDates")} onClose={() => setOpen(false)} onCancel={() => setOpen(false)} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeCredits();
    }}>
      <div className="quota-reset-popover-heading"><strong className="quota-reset-popover-title">{t("quota:availableResetExpirationDates")}</strong><button type="button" className="quota-reset-close" aria-label={t("quota:closeExpirationDates")} onClick={closeCredits}>×</button></div>
      {credits.length > 0 && <ul>{credits.map((credit, index) => <li key={`${credit.title}-${index}`}><strong>{credit.title || t("quota:quotaReset", { index: formatNumber(index + 1) })}</strong><span>{credit.expires_at == null ? t(credit.expiry_known ? "quota:noExpirationDate" : "quota:expirationDateUnavailable") : t("quota:expires", { time: formatDateTime(credit.expires_at * 1000, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) })}</span></li>)}</ul>}
      {count > credits.length ? <p>{t("quota:expirationDatesForResetsAreUnavailable", { count: count - credits.length })}</p> : !quota?.reset_credits_details_available && <p>{t("quota:resetExpirationDatesAreUnavailable")}</p>}
    </dialog>
    <button id="refreshQuotaButton" type="button" className={`button quota-refresh${urgent ? " expiring" : ""}`} disabled={busy} onClick={() => refreshQuota().catch(() => {})}>{t(busy ? "quota:reading" : "quota:refreshQuota")}{busy && <UsageSkeleton className="usage-inline-skeleton" style={{ display: "inline-block", width: 24, height: 8, marginLeft: 8, verticalAlign: "middle" }} />}</button>
  </section></>;
}

