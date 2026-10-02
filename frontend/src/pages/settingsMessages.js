import {addMessages} from '../lib/i18n';

const messages = {
  '设置': ['Settings', '設定'],
  'SETTINGS': ['SETTINGS', '設定'],
  '管理日志目录、界面语言和模型价格。': ['Manage the log directory, interface language, and model prices.', 'ログディレクトリ、表示言語、モデル料金を管理します。'],
  'APPLICATION SETTINGS': ['APPLICATION SETTINGS', 'アプリ設定'],
  '日志与界面': ['Logs and interface', 'ログと表示'],
  'Codex 日志目录': ['Codex log directory', 'Codexログディレクトリ'],
  '选择 Codex 主目录，包含 sessions、archived_sessions 或 logs_2.sqlite。保存后自动扫描，已有历史记录继续保留。': [
    'Select the Codex home directory containing sessions, archived_sessions, or logs_2.sqlite. Saving scans this directory and keeps your saved history.',
    'sessions、archived_sessions、または logs_2.sqlite を含む Codex のホームディレクトリを指定してください。保存するとスキャンが実行され、保存済みの履歴は保持されます。',
  ],
  '显示语言': ['Interface language', '表示言語'],
  '跟随浏览器': ['Follow browser', 'ブラウザーに合わせる'],
  '语言切换立即生效，选择保存在当前浏览器中。': ['Language changes take effect immediately. Your choice is saved in this browser.', '言語はすぐに切り替わります。選択はこのブラウザーに保存されます。'],
  '保存并扫描': ['Save and scan', '保存してスキャン'],
  '正在保存并扫描…': ['Saving and scanning…', '保存してスキャン中…'],
  '日志目录已保存。': ['Log directory saved.', 'ログディレクトリを保存しました。'],
  '请输入 Codex 日志目录。': ['Enter the Codex log directory.', 'Codexログディレクトリを入力してください。'],
  '当前日志目录不存在，请选择有效目录。': ['The current log directory does not exist. Choose a valid directory.', '現在のログディレクトリが見つかりません。有効なディレクトリを指定してください。'],
};

addMessages(Object.fromEntries(['en', 'ja'].map((language, index) =>
  [language, Object.fromEntries(Object.entries(messages).map(([key, translations]) => [key, translations[index]]))])));
