import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

async function loadI18n(languages, language = languages?.[0]) {
  vi.resetModules();
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages);
  vi.spyOn(navigator, 'language', 'get').mockReturnValue(language);
  return import('../lib/i18n');
}

let languageListeners = [];
beforeEach(() => {
  localStorage.clear();
  document.documentElement.lang = 'en';
  languageListeners = [];
  const addEventListener = window.addEventListener.bind(window);
  vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    if (type === 'storage' || type === 'languagechange') languageListeners.push([type, listener, options]);
    addEventListener(type, listener, options);
  });
});
afterEach(() => {
  for (const listener of languageListeners) window.removeEventListener(...listener);
  vi.restoreAllMocks();
});

describe('browser language selection', () => {
  it.each([
    [['ja-JP', 'en-US'], 'ja-JP', 'ja'],
    [['en-GB', 'ja-JP'], 'en-GB', 'en'],
    [['fr-FR', 'ja-JP', 'en-US'], 'fr-FR', 'ja'],
    [['zh-TW', 'en-US'], 'zh-TW', 'zh'],
    [['zh-CN'], 'zh-CN', 'zh'],
    [['zh-Hans-CN'], 'zh-Hans-CN', 'zh'],
    [['zh-Hant-TW'], 'zh-Hant-TW', 'zh'],
    [['ja_jp'], 'ja_jp', 'ja'],
    [['JA-jp'], 'JA-jp', 'ja'],
    [['fr-FR', 'zh-TW'], 'fr-FR', 'zh'],
    [['fr-FR', 'ko-KR'], 'fr-FR', 'en'],
    [[], 'ja-JP', 'ja'],
    [undefined, undefined, 'en'],
  ])('matches %j with fallback language %s to %s', async (languages, language, expected) => {
    const { locale, detectLocale } = await loadI18n(languages, language);
    expect(locale).toBe(expected);
    expect(document.documentElement.lang).toBe(expected);
    expect(detectLocale({ languages, language })).toBe(expected);
  });

  it('defaults to English when browser metadata is unavailable', async () => {
    const { detectLocale } = await loadI18n([]);
    expect(detectLocale(null)).toBe('en');
    expect(detectLocale({})).toBe('en');
  });
});

describe('message catalogs', () => {
  it('selects Japanese and falls back to English for a missing Japanese key', async () => {
    const { addMessages, t } = await loadI18n(['ja-JP']);
    addMessages({ en: { '测试': 'English {count}', '仅英语': 'English only' }, ja: { '测试': '日本語 {count}' } });
    expect(t('测试', { count: 3 })).toBe('日本語 3');
    expect(t('仅英语')).toBe('English only');
    expect(t('unregistered message')).toBe('unregistered message');
    expect(t('模型定价')).toBe('モデル料金');
  });

  it('interpolates literal values without recursively interpreting their placeholders', async () => {
    const { addMessages, t } = await loadI18n(['en-GB']);
    addMessages({ en: { '模板': '{value} / {count} / {missing}' } });
    expect(t('模板', { value: '<script>{count}</script>', count: 0 })).toBe('<script>{count}</script> / 0 / {missing}');
    expect(t('模板', Object.create({ value: 'inherited', count: 10 }))).toBe('{value} / {count} / {missing}');
  });

  it('does not resolve inherited catalog properties as messages', async () => {
    const { t, addMessages } = await loadI18n(['en-US']);
    expect(t('constructor')).toBe('constructor');
    addMessages({ en: JSON.parse('{"__proto__":"literal key"}') });
    expect(t('__proto__')).toBe('literal key');
  });
});

