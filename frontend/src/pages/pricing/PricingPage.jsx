import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDashboard } from "../../context/DashboardContext";
import { apiDelete, apiGet, apiPost, apiPut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatNumber } from "../../lib/format";
import { ErrorNotice } from "../../components/Shared";
import { valueTime } from "../quota/QuotaShared";
import "../quotaMessages";

const priceFields = ["input", "cached_input", "cache_write", "output", "api_fast_multiplier"];
const fieldLabels = { input: "Input", cached_input: "Cached", cache_write: "Cache write", output: "Output", api_fast_multiplier: "Fast multiplier" };

export function validatePriceValues(model, fields) {
  const values = Object.fromEntries(priceFields.map(field => [field, fields[field] === "" || fields[field] == null ? null : Number(fields[field])]));
  for (const field of ["input", "cached_input", "output"]) if (values[field] == null || !Number.isFinite(values[field]) || values[field] < 0) throw new Error(t("{model}: {field} must be a nonnegative number.", { model, field }));
  for (const field of ["cache_write", "api_fast_multiplier"]) if (values[field] != null && (!Number.isFinite(values[field]) || values[field] < 0)) throw new Error(t("{model}: {field} must be empty or a nonnegative number.", { model, field: field === "api_fast_multiplier" ? t("Fast multiplier") : field }));
  return values;
}

function PriceRow({ item, onNotice }) {
  const client = useQueryClient();
  const [fields, setFields] = useState(() => Object.fromEntries(priceFields.map(field => [field, item.effective?.[field] == null ? "" : String(item.effective[field])])));
  const [validationError, setValidationError] = useState(null);
  const mutation = useMutation({ mutationFn: async action => {
    const url = `/api/pricing/models/${encodeURIComponent(item.model)}/override`;
    return action === "restore" ? apiDelete(url) : apiPut(url, validatePriceValues(item.model, fields));
  }, onSuccess: async (_, action) => {
    onNotice(t(action === "restore" ? "Cached prices restored for {model}." : "Prices saved for {model}.", { model: item.model }));
    await client.invalidateQueries({ predicate: query => query.queryKey[0] !== "quota" });
  }, onError: error => onNotice(error.message, true) });
  function save(action) {
    setValidationError(null);
    if (action === "save") {
      try { validatePriceValues(item.model, fields); } catch (error) { setValidationError(error); onNotice(error.message, true); return; }
    }
    mutation.mutate(action);
  }
  return <tr data-model={item.model}><td><strong>{item.display_name || item.model}</strong><small>{item.model}</small></td>{priceFields.map(field => <td key={field}><input aria-label={`${item.model} ${t(fieldLabels[field])}`} type="number" min="0" step="any" value={fields[field]} placeholder={field === "cache_write" || field === "api_fast_multiplier" ? t("Unknown") : undefined} disabled={mutation.isPending} onChange={event => setFields(values => ({ ...values, [field]: event.target.value }))} /></td>)}<td><span className={`coverage${item.override ? " partial" : ""}`}>{item.override ? t("Manual override") : item.official ? item.source === "models_dev" ? "models.dev" : t("Cached / built-in") : t("Unpriced")}</span></td><td className="price-actions"><button type="button" className="button" disabled={mutation.isPending} onClick={() => save("save")}>{t(mutation.isPending && mutation.variables === "save" ? "Saving…" : "Save")}</button><button type="button" className="button ghost" disabled={mutation.isPending || !item.override} onClick={() => save("restore")}>{t("Restore")}</button>{(validationError || mutation.error) && <span className="error-text" role="alert">{(validationError || mutation.error).message}</span>}</td></tr>;
}

export function PricingPage() {
  const { timezone } = useDashboard();
  const client = useQueryClient();
  const [notice, setNotice] = useState(null);
  const pricing = useQuery({ queryKey: ["pricing"], queryFn: ({ signal }) => apiGet("/api/pricing", { signal }) });
  const refresh = useMutation({ mutationFn: () => apiPost("/api/pricing/refresh"), onSuccess: async result => {
    const failed = Object.keys(result.failed_models || {}).length;
    setNotice({ message: t(failed ? "Updated {count} models; {failed} failed and retained their previous cache." : "Updated {count} models.", { count: formatNumber((result.updated_models || []).length), failed: formatNumber(failed) }), error: failed > 0 });
    await client.invalidateQueries({ predicate: query => query.queryKey[0] !== "quota" });
  }, onError: error => setNotice({ message: error.message, error: true }) });
  const data = pricing.data;
  const status = refresh.isPending ? t("Fetching OpenAI model prices from models.dev…") : notice?.message || (data?.refresh_error ? t("Some prices could not be refreshed: {error}", { error: systemMessage(data.refresh_error) }) : data ? t(data.source === "models_dev" ? "Using cached models.dev prices; Fast multipliers are maintained separately." : data.source === "openai_docs" ? "Using the legacy official documentation cache; refreshing switches to models.dev." : "Using built-in prices; you can refresh prices manually.") : t("Reading local prices…"));
  return <section className="page" data-page="pricing"><section className="panel price-panel">
    <div className="panel-heading"><div><p className="eyebrow">{t("PRICING BASIS")}</p><h2>{t("Model price management")}</h2></div><button type="button" id="refreshPricingButton" className="button" disabled={refresh.isPending} onClick={() => { setNotice(null); refresh.mutate(); }}>{t(refresh.isPending ? "Refreshing…" : "Refresh prices")}</button></div>
    <div className="price-layout"><div className="price-facts"><div><span>{t("Price date")}</span><strong>{data?.as_of || "—"}</strong></div><div><span>{t("Last fetched")}</span><strong>{data?.fetched_at ? valueTime(data.fetched_at) : t("Built-in prices")}</strong></div><div><span>{t("Service tier")}</span><strong>{t("Per-request Standard / Fast")}</strong></div><div><span>{t("Timezone")}</span><strong>{timezone}</strong></div></div><div>
      <p id="pricingStatus" className={`fine-print${notice?.error || data?.refresh_error ? " error-text" : ""}`} role="status">{status}</p><ErrorNotice error={pricing.error} />
      <p className="fine-print">{t("All prices are USD per 1M tokens. Base prices come from models.dev; Fast multipliers are maintained separately. Manual values take priority over the cache and survive refreshes. Amounts are API-equivalent costs, not subscription bills.")}</p>
      <p className="fine-print">{t("Fast API surcharges are API-equivalent dollars: GPT-6.1 Sol uses a 2× multiplier. The client speed setting is a speed hint. Fast consumes 2.5× the subscription quota of Standard (+150%); dollar surcharges cannot determine actual quota percentages.")}</p>
      <a className="source-link" href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">{t("OpenAI official pricing ↗")}</a>
    </div></div>
    <div className="table-wrap pricing-table-wrap"><table className="pricing-table"><thead><tr>{["Model", "Input", "Cached", "Cache write", "Output", "Fast multiplier", "Status", "Actions"].map(header => <th key={header}>{t(header)}</th>)}</tr></thead><tbody id="pricingTable">{(data?.models || []).map(item => <PriceRow key={`${item.model}:${JSON.stringify(item.effective)}:${Boolean(item.override)}`} item={item} onNotice={(message, error = false) => setNotice({ message, error })} />)}{!data?.models?.length && <tr><td colSpan="8" className="empty-state">{t(pricing.isPending ? "Reading local prices…" : "No models available")}</td></tr>}</tbody></table></div>
  </section></section>;
}

