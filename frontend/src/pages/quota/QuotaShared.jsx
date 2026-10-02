import { t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatDateTime, formatNumber, money } from "../../lib/format";
import "../quotaMessages";

const plans = { free: "Free", go: "Go", plus: "Plus", pro: "Pro", prolite: "Pro Lite", team: "Team", business: "Business", enterprise: "Enterprise", edu: "Edu" };
export const planLabel = quota => plans[quota?.plan_type] || quota?.plan_type || t("Unknown plan");
export const historyAvailable = quota => quota?.history_mode !== "unavailable" && Boolean(quota?.reset_history_scope);
export const valueTime = value => formatDateTime(value, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const percent = value => value == null || !Number.isFinite(Number(value)) ? t("Unknown") : `${formatNumber(Number(Number(value).toFixed(2)))}%`;
export const valueMoney = value => value == null ? t("Unknown") : money(value);

export function historyContext(quota) {
  const account = systemMessage(quota?.history_label) || systemMessage(quota?.history_mode === "offline" ? "上次保存的账号" : "当前账号");
  return quota?.history_mode === "offline" ? t("Offline history · {account}", { account })
    : quota?.status !== "ready" ? t("{account} · local history (live quota unavailable)", { account })
      : t("{account} · saved history", { account });
}

export function HistoryNotice({ quota }) {
  if (!historyAvailable(quota) || (quota.status === "ready" && quota.history_mode !== "offline")) return null;
  return <div className="reset-selection unknown" role="status"><div><strong>{historyContext(quota)}</strong><br />{t("Last successful read: {time}. Saved records retain their amounts and percentages from that reading.", { time: valueTime(quota.history_fetched_at || quota.fetched_at) })}</div></div>;
}

