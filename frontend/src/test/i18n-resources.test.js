import {describe, expect, it} from 'vitest';
import wireMessages from '../locales/backend-messages.json';

const files = import.meta.glob('../locales/*/*.json', {eager: true, import: 'default'});
const resources = {};
for (const [path, catalog] of Object.entries(files)) {
  const [, language, namespace] = /\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path);
  (resources[language] ||= {})[namespace] = catalog;
}
const placeholders = value => [...value.matchAll(/\{\{(\w+)(?:,[^}]+)?\}\}/g)].map(match => match[1]).sort();
const baseKey = key => key.replace(/_(one|other)$/, '');

describe('translation resources', () => {
  it('maps backend messages only to existing translation keys', () => {
    for (const fullKey of [...Object.values(wireMessages.exact), ...wireMessages.patterns.map(entry => entry.key)]) {
      const [namespace, key] = fullKey.split(':');
      expect(Object.hasOwn(resources.en[namespace], key), fullKey).toBe(true);
    }
  });
  it('provides all namespaces, keys and interpolation parameters in every supported language', () => {
    expect(Object.keys(resources).sort()).toEqual(['en', 'ja', 'zh']);
    for (const language of ['ja', 'zh']) {
      expect(Object.keys(resources[language]).sort()).toEqual(Object.keys(resources.en).sort());
      for (const [namespace, english] of Object.entries(resources.en)) {
        const catalog = resources[language][namespace];
        expect([...new Set(Object.keys(catalog).map(baseKey))].sort(), `${language}/${namespace}`)
          .toEqual([...new Set(Object.keys(english).map(baseKey))].sort());
        for (const [key, value] of Object.entries(catalog)) {
          const reference = english[key] ?? english[baseKey(key) + '_other'];
          expect(typeof value).toBe('string');
          expect(value.trim().length).toBeGreaterThan(0);
          expect(placeholders(value), `${language}/${namespace}:${key}`).toEqual(placeholders(reference));
        }
      }
    }
  });

  it('resolves every literal semantic key in application code without component registration', () => {
    const sources = import.meta.glob('../**/*.{js,jsx}', {eager: true, query: '?raw', import: 'default'});
    for (const [path, source] of Object.entries(sources)) {
      if (path.startsWith('./') || path.includes('/test/')) continue;
      expect(source, path).not.toMatch(/\baddMessages\s*\(/);
      for (const [, namespace, key] of source.matchAll(/['"]([a-z]+):([a-zA-Z0-9]+)['"]/g)) {
        expect(resources.en[namespace], `${path}: ${namespace}`).toBeDefined();
        const catalog = resources.en[namespace];
        expect(Object.hasOwn(catalog, key) || Object.hasOwn(catalog, key + '_other'), `${path}: ${namespace}:${key}`).toBe(true);
      }
      for (const [, key] of source.matchAll(/\bt\(\s*['"]([^'"]+)['"]/g)) {
        expect(key, path).toMatch(/^[a-z]+:[a-zA-Z0-9]+$/);
      }
    }
  });
});