describe('localized formatting', () => {
  it.each([
    ['en-US', 'unknown for 2 calls', 'Fast multiplier', '2 Fast calls'],
    ['zh-TW', '有 2 次调用', 'Fast 倍率', '2 次 Fast 调用'],
    ['ja-JP', '2 回の呼び出し', 'Fast 倍率', '2 回の Fast 呼び出し'],
  ])('localizes the unknown amount explanation in %s', async (language, calls, reason, fastCalls) => {
    await loadI18n([language]);
    const {unknownCostTitle} = await import('../components/CostValue');
    const row = {api_usd_known: 0, unknown_price_calls: 2, fast_surcharge_usd: 0, unknown_fast_price_calls: 2};
    expect(unknownCostTitle(row)).toContain(calls);
    expect(unknownCostTitle(row)).toContain(reason);
    expect(unknownCostTitle(row, 'fast')).toContain(fastCalls);
    expect(unknownCostTitle({api_usd_known: 0, unknown_price_calls: 0})).toBeUndefined();
  });

  it.each(['en-US', 'zh-TW', 'ja-JP'])('rounds dollar amounts to exactly two decimals with only the dollar symbol in %s', async language => {
    await loadI18n([language]);
    const {money, fastSurcharge} = await import('../lib/format');
    expect(money(8)).toBe('$8.00');
    expect(money(8.5)).toBe('$8.50');
    expect(money(1234.567)).toBe('$1,234.57');
    expect(money(1456.99657828)).toBe('$1,457.00');
    expect(money(1.005)).toBe('$1.01');
    expect(money(0.004)).toBe('$0.00');
    expect(money(0.005)).toBe('$0.01');
    expect(money(-1.235)).toBe('-$1.24');
    expect(money(8.555, true)).toBe('$8.56');
    expect(fastSurcharge({fast_surcharge_usd: 0.155, unknown_fast_price_calls: 0}, true)).toBe('$0.16');
  });

  it('uses the persisted Chinese choice for native labels, English-keyed features, and formatting', async () => {
    localStorage.setItem('codex-token-report.language', 'zh');
    const store = await loadI18n(['en-US']);
    await import('../pages/quotaMessages');
    await import('../pages/settingsMessages');
    const {formatCompact, formatDateTime, quotaWindowLabel} = await import('../lib/format');
    const {systemMessage} = await import('../lib/systemMessages');
    document.body.dataset.timezone = 'Asia/Taipei';
    expect(store.locale).toBe('zh');
    expect(store.getLanguagePreference()).toBe('zh');
    expect(document.documentElement.lang).toBe('zh');
    expect(store.t('用量总览')).toBe('用量总览');
    expect(store.t('Model price management')).toBe('模型价格管理');
    expect(store.t('Current cycle conversion')).toBe('当前周期换算');
    expect(store.t('{window} remaining {percent}', {window: '每周额度', percent: '75%'})).toBe('每周额度剩余 75%');
    expect(formatCompact(10000)).toBe('1万');
    expect(quotaWindowLabel({window_minutes: 300, limit_id: 'codex'})).toBe('5 小时额度');
    expect(formatDateTime('2026-10-01T17:03:00Z', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})).toBe('2026/10/02 01:03');
    expect(systemMessage('Codex 目录不存在，请选择已有目录。')).toBe('Codex 目录不存在，请选择已有目录。');
    expect(systemMessage('start 必须是 YYYY-MM-DD')).toBe('start 必须是 YYYY-MM-DD');
    const title = 'My title 用户标题';
    expect(systemMessage(title)).toBe(title);
    store.setLanguagePreference('en');
    expect(formatCompact(10000)).toBe('10K');
  });

  it('uses Japanese compact units, quota labels, and the configured date timezone', async () => {
    await loadI18n(['ja-JP']);
    document.body.dataset.timezone = 'Asia/Taipei';
    const { formatCompact, formatDateTime, quotaWindowLabel, fastSurcharge } = await import('../lib/format');
    expect(formatCompact(10000)).toBe('1万');
    expect(quotaWindowLabel({ window_minutes: 300, limit_id: 'codex' })).toContain('5時間');
    expect(formatDateTime('2026-10-01T17:03:00Z', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })).toBe('2026/10/02 01:03');
    expect(formatDateTime(null)).toBe('不明');
    expect(fastSurcharge({ fast_surcharge_usd: 0, unknown_fast_price_calls: 1 })).toBe('不明');
  });
});

