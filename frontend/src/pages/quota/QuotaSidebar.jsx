import { useEffect, useRef, useState } from "react";
import { useDashboard } from "../../context/DashboardContext";
import { t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatDateTime, formatNumber, quotaWindowLabel } from "../../lib/format";
import { planLabel, valueTime, percent } from "./QuotaShared";
import "../quotaMessages";

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
  const count = ready ? quota.reset_credits_available || 0 : 0;
  const urgent = ready && credits.some(credit => credit.expires_at != null && credit.expires_at * 1000 > now && credit.expires_at * 1000 - now <= 72 * 60 * 60 * 1000);
  const notices = ready ? [
    !windows.length && t("No percentage quota was returned"),
    quota.archive_status === "error" && t("Raw quota readings could not be saved"),
    quota.reset_history_status === "error" && t("Reset records could not be saved"),
    quota.value_history_status === "error" && t("Quota value history could not be saved; this reading remains available"),
  ].filter(Boolean) : [systemMessage(quota?.message) || quotaError?.message || t("Quota unavailable")];
  const resetLabel = t("Available quota resets: {count}", { count: formatNumber(count) });
  const busy = quotaLoading || quotaRefreshing || scanning;
  function showCredits() {
    dialog.current?.showModal?.();
    setOpen(true);
  }
  function closeCredits() { dialog.current?.close?.(); setOpen(false); }
  return <section id="quotaPanel" className="sidebar-quota" aria-labelledby="quotaTitle" aria-busy={busy}>
    <div className="quota-heading"><h2 id="quotaTitle">{t("Current account")}</h2><span id="quotaPlan" className={`quota-plan${!quota && quotaLoading ? " quota-skeleton" : ""}`} title={ready ? planLabel(quota) : t("Live quota unavailable")}>{!quota && quotaLoading ? "" : ready ? planLabel(quota) : t("Live quota unavailable")}</span></div>
    <div id="quotaWindows" className="quota-grid">
      {!quota && quotaLoading ? <div className="quota-skeleton-window" aria-label={t("Reading account quota…")}><div className="quota-window-heading"><span className="quota-skeleton skeleton-label" /><span className="quota-skeleton skeleton-value" /></div><span className="quota-skeleton skeleton-bar" /><span className="quota-skeleton skeleton-reset" /></div>
        : windows.length ? windows.map((window, index) => {
          const remaining = window.remaining_percent;
          const label = quotaWindowLabel(window);
          const reset = window.resets_at == null ? t("Reset time unavailable") : t("Resets at {time}", { time: formatDateTime(window.resets_at * 1000, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) });
          return <article className={`quota-window${remaining != null && remaining <= 20 ? " low" : ""}`} key={`${window.limit_id}-${window.slot}-${index}`}>
            <div className="quota-window-heading"><p>{t("{window} · remaining", { window: label })}</p><strong>{remaining == null ? "—" : percent(remaining)}</strong></div>
            {remaining != null && <progress max="100" value={remaining} aria-label={t("{window} remaining {percent}", { window: label, percent: percent(remaining) })} />}
            <small title={window.resets_at == null ? reset : t("Resets at {time}", { time: valueTime(window.resets_at * 1000) })}>{reset}</small>
          </article>;
        }) : <div className="quota-empty">{t("Quota unavailable")}</div>}
    </div>
    {(notices.length > 0 || count > 0) && <p id="quotaStatus" className={`fine-print${quota?.status === "error" ? " error-text" : ""}`} aria-live="polite" title={[count > 0 && resetLabel, ...notices].filter(Boolean).join(" · ")}>
      {count > 0 && <><button type="button" className={`quota-reset-trigger${urgent ? " expiring" : ""}`} aria-controls="quotaResetPopover" aria-haspopup="dialog" aria-expanded={open} onClick={showCredits}>{resetLabel}</button>{notices.length > 0 ? " · " : ""}</>}{notices.join(" · ")}
    </p>}
    <dialog ref={dialog} id="quotaResetPopover" className="quota-reset-popover" aria-label={t("Available reset expiration dates")} onClose={() => setOpen(false)} onCancel={() => setOpen(false)} onClick={event => {
      if (event.target !== event.currentTarget) return;
      const rect = event.currentTarget.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeCredits();
    }}>
      <div className="quota-reset-popover-heading"><strong className="quota-reset-popover-title">{t("Available reset expiration dates")}</strong><button type="button" className="quota-reset-close" aria-label={t("Close expiration dates")} onClick={closeCredits}>×</button></div>
      {credits.length > 0 && <ul>{credits.map((credit, index) => <li key={`${credit.title}-${index}`}><strong>{credit.title || t("Quota reset {index}", { index: formatNumber(index + 1) })}</strong><span>{credit.expires_at == null ? t(credit.expiry_known ? "No expiration date" : "Expiration date unavailable") : t("Expires: {time}", { time: formatDateTime(credit.expires_at * 1000, { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" }) })}</span></li>)}</ul>}
      {count > credits.length ? <p>{t("Expiration dates for {count} resets are unavailable.", { count: formatNumber(count - credits.length) })}</p> : !quota?.reset_credits_details_available && <p>{t("Reset expiration dates are unavailable.")}</p>}
    </dialog>
    <button id="refreshQuotaButton" type="button" className={`button quota-refresh${urgent ? " expiring" : ""}`} disabled={busy} onClick={() => refreshQuota().catch(() => {})}>{t(busy ? "Reading…" : "Refresh quota")}</button>
  </section>;
}

