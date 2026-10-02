import {useEffect, useRef, useState} from 'react';
import {useQuery} from '@tanstack/react-query';
import {useDashboard} from '../context/DashboardContext';
import {apiGet, apiPost} from '../lib/api';
import {t, useLanguagePreference, setLanguagePreference} from '../lib/i18n';
import {ErrorNotice} from '../components/Shared';
import {PricingPage} from './pricing/PricingPage';
import './settingsMessages';

export default function SettingsPage() {
  const {codexHome, saveSettings, settingsSaving, scanning, quotaRefreshing} = useDashboard();
  const [directory, setDirectory] = useState(codexHome || '');
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const selectingRef = useRef(false);
  const language = useLanguagePreference();
  const settings = useQuery({queryKey: ['settings'], queryFn: ({signal}) => apiGet('/api/settings', {signal})});
  useEffect(() => {
    if (!dirty) setDirectory(settings.data?.codex_home ?? codexHome ?? '');
  }, [settings.data?.codex_home, codexHome, dirty]);
  async function selectFolder() {
    if (busy || selectingRef.current) return;
    selectingRef.current = true;
    setSelecting(true);
    setError(null);
    try {
      const result = await apiPost('/api/settings/select-folder', {initial_path: directory.trim()});
      if (result.path) {
        setDirectory(result.path);
        setDirty(true);
        setSaved(false);
      }
    } catch (failure) { setError(failure); }
    finally { selectingRef.current = false; setSelecting(false); }
  }
  async function save(event) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setSaved(false);
    const path = directory.trim();
    if (!path) { setError(new Error(t('请输入 Codex 日志目录。'))); return; }
    try {
      const result = await saveSettings({codex_home: path});
      setDirectory(result.codex_home);
      setDirty(false);
      setSaved(true);
    } catch (failure) { setError(failure); }
  }
  const busy = settingsSaving || scanning || quotaRefreshing || selecting;
  return <section className="page settings-page" data-page="settings">
    <section className="panel settings-panel" aria-labelledby="settingsHeading">
      <div className="panel-heading"><div><p className="eyebrow">{t('APPLICATION SETTINGS')}</p><h2 id="settingsHeading">{t('日志与界面')}</h2></div></div>
      <form className="settings-form" onSubmit={save}>
        <div className="settings-field">
          <label htmlFor="codexHomeInput">{t('Codex 日志目录')}</label>
          <div className="settings-directory-control">
            <input id="codexHomeInput" type="text" autoComplete="off" spellCheck="false" value={directory} disabled={busy} aria-describedby="codexHomeHint" onChange={event => { setDirectory(event.target.value); setDirty(true); setError(null); setSaved(false); }} />
            <button type="button" className="button" disabled={busy} onClick={selectFolder}>{t(selecting ? '正在选择…' : '选择文件夹')}</button>
          </div>
          <p id="codexHomeHint" className="fine-print">{t('手动填写或选择本机文件夹，目录需包含 sessions、archived_sessions 或 logs_2.sqlite。点击保存后自动扫描，已有历史记录继续保留。')}</p>
          {settings.data?.codex_home_exists === false && <p className="fine-print unknown">{t('当前日志目录不存在，请选择有效目录。')}</p>}
        </div>
        <div className="settings-actions"><button type="submit" className="button primary" disabled={busy}>{t(settingsSaving ? '正在保存并扫描…' : '保存并扫描')}</button><span role="status" className="fine-print">{saved && t('日志目录已保存。')}</span></div>
        <ErrorNotice error={error || settings.error} />
      </form>
      <div className="settings-field settings-language">
        <label htmlFor="languageSelect">{t('显示语言')}</label>
        <select id="languageSelect" value={language} aria-describedby="languageHint" onChange={event => setLanguagePreference(event.target.value)}>
          <option value="auto">{t('跟随浏览器')}</option><option value="en">English</option><option value="ja">日本語</option><option value="zh">中文 (Chinese)</option>
        </select>
        <p id="languageHint" className="fine-print">{t('语言切换立即生效，选择保存在当前浏览器中。')}</p>
      </div>
    </section>
    <PricingPage />
  </section>;
}
