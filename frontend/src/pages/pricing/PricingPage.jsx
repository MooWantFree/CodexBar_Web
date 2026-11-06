import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPut } from "../../lib/api";
import { t } from "../../lib/i18n";
import { systemMessage } from "../../lib/systemMessages";
import { formatNumber } from "../../lib/format";
import { ErrorNotice } from "../../components/Shared";
import { LoadingStatus, UsageSkeleton, UsageTableSkeleton } from "../../components/UsageSkeleton";
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
  return <tr data-model={item.model}><td><strong>{item.display_name || item.model}</strong>{item.display_name && item.display_name !== item.model && <small>{item.model}</small>}</td>{priceFields.map(field => <td key={field}><input aria-label={`${item.model} ${t(fieldLabels[field])}`} type="number" min="0" step="any" value={fields[field]} placeholder={field === "cache_write" || field === "api_fast_multiplier" ? t("Unknown") : undefined} disabled={mutation.isPending} onChange={event => setFields(values => ({ ...values, [field]: event.target.value }))} /></td>)}<td><span className={`coverage${item.override ? " partial" : ""}`}>{item.override ? t("Manual override") : item.official ? item.source === "models_dev" ? "models.dev" : t("Cached / built-in") : t("Unpriced")}</span></td><td className="price-actions"><button type="button" className="button" disabled={mutation.isPending} onClick={() => save("save")}>{t(mutation.isPending && mutation.variables === "save" ? "Saving…" : "Save")}</button><button type="button" className="button ghost" disabled={mutation.isPending || !item.override} onClick={() => save("restore")}>{t("Restore")}</button>{mutation.isPending && <UsageSkeleton className="usage-inline-skeleton" />}<LoadingStatus loading={mutation.isPending} />{(validationError || mutation.error) && <span className="error-text" role="alert">{(validationError || mutation.error).message}</span>}</td></tr>;
}

export function PricingPage() {
  const client = useQueryClient();
  const [notice, setNotice] = useState(null);
  const pricing = useQuery({ queryKey: ["pricing"], queryFn: ({ signal }) => apiGet("/api/pricing", { signal }) });
  const refresh = useMutation({ mutationFn: () => apiPost("/api/pricing/refresh"), onSuccess: async result => {
    const failed = Object.keys(result.failed_models || {}).length;
    setNotice({ message: t(failed ? "Updated {count} models; {failed} failed and retained their previous cache." : "Updated {count} models.", { count: formatNumber((result.updated_models || []).length), failed: formatNumber(failed) }), error: failed > 0 });
    await client.invalidateQueries({ predicate: query => query.queryKey[0] !== "quota" });
  }, onError: error => setNotice({ message: error.message, error: true }) });
  const data = pricing.data;
  const initialLoading = pricing.isPending && !data;
  const loading = pricing.isFetching || refresh.isPending;
  const status = refresh.isPending ? t("Fetching OpenAI model prices from models.dev…") : notice?.message || (data?.refresh_error ? t("Some prices could not be refreshed: {error}", { error: systemMessage(data.refresh_error) }) : initialLoading ? t("Reading local prices…") : "");
  return <section className="page" data-page="pricing"><section className="panel price-panel">
    <div className="panel-heading"><h2>{t("Model price management")}</h2><button type="button" id="refreshPricingButton" className="button" disabled={initialLoading || refresh.isPending} onClick={() => { setNotice(null); refresh.mutate(); }}>{t(refresh.isPending ? "Refreshing…" : "Refresh prices")}</button></div>
    <div className="price-layout"><div className="price-facts" aria-busy={initialLoading}><div><span>{t("Price date")}</span><strong>{initialLoading ? <UsageSkeleton className="usage-line-skeleton" style={{width: 88}} /> : data?.as_of || "—"}</strong></div><div><span>{t("Last fetched")}</span><strong>{initialLoading ? <UsageSkeleton className="usage-line-skeleton" style={{width: 140}} /> : data?.fetched_at ? valueTime(data.fetched_at) : t("Built-in prices")}</strong></div></div><div>
      <p id="pricingStatus" className={`${status || loading ? "fine-print" : "sr-only"}${notice?.error || data?.refresh_error ? " error-text" : ""}`} role="status">{status}{loading && <UsageSkeleton className="usage-inline-skeleton" />}</p><ErrorNotice error={pricing.error} />
      <p className="fine-print">{t("Prices are USD per 1M tokens. Manual prices take priority and survive refreshes.")}</p>
      <p className="fine-print">{t("API-equivalent costs are not subscription bills. Fast uses 2.5× the Standard subscription quota; API price multipliers do not indicate quota usage.")}</p>
      <a className="source-link" href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noreferrer">{t("OpenAI official pricing ↗")}</a>
    </div></div>
    <div className="table-wrap pricing-table-wrap" aria-busy={initialLoading}><table className="pricing-table"><thead><tr>{["Model", "Input", "Cached", "Cache write", "Output", "Fast multiplier", "Status", "Actions"].map(header => <th key={header}>{t(header)}</th>)}</tr></thead><tbody id="pricingTable">{initialLoading ? <UsageTableSkeleton columns={8} /> : (data?.models || []).map(item => <PriceRow key={`${item.model}:${JSON.stringify(item.effective)}:${Boolean(item.override)}`} item={item} onNotice={(message, error = false) => setNotice({ message, error })} />)}{!initialLoading && !data?.models?.length && <tr><td colSpan="8" className="empty-state">{t("No models available")}</td></tr>}</tbody></table></div>
  </section></section>;
}