describe('backend system messages', () => {
  it('localizes known Japanese errors, field validation, and model error lists', async () => {
    await loadI18n(['ja-JP']);
    const { systemMessage } = await import('../lib/systemMessages');
    expect(systemMessage('项目不存在')).toBe('プロジェクトが見つかりません。');
    expect(systemMessage('start 必须是 YYYY-MM-DD')).toBe('start は YYYY-MM-DD 形式で指定してください。');
    expect(systemMessage('end_time 必须是 HH:MM（00:00–23:59）')).toBe('end_time は HH:MM 形式（00:00–23:59）で指定してください。');
    expect(systemMessage('gpt-6-astra: 模型缺少价格; gpt-5.6-sol: 价格不是有效数字')).toBe('gpt-6-astra: モデルの価格がありません。; gpt-5.6-sol: 価格が有効な数値ではありません。');
  });

  it('localizes English errors and preserves unknown server or user text', async () => {
    await loadI18n(['en-GB']);
    const { systemMessage } = await import('../lib/systemMessages');
    expect(systemMessage('项目不存在')).toBe('Project not found.');
    const external = 'meeting notes: 用户的中文标题 {count}';
    expect(systemMessage(external)).toBe(external);
    expect(systemMessage('gpt-6-astra: vendor error with 中文详情')).toBe('gpt-6-astra: vendor error with 中文详情');
    expect(systemMessage('gpt-6-astra: 模型缺少价格; gpt-5.6-sol: external failure')).toBe('gpt-6-astra: The model has no prices.; gpt-5.6-sol: external failure');
    expect(systemMessage(null)).toBeNull();
    expect(systemMessage(undefined)).toBeUndefined();
  });
});

describe('generated model labels', () => {
  it.each([['en-US', 'Unknown model'], ['ja-JP', '不明なモデル']])('localizes unknown identities for %s and retains literal custom names', async (language, expected) => {
    await loadI18n([language]);
    const { modelName } = await import('../lib/format');
    expect(modelName({ key: 'unknown', display_name: '未知模型' })).toBe(expected);
    expect(modelName({ model: 'unknown', display_name: 'unknown' })).toBe(expected);
    expect(modelName({ key: 'custom-model', display_name: '未知模型' })).toBe('未知模型');
    expect(modelName({ model: 'custom-model', display_name: '<img src=x>' })).toBe('<img src=x>');
    expect(modelName({ key: 'gpt-custom' })).toBe('gpt-custom');
    const { createElement } = await import('react');
    const { render } = await import('@testing-library/react');
    const { StackedChart } = await import('../components/Shared');
    const view = render(createElement(StackedChart, { rows: [{ key: '2026-10-01', total_tokens: 20, models: [
      { key: 'unknown', model: 'unknown', display_name: '未知模型', total_tokens: 10 },
      { key: 'custom-model', display_name: '未知模型', total_tokens: 10 },
    ] }] }));
    const segments = view.container.querySelectorAll('.model-segment');
    expect(segments[0].title.split('\n')[0]).toBe(expected);
    expect(segments[1].title.split('\n')[0]).toBe('未知模型');
    const { sessionMatches } = await import('../pages/usage/SessionsPage');
    const { t } = await import('../lib/i18n');
    const row = { key: 'sample', title: 'Literal session', models: ['未知模型'], projects: ['未知项目'],
      model_entries: [{ key: 'unknown', display_name: '未知模型' }],
      project_entries: [{ key: 'unknown', display_name: '未知项目', path: null }] };
    expect(sessionMatches(row, expected)).toBe(true);
    expect(sessionMatches(row, t('未知项目'))).toBe(true);
    expect(sessionMatches({ key: 'legacy', title: 'Literal session', models: ['未知模型'], projects: ['未知项目'] }, expected)).toBe(false);

  });
});

