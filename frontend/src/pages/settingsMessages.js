import {addMessages} from '../lib/i18n';

const messages = {
  '设置': ['Settings', '設定'],
  'SETTINGS': ['SETTINGS', '設定'],
  '管理日志目录、界面语言和模型价格。': ['Manage the log directory, interface language, and model prices.', 'ログディレクトリ、表示言語、モデル料金を管理します。'],
  'APPLICATION SETTINGS': ['APPLICATION SETTINGS', 'アプリ設定'],
  '日志与界面': ['Logs and interface', 'ログと表示'],
  'Codex 日志目录': ['Codex log directory', 'Codexログディレクトリ'],
  '选择文件夹': ['Choose folder', 'フォルダーを選択'],
  '正在选择…': ['Choosing…', '選択中…'],
  '目录需包含 sessions、archived_sessions 或 logs_2.sqlite。已有历史记录会保留。': [
    'The folder must contain sessions, archived_sessions, or logs_2.sqlite. Saved history is retained.',
    'sessions、archived_sessions、または logs_2.sqlite を含むフォルダーを指定してください。保存済みの履歴は保持されます。',
  ],
  '显示语言': ['Interface language', '表示言語'],
  '跟随浏览器': ['Follow browser', 'ブラウザーに合わせる'],
  '保存并扫描': ['Save and scan', '保存してスキャン'],
  '正在保存并扫描…': ['Saving and scanning…', '保存してスキャン中…'],
  '日志目录已保存。': ['Log directory saved.', 'ログディレクトリを保存しました。'],
  '请输入 Codex 日志目录。': ['Enter the Codex log directory.', 'Codexログディレクトリを入力してください。'],
  '当前日志目录不存在，请选择有效目录。': ['The current log directory does not exist. Choose a valid directory.', '現在のログディレクトリが見つかりません。有効なディレクトリを指定してください。'],
};

addMessages(Object.fromEntries(['en', 'ja'].map((language, index) =>
  [language, Object.fromEntries(Object.entries(messages).map(([key, translations]) => [key, translations[index]]))])));
