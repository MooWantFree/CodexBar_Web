import {useEffect, useRef, useState} from 'react';
import {addMessages, t, useLocale} from '../lib/i18n';

addMessages({
  en: {
    '服务已关闭': 'Service is unavailable',
    '无法连接后端服务。请重新启动服务，连接恢复后此提示会自动消失。': 'Cannot connect to the backend. Restart the service; this notice will disappear when the connection recovers.',
    '关闭提示': 'Dismiss notice',
  },
  ja: {
    '服务已关闭': 'サービスに接続できません',
    '无法连接后端服务。请重新启动服务，连接恢复后此提示会自动消失。': 'バックエンドに接続できません。サービスを再起動してください。接続が回復すると、この通知は自動的に閉じます。',
    '关闭提示': '通知を閉じる',
  },
});

const HEARTBEAT_INTERVAL = 3000;
const HEARTBEAT_TIMEOUT = 2000;

export default function ServiceConnectionGuard({children}) {
  useLocale();
  const [offline, setOffline] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const dialog = useRef(null);

  useEffect(() => {
    let stopped = false;
    let failures = 0;
    let nextCheck;
    let timeout;
    let controller;

    async function check() {
      controller = new AbortController();
      timeout = setTimeout(() => controller.abort(), HEARTBEAT_TIMEOUT);
      try {
        const response = await fetch('/api/health', {cache: 'no-store', signal: controller.signal});
        if (!response.ok || (await response.json()).status !== 'ok') throw new Error('Service unavailable');
        if (stopped) return;
        failures = 0;
        setOffline(false);
        setDismissed(false);
      } catch {
        // Ignore one transient failure. Keep checking even after manual dismissal.
        if (!stopped && ++failures >= 2) setOffline(true);
      } finally {
        clearTimeout(timeout);
        if (!stopped) nextCheck = setTimeout(check, HEARTBEAT_INTERVAL);
      }
    }

    check();
    return () => {
      stopped = true;
      clearTimeout(nextCheck);
      clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  const showNotice = offline && !dismissed;
  useEffect(() => {
    if (!showNotice) return;
    const element = dialog.current;
    // A native modal also covers open date-picker dialogs and traps keyboard focus.
    element.showModal();
    document.body.classList.add('service-offline');
    return () => {
      element.close();
      document.body.classList.remove('service-offline');
    };
  }, [showNotice]);

  return <>{children}{showNotice && <dialog ref={dialog} className="service-offline-dialog" role="alertdialog"
    aria-modal="true" aria-labelledby="service-offline-title" aria-describedby="service-offline-description"
    onCancel={() => setDismissed(true)}>
    <div className="service-offline-icon" aria-hidden="true">!</div>
    <h2 id="service-offline-title">{t('服务已关闭')}</h2>
    <p id="service-offline-description">{t('无法连接后端服务。请重新启动服务，连接恢复后此提示会自动消失。')}</p>
    <button className="button" autoFocus onClick={() => setDismissed(true)}>{t('关闭提示')}</button>
  </dialog>}</>;
}