describe('language preferences', () => {
  it('restores a persisted manual language ahead of browser preferences', async () => {
    localStorage.setItem('codex-token-report.language', 'en');
    const store = await loadI18n(['ja-JP']);
    expect(store.getLanguagePreference()).toBe('en');
    expect(store.locale).toBe('en');
    store.setLanguagePreference('ja');
    expect(localStorage.getItem(store.LANGUAGE_STORAGE_KEY)).toBe('ja');
    vi.resetModules();
    const restored = await import('../lib/i18n');
    expect(restored.getLanguagePreference()).toBe('ja');
    expect(restored.locale).toBe('ja');
    restored.setLanguagePreference('auto');
    expect(restored.locale).toBe('ja');
    expect(localStorage.getItem(store.LANGUAGE_STORAGE_KEY)).toBe('auto');
  });

  it.each(['fr', '{corrupt-json}', '"ja"', ''])('ignores invalid persisted preference %j', async value => {
    localStorage.setItem('codex-token-report.language', value);
    const store = await loadI18n(['ja-JP']);
    expect(store.getLanguagePreference()).toBe('auto');
    expect(store.locale).toBe('ja');
  });

  it('switches existing translations and Intl formatters without a module reload', async () => {
    const store = await loadI18n(['en-US']);
    document.body.dataset.timezone = 'Asia/Taipei';
    const {formatCompact, money, formatDateTime} = await import('../lib/format');
    expect(formatCompact(10000)).toBe('10K');
    store.setLanguagePreference('ja');
    expect(store.locale).toBe('ja');
    expect(document.documentElement.lang).toBe('ja');
    expect(store.t('模型定价')).toBe('モデル料金');
    expect(formatCompact(10000)).toBe('1万');
    expect(money(10)).toBe('$10.00');
    expect(formatDateTime('2026-10-01T17:03:00Z', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})).toBe('2026/10/02 01:03');
    store.setLanguagePreference('auto');
    expect(store.locale).toBe('en');
    expect(formatCompact(10000)).toBe('10K');
  });

  it('notifies both hooks while preserving a mounted component draft', async () => {
    const store = await loadI18n(['en-US']);
    const {createElement, useState} = await import('react');
    const {render, fireEvent, act} = await import('@testing-library/react');
    function Probe() {
      const active = store.useLocale(), preference = store.useLanguagePreference();
      const [draft, setDraft] = useState('original');
      return createElement('div', null,
        createElement('output', {'data-testid': 'preference'}, `${active}/${preference}`),
        createElement('input', {value: draft, onChange: event => setDraft(event.target.value)}));
    }
    const view = render(createElement(Probe));
    fireEvent.change(view.getByRole('textbox'), {target: {value: 'unsaved directory'}});
    act(() => store.setLanguagePreference('en'));
    expect(view.getByTestId('preference').textContent).toBe('en/en');
    act(() => store.setLanguagePreference('ja'));
    expect(view.getByTestId('preference').textContent).toBe('ja/ja');
    expect(view.getByRole('textbox').value).toBe('unsaved directory');
  });

  it('retains an in-memory choice when reading or writing storage is denied', async () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new DOMException('Denied', 'SecurityError'); });
    const store = await loadI18n(['en-US']);
    expect(store.getLanguagePreference()).toBe('auto');
    expect(() => store.setLanguagePreference('ja')).not.toThrow();
    expect(store.locale).toBe('ja');
    expect(document.documentElement.lang).toBe('ja');
  });

  it('still switches when browser storage exceeds its quota', async () => {
    const store = await loadI18n(['en-US']);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full', 'QuotaExceededError'); });
    expect(() => store.setLanguagePreference('ja')).not.toThrow();
    expect(store.getLanguagePreference()).toBe('ja');
    expect(store.t('用量总览')).toBe('使用量の概要');
  });

  it('synchronizes cross-tab storage changes and browser language changes in auto mode', async () => {
    const store = await loadI18n(['en-US']);
    window.dispatchEvent(new StorageEvent('storage', {key: store.LANGUAGE_STORAGE_KEY, newValue: 'ja'}));
    expect(store.locale).toBe('ja');
    expect(store.getLanguagePreference()).toBe('ja');
    window.dispatchEvent(new StorageEvent('storage', {key: 'unrelated', newValue: 'en'}));
    expect(store.locale).toBe('ja');
    window.dispatchEvent(new StorageEvent('storage', {key: store.LANGUAGE_STORAGE_KEY, newValue: null}));
    expect(store.getLanguagePreference()).toBe('auto');
    expect(store.locale).toBe('en');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['ja-JP']);
    window.dispatchEvent(new Event('languagechange'));
    expect(store.locale).toBe('ja');
    store.setLanguagePreference('en');
    window.dispatchEvent(new Event('languagechange'));
    expect(store.locale).toBe('en');
    window.dispatchEvent(new StorageEvent('storage', {key: null}));
    expect(store.getLanguagePreference()).toBe('auto');
    expect(store.locale).toBe('ja');
  });
});
