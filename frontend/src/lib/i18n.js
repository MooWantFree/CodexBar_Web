import {useSyncExternalStore} from 'react';
import {createInstance} from 'i18next';
import {initReactI18next, useTranslation} from 'react-i18next';

export const supportedLocales = ['en', 'ja', 'zh'];
const resources = {};
for (const [path, catalog] of Object.entries(import.meta.glob('../locales/*/*.json', {eager: true, import: 'default'}))) {
  const [, language, namespace] = /\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path);
  (resources[language] ||= {})[namespace] = catalog;
}

export function detectLocale(browser = globalThis.navigator) {
  const preferences = browser?.languages?.length ? browser.languages : [browser?.language];
  return Array.from(preferences, language => String(language || '').toLowerCase().split(/[-_]/)[0])
    .find(language => supportedLocales.includes(language)) || 'en';
}

export const LANGUAGE_STORAGE_KEY = 'codex-token-report.language';
const validPreferences = new Set(['auto', ...supportedLocales]);
const normalizePreference = value => validPreferences.has(value) ? value : 'auto';
function readPreference() {
  try { return normalizePreference(globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY)); }
  catch { return 'auto'; }
}

let preference = readPreference();
export let locale = preference === 'auto' ? detectLocale() : preference;
export const i18n = createInstance();
i18n.use(initReactI18next).init({
  resources,
  lng: locale,
  supportedLngs: supportedLocales,
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: Object.keys(resources.en),
  keySeparator: false,
  initAsync: false,
  // React escapes rendered text. Interpolated external values remain literal.
  interpolation: {escapeValue: false, skipOnVariables: true},
  react: {useSuspense: false},
});

const subscribers = new Set();
const subscribe = listener => { subscribers.add(listener); return () => subscribers.delete(listener); };
const notify = () => { for (const listener of subscribers) listener(); };
const currentPreference = () => preference;
export const getLanguagePreference = currentPreference;
export const useLanguagePreference = () => useSyncExternalStore(subscribe, currentPreference, currentPreference);
export function useLocale() {
  const {i18n: instance} = useTranslation(undefined, {i18n});
  return instance.resolvedLanguage || instance.language;
}

function syncLocale(language) {
  locale = language;
  if (globalThis.document?.documentElement) document.documentElement.lang = language;
}
i18n.on('languageChanged', syncLocale);
syncLocale(locale);

function updatePreference(value) {
  const next = normalizePreference(value);
  const changed = preference !== next;
  preference = next;
  const nextLocale = next === 'auto' ? detectLocale() : next;
  if (locale !== nextLocale) void i18n.changeLanguage(nextLocale);
  if (changed) notify();
}

export function setLanguagePreference(value) {
  const next = normalizePreference(value);
  try { globalThis.localStorage?.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* Keep the choice usable without storage. */ }
  updatePreference(next);
}

if (globalThis.window) {
  window.addEventListener('storage', event => {
    if (event.key === LANGUAGE_STORAGE_KEY || event.key === null) updatePreference(event.key === null ? 'auto' : event.newValue);
  });
  window.addEventListener('languagechange', () => { if (preference === 'auto') updatePreference('auto'); });
}

// Non-component formatters and API error handling use the same initialized instance.
export const t = (key, params = {}) => String(i18n.t(key, {...params}));
