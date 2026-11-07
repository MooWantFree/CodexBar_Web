import {systemMessage} from './systemMessages';
import {t} from "./i18n";

async function request(path, method = 'GET', body, options = {}) {
  const response = await fetch(path, {
    method,
    ...(body !== undefined ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {}),
    ...options,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(systemMessage(payload?.detail) || t("common:requestFailed", {status: response.status}));
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const apiGet = (path, options) => request(path, 'GET', undefined, options);
export const apiPost = (path, body) => request(path, 'POST', body);
export const apiPut = (path, body) => request(path, 'PUT', body);
export const apiDelete = path => request(path, 'DELETE');
