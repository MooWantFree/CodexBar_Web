import {afterEach, beforeEach, describe, expect, it} from 'vitest';
import {cleanup, render} from '@testing-library/react';
import {CostValue} from '../components/CostValue';
import {setLanguagePreference} from '../lib/i18n';

afterEach(cleanup);
beforeEach(() => setLanguagePreference('en'));

describe('unknown OpenAI Fast rates', () => {
  it('shows the Standard estimate in yellow and explains the missing surcharge', () => {
    const row = {api_usd_known: 12.345, priced_calls: 2, unknown_price_calls: 2,
      unknown_fast_price_calls: 2, fast_standard_fallback_calls: 2};
    const {container} = render(<CostValue row={row}/>);
    const amount = container.querySelector('.cost-value');
    expect(amount.textContent).toBe('$12.35');
    expect(amount.classList.contains('unknown-cost')).toBe(true);
    expect(amount.title).toContain('2 Fast calls are temporarily estimated at Standard rates');
    expect(amount.title).toContain('unknown Fast surcharge is not included');
    expect(amount.textContent).not.toContain('Unknown');
  });

  it('retains the unknown surcharge while showing a known zero Standard estimate', () => {
    const row = {api_usd_known: 0, priced_calls: 1, unknown_price_calls: 1,
      fast_standard_fallback_calls: 1, fast_surcharge_usd: 0, unknown_fast_price_calls: 1};
    const {container} = render(<><CostValue row={row}/><CostValue row={row} kind="fast"/></>);
    const [amount, surcharge] = container.querySelectorAll('.cost-value');
    expect(amount.textContent).toBe('$0.00');
    expect(amount.title).toContain('Standard rates');
    expect(surcharge.textContent).toBe('Unknown');
    expect(surcharge.classList.contains('unknown-cost')).toBe(true);
  });

  it.each(['zh', 'ja'])('localizes the provisional estimate explanation in %s', language => {
    setLanguagePreference(language);
    const {container} = render(<CostValue row={{api_usd_known: 5, unknown_price_calls: 1,
      api_standard_fallback: true}}/>);
    const amount = container.querySelector('.cost-value');
    expect(amount.textContent).toBe('$5.00');
    expect(amount.title).toContain('Standard');
    expect(amount.title).not.toContain('temporarily estimated');
  });
});
