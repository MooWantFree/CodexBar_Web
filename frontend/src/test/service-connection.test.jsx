import {StrictMode} from 'react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import ServiceConnectionGuard from '../components/ServiceConnectionGuard';
import {setLanguagePreference} from '../lib/i18n';

const healthy = () => ({ok: true, json: async () => ({status: 'ok'})});
const advance = async milliseconds => act(async () => { await vi.advanceTimersByTimeAsync(milliseconds); });
const notice = () => screen.queryByRole('alertdialog');
const dialogMethods = Object.getOwnPropertyDescriptors(HTMLDialogElement.prototype);

beforeEach(() => {
  vi.useFakeTimers();
  setLanguagePreference('zh');
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {configurable: true, value() { this.open = true; }});
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {configurable: true, value() { this.open = false; }});
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(healthy()));
});

afterEach(() => {
  cleanup();
  for (const method of ['showModal', 'close']) {
    if (dialogMethods[method]) Object.defineProperty(HTMLDialogElement.prototype, method, dialogMethods[method]);
    else delete HTMLDialogElement.prototype[method];
  }
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('backend heartbeat', () => {
  it('checks health without caching and ignores an isolated failure', async () => {
    fetch.mockResolvedValueOnce(healthy()).mockRejectedValueOnce(new Error('Offline'));
    render(<ServiceConnectionGuard><button>Page action</button></ServiceConnectionGuard>);
    await advance(0);
    expect(fetch).toHaveBeenCalledWith('/api/health', {cache: 'no-store', signal: expect.any(AbortSignal)});
    await advance(6000);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(notice()).toBeNull();
    expect(screen.getByText('Page action')).toBeTruthy();
  });

  it('opens a global modal after repeated failures and automatically closes it on recovery', async () => {
    fetch.mockRejectedValue(new Error('Offline'));
    render(<ServiceConnectionGuard>Page</ServiceConnectionGuard>);
    await advance(3000);
    expect(notice().open).toBe(true);
    expect(screen.getByText('服务已关闭')).toBeTruthy();
    expect(document.body.classList.contains('service-offline')).toBe(true);
    fetch.mockResolvedValue(healthy());
    await advance(3000);
    expect(notice()).toBeNull();
    expect(document.body.classList.contains('service-offline')).toBe(false);
  });

  it.each(['button', 'escape'])('allows dismissal by %s until recovery, then warns on a new outage', async method => {
    fetch.mockRejectedValue(new Error('Offline'));
    render(<ServiceConnectionGuard>Page</ServiceConnectionGuard>);
    await advance(3000);
    if (method === 'button') fireEvent.click(screen.getByText('关闭提示'));
    else fireEvent(notice(), new Event('cancel', {bubbles: true}));
    expect(notice()).toBeNull();
    expect(document.body.classList.contains('service-offline')).toBe(false);
    await advance(9000);
    expect(notice()).toBeNull();
    fetch.mockResolvedValue(healthy());
    await advance(3000);
    fetch.mockRejectedValue(new Error('Offline again'));
    await advance(6000);
    expect(notice().open).toBe(true);
  });

  it.each([
    {ok: false, json: async () => ({status: 'ok'})},
    {ok: true, json: async () => ({status: 'error'})},
    {ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); }},
  ])('does not treat an unsuccessful health response as recovery: %j', async response => {
    fetch.mockResolvedValue(response);
    render(<ServiceConnectionGuard>Page</ServiceConnectionGuard>);
    await advance(3000);
    expect(notice().open).toBe(true);
  });

  it('times out stalled requests without overlap and aborts the current request on unmount', async () => {
    fetch.mockImplementation((_url, {signal}) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    const view = render(<ServiceConnectionGuard>Page</ServiceConnectionGuard>);
    await advance(7000);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
    expect(notice().open).toBe(true);
    await advance(3000);
    const currentSignal = fetch.mock.calls.at(-1)[1].signal;
    expect(currentSignal.aborted).toBe(false);
    view.unmount();
    expect(currentSignal.aborted).toBe(true);
    await advance(10000);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
    expect(document.body.classList.contains('service-offline')).toBe(false);
  });

  it('keeps a single polling loop in StrictMode and preserves dismissal when children change', async () => {
    fetch.mockRejectedValue(new Error('Offline'));
    const tree = content => <StrictMode><ServiceConnectionGuard>{content}</ServiceConnectionGuard></StrictMode>;
    const view = render(tree('Loading'));
    await advance(3000);
    expect(fetch).toHaveBeenCalledTimes(3);
    fireEvent.click(screen.getByText('关闭提示'));
    view.rerender(tree('Dashboard'));
    await advance(6000);
    expect(fetch).toHaveBeenCalledTimes(5);
    expect(notice()).toBeNull();
    expect(screen.getByText('Dashboard')).toBeTruthy();
  });
});
