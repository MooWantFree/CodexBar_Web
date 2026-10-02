import { addMessages, t } from "./i18n";

// API values remain unchanged. Only messages owned by this application are translated.
const translations = [
  ["Codex 目录不能为空。", "The Codex directory cannot be empty.", "Codex ディレクトリを入力してください。"],
  ["Codex 目录不存在，请选择已有目录。", "The Codex directory does not exist. Choose an existing directory.", "Codex ディレクトリが見つかりません。既存のディレクトリを指定してください。"],
  ["Codex 路径必须是目录。", "The Codex path must be a directory.", "Codex のパスにはディレクトリを指定してください。"],
  ["Codex 目录无法读取，请检查访问权限。", "The Codex directory cannot be read. Check its access permissions.", "Codex ディレクトリを読み取れません。アクセス権を確認してください。"],
  ["Codex 目录结构无效：sessions 和 archived_sessions 必须是目录，logs_2.sqlite 必须是文件。", "Invalid Codex directory structure: sessions and archived_sessions must be directories, and logs_2.sqlite must be a file.", "Codex ディレクトリの構造が無効です。sessions と archived_sessions はディレクトリ、logs_2.sqlite はファイルである必要があります。"],
  ["保存 Codex 目录失败，请稍后重试。", "Could not save the Codex directory. Try again later.", "Codex ディレクトリを保存できませんでした。後で再試行してください。"],
  ["当前账号", "Current account", "現在のアカウント"],
  ["上次保存的账号", "Last saved account", "最後に保存したアカウント"],
  ["旧版本本地账号档案（日志目录归属未确认）", "Legacy local account archive (log directory ownership unverified)", "旧バージョンのローカルアカウント記録（ログディレクトリの所属は未確認）"],
  ["CODEX_TOKEN_REPORT_CODEX_BIN 指向的文件不存在，请检查路径。", "The file configured in CODEX_TOKEN_REPORT_CODEX_BIN does not exist. Check the path.", "CODEX_TOKEN_REPORT_CODEX_BIN で指定したファイルが見つかりません。パスを確認してください。"],
  ["无法使用配置的 Codex CLI，请指定 codex.exe 的路径。", "The configured Codex CLI cannot be used. Specify the path to codex.exe.", "設定された Codex CLI を使用できません。codex.exe のパスを指定してください。"],
  ["未找到 Codex CLI。请安装 CLI，或设置 CODEX_TOKEN_REPORT_CODEX_BIN。", "Codex CLI was not found. Install it or set CODEX_TOKEN_REPORT_CODEX_BIN.", "Codex CLI が見つかりません。CLI をインストールするか、CODEX_TOKEN_REPORT_CODEX_BIN を設定してください。"],
  ["无法启动 Codex CLI，请检查可执行文件路径。", "Could not start Codex CLI. Check the executable path.", "Codex CLI を起動できません。実行ファイルのパスを確認してください。"],
  ["Codex 额度连接已中断，请稍后刷新。", "The Codex quota connection was interrupted. Refresh later.", "Codex の利用枠への接続が中断されました。しばらくしてから更新してください。"],
  ["读取 Codex 额度超时，请稍后刷新。", "Reading Codex quota timed out. Refresh later.", "Codex の利用枠の取得がタイムアウトしました。しばらくしてから更新してください。"],
  ["Codex 额度连接已中断，请检查 CLI 和登录状态。", "The Codex quota connection was interrupted. Check the CLI and sign-in status.", "Codex の利用枠への接続が中断されました。CLI とログイン状態を確認してください。"],
  ["Codex 无法读取额度，请检查 ChatGPT 登录状态或稍后重试。", "Codex could not read quota. Check your ChatGPT sign-in status or try again later.", "Codex が利用枠を取得できません。ChatGPT のログイン状態を確認するか、後で再試行してください。"],
  ["Codex 返回的额度格式不兼容，请更新 CLI。", "The quota format returned by Codex is incompatible. Update the CLI.", "Codex が返した利用枠の形式に対応していません。CLI を更新してください。"],
  ["Codex 尚未登录，请先在 Codex 中登录 ChatGPT 账号。", "Codex is not signed in. Sign in to your ChatGPT account in Codex first.", "Codex にログインしていません。先に Codex で ChatGPT アカウントにログインしてください。"],
  ["当前使用 API Key / Bedrock，无法读取订阅额度。", "API Key / Bedrock authentication is in use; subscription quota is unavailable.", "API Key / Bedrock を使用中のため、サブスクリプションの利用枠を取得できません。"],
  ["刷新登录后无法识别 ChatGPT 账号。", "The ChatGPT account could not be identified after refreshing sign-in.", "ログインの更新後も ChatGPT アカウントを識別できません。"],
  ["读取额度失败，请检查 Codex CLI 后重试。", "Could not read quota. Check Codex CLI and try again.", "利用枠を取得できません。Codex CLI を確認して再試行してください。"],
  ["请成功读取当前账号额度后查看历史；需要可识别的账号身份。", "Read the current account quota successfully before viewing history; an identifiable account is required.", "履歴を表示するには、識別可能な現在のアカウントの利用枠を取得してください。"],
  ["请先读取账号额度。", "Read the account quota first.", "先にアカウントの利用枠を取得してください。"],
  ["缺少有效的已消耗百分比，无法计算金额。", "A valid used percentage is missing, so the amount cannot be calculated.", "有効な使用済み割合がないため、金額を計算できません。"],
  ["缺少有效的额度快照、重置时间或窗口长度，无法确定统计范围。", "A valid quota snapshot, reset time, or window duration is missing; the reporting range cannot be determined.", "有効な利用枠のスナップショット、リセット時刻、または期間の長さがないため、集計範囲を特定できません。"],
  ["快照中的重置时间已过期，请刷新额度后计算。", "The snapshot reset time has passed. Refresh quota before calculating.", "スナップショットのリセット時刻を過ぎています。利用枠を更新してから計算してください。"],
  ["窗口长度超出支持范围，无法确定周期开始时间。", "The window duration exceeds the supported range; the cycle start cannot be determined.", "期間の長さが対応範囲を超えているため、サイクルの開始時刻を特定できません。"],
  ["本地调用日志没有额度组标识，无法分配到此额度组。", "Local request logs have no quota group identifier, so usage cannot be assigned to this group.", "ローカルのリクエストログに利用枠グループの識別情報がないため、このグループに使用量を割り当てられません。"],
  ["已消耗为 0%，不推测未使用的滚动窗口或额度美元价值。", "Usage is 0%; an unused rolling window and its dollar value are not estimated.", "使用量が 0% のため、未使用のローリング期間や利用枠のドル換算値は推定しません。"],
  ["无法确定当前周期起点，暂不计算金额。", "The current cycle start cannot be determined, so its amount is not calculated.", "現在のサイクルの開始時刻を特定できないため、金額は計算しません。"],
  ["缺少有效的额度快照时间，请刷新额度后计算。", "A valid quota snapshot time is missing. Refresh quota before calculating.", "有効な利用枠スナップショットの時刻がありません。利用枠を更新してから計算してください。"],
  ["当前账号未返回可计算的额度窗口。", "The current account returned no quota windows that can be calculated.", "現在のアカウントから、計算可能な利用枠の期間が返されませんでした。"],
  ["API 等价金额按本机日志估算；日志缺少账号标识，无法核对当前账号归属。不同窗口的统计范围可能重叠，金额请勿相加。", "API-equivalent amounts are estimated from local logs, which lack account identifiers and cannot be verified against the current account. Window ranges may overlap; do not add their amounts together.", "API 相当額はローカルログから推定します。ログにアカウント識別情報がないため、現在のアカウントの使用量か確認できません。各期間の集計範囲は重複する場合があるため、金額を合算しないでください。"],
  ["此周期没有本地调用记录，已消耗额度的金额未知。", "This cycle has no local request records; the value of used quota is unknown.", "このサイクルにローカルのリクエスト記録がないため、使用済み利用枠の金額は不明です。"],
  ["已消耗为 0%，无法据此外推每 1% 或整窗价值。", "Usage is 0%; the value per 1% or for the full window cannot be extrapolated.", "使用量が 0% のため、1% あたりや期間全体の価値を推定できません。"],
  ["按已知金额换算；未定价调用未计入金额。", "Converted using known amounts; unpriced requests are excluded.", "既知の金額で換算しています。未定価のリクエストは金額に含めません。"],
  ["此周期没有已定价调用，暂时无法换算额度美元。", "This cycle has no priced requests, so quota cannot yet be converted to dollars.", "このサイクルに定価のあるリクエストがないため、利用枠をドルに換算できません。"],
  ["显示最后一次保存的换算，金额与百分比保持当次读数。", "Showing the last saved conversion, with amounts and percentages preserved from that reading.", "最後に保存した換算を表示しています。金額と割合は、その取得時点の値を保持します。"],
  ["所选时间在当前时区不存在", "The selected time does not exist in the configured timezone.", "選択した時刻は、設定されたタイムゾーンに存在しません。"],
  ["精确范围需要两个重置时刻及对应日期", "An exact range requires two reset times and their corresponding dates.", "正確な範囲には、2 つのリセット時刻と対応する日付が必要です。"],
  ["重置时刻必须含时区且与日期时分一致", "Reset times must include a timezone and match the selected dates and times.", "リセット時刻にはタイムゾーンが必要で、選択した日付と時刻に一致している必要があります。"],
  ["两个重置时刻必须不同，开始时间须早于结束时间", "The reset times must differ, and the start must precede the end.", "2 つのリセット時刻は異なる必要があり、開始時刻は終了時刻より前である必要があります。"],
  ["开始时间不能晚于结束时间", "The start time cannot be later than the end time.", "開始時刻は終了時刻より後にできません。"],
  ["结束时间超出支持范围", "The end time exceeds the supported range.", "終了時刻が対応範囲を超えています。"],
  ["价格和倍率必须是有限的非负数", "Prices and multipliers must be finite, nonnegative numbers.", "価格と倍率は、有限の 0 以上の数値である必要があります。"],
  ["请求参数无效", "Invalid request parameters.", "リクエストのパラメーターが無効です。"],
  ["所选范围内没有该会话的调用", "No requests for this session exist in the selected range.", "選択した範囲にこのセッションのリクエストはありません。"],
  ["项目不存在", "Project not found.", "プロジェクトが見つかりません。"],
  ["额度历史读取失败，请稍后重试。", "Could not read quota history. Try again later.", "利用枠の履歴を取得できません。しばらくしてから再試行してください。"],
  ["额度读数历史读取失败，请稍后重试。", "Could not read quota observation history. Try again later.", "利用枠の取得値の履歴を取得できません。しばらくしてから再試行してください。"],
  ["当前账号没有此周期的历史记录。", "The current account has no history for this cycle.", "現在のアカウントに、このサイクルの履歴はありません。"],
  ["价格目录缺少 OpenAI 模型表", "The price catalog is missing the OpenAI model table.", "価格カタログに OpenAI のモデル一覧がありません。"],
  ["价格目录没有有效的 OpenAI 单价，保留上次有效缓存", "The catalog contains no valid OpenAI prices; the last valid cache is retained.", "カタログに有効な OpenAI の単価がないため、前回の有効なキャッシュを保持します。"],
  ["价格目录被重定向到非允许域名", "The price catalog was redirected to a disallowed domain.", "価格カタログが許可されていないドメインにリダイレクトされました。"],
  ["价格目录过大", "The price catalog is too large.", "価格カタログのサイズが大きすぎます。"],
  ["价格必须是有限的非负数", "Prices must be finite, nonnegative numbers.", "価格は、有限の 0 以上の数値である必要があります。"],
  ["价格不是有效数字", "The price is not a valid number.", "価格が有効な数値ではありません。"],
  ["models.dev 未提供该 OpenAI 模型", "models.dev does not provide this OpenAI model.", "models.dev にこの OpenAI モデルがありません。"],
  ["模型缺少价格", "The model has no prices.", "モデルの価格がありません。"],
  ["模型缺少 input/output 价格", "The model is missing input/output prices.", "モデルの input/output 価格がありません。"],
  ["长上下文阈值无效", "The long-context threshold is invalid.", "長いコンテキストのしきい値が無効です。"],
  ["模型 ID 只能包含小写字母、数字、点、下划线和连字符", "Model IDs may contain only lowercase letters, digits, dots, underscores, and hyphens.", "モデル ID に使用できるのは、小文字の英字、数字、ドット、アンダースコア、ハイフンのみです。"],
  ["logs_2.sqlite 不存在", "logs_2.sqlite was not found.", "logs_2.sqlite が見つかりません。"],
  ["{field} 必须是 YYYY-MM-DD", "{field} must use YYYY-MM-DD.", "{field} は YYYY-MM-DD 形式で指定してください。"],
  ["{field} 必须是 HH:MM（00:00–23:59）", "{field} must use HH:MM (00:00–23:59).", "{field} は HH:MM 形式（00:00–23:59）で指定してください。"],
];
const messages = {
  en: Object.fromEntries(translations.map(([key, english]) => [key, english])),
  ja: Object.fromEntries(translations.map(([key, , japanese]) => [key, japanese])),
};
addMessages(messages);

function translateKnown(value) {
  if (Object.hasOwn(messages.en, value)) return t(value);
  const date = /^(start|end) 必须是 YYYY-MM-DD$/.exec(value);
  if (date) return t("{field} 必须是 YYYY-MM-DD", { field: date[1] });
  const clock = /^(start_time|end_time) 必须是 HH:MM（00:00–23:59）$/.exec(value);
  if (clock) return t("{field} 必须是 HH:MM（00:00–23:59）", { field: clock[1] });
  return value;
}

export function systemMessage(value) {
  if (typeof value !== "string") return value;
  const exact = translateKnown(value);
  if (exact !== value) return exact;
  // Pricing errors are assembled as "model-id: known error; model-id: known error".
  // Unknown server/library errors and user-provided content retain their original text.
  return value.split("; ").map(part => {
    const match = /^([a-z0-9][a-z0-9._-]*): ([^\r\n]+)$/.exec(part);
    if (!match) return part;
    const translated = translateKnown(match[2]);
    return translated === match[2] ? part : `${match[1]}: ${translated}`;
  }).join("; ");
}
