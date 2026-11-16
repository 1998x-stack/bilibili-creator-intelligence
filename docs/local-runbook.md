# 本地运行手册

本手册用于第一次在个人电脑上运行 Bilibili Creator Intelligence。建议严格按阶段推进，不要一开始就批量下载、启用多 worker 或调用付费 LLM。

## 0. 权限与隐私边界

- 仅处理你有权访问、保存和分析的内容；遵守 B站平台规则、创作者授权和适用法律。
- \`--authorized-content-use\` 是操作者声明，不会授予额外权限，也不会绕过登录、验证码、访问限制或风控。
- 默认只保存 SQLite、字幕、音频和分析产物，不下载完整 MP4。
- \`--no-llm\` 可确保本次处理不把字幕文本发送到外部 LLM。
- 不要把 \`.env\`、Cookie 文件、API Key、数据库、私人字幕或完整错误日志中的凭据提交到 GitHub。

## 1. 安装环境

~~~bash
git clone https://github.com/1998x-stack/bilibili-creator-intelligence.git
cd bilibili-creator-intelligence
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[all,dev]'
cp .env.example .env
~~~

macOS 建议先使用 CPU 配置：

~~~dotenv
BCI_WHISPER_DEVICE=cpu
BCI_WHISPER_COMPUTE_TYPE=int8
~~~

确认 FFmpeg 可用：

~~~bash
ffmpeg -version
~~~

## 2. 本机环境诊断

~~~bash
bci doctor
~~~

重点关注 Python、yt-dlp、FFmpeg、SQLite FTS5 trigram、faster-whisper、LLM SDK、API Key 和目录权限。

\`bci doctor\` 不发起网络请求，不验证 B站 Cookie 是否有效，也不测试 LLM API 连通性。可选组件未安装时会显示警告；不使用相应功能时可以暂时忽略。

## 3. 先跑离线测试

~~~bash
python -m compileall -q src
python -m pytest -q
~~~

只有离线测试通过后，再进入真实内容测试。

## 4. 第一阶段：只发现一条视频并读取元数据

~~~bash
bci run \
  --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp \
  --max-videos 1 \
  --authorized-content-use \
  --metadata-only
bci stats
~~~

这一步不下载音频、不运行 Whisper、不调用 LLM。检查视频是否进入数据库、标题和时长是否合理。

## 5. 第二阶段：转录，不调用 LLM

~~~bash
bci process \
  --mid 123456 \
  --limit 1 \
  --no-metadata \
  --no-llm \
  --authorized-content-use
~~~

这一步优先尝试可用字幕；字幕不可用时才尝试音频下载和 faster-whisper。首次 ASR 可能需要下载模型权重，耗时和内存占用会明显增加。

如果只想验证原字幕，不想触发 ASR，可以额外加 \`--no-asr\`；但只要某一 P 没有合格字幕，该视频就会失败，不会生成伪造的“完整转录”。

检查结果：

~~~bash
bci stats
bci queue-status
bci search '选择一段实际出现的中文文本'
~~~

FTS5 trigram 搜索至少需要 3 个字符。

## 6. 第三阶段：单独运行 LLM 分析

先在 \`.env\` 配置服务商的 API Key、Base URL 和模型名，再运行：

~~~bash
bci process \
  --mid 123456 \
  --limit 1 \
  --no-metadata \
  --no-subtitles \
  --no-asr
~~~

默认 \`BCI_LLM_MODE=schema\` 要求服务商支持严格 JSON Schema Structured Outputs。若兼容服务不支持，需明确设置 \`BCI_LLM_MODE=json\`；输出仍会通过 Pydantic 校验。

查看费用记录：

~~~bash
bci costs
~~~

费用是基于服务商返回用量和操作者提供价格计算的估算值，不等于账单核对。

## 7. 导出与恢复

~~~bash
bci export --mid 123456 --output data/export/creator.jsonl
bci queue-status
bci stats
~~~

队列任务耗尽重试次数后不会自动无限重试。确认错误原因后，显式执行：

~~~bash
bci process --mid 123456 --authorized-content-use --retry-failed
~~~

执行前建议备份 SQLite 数据库。SQLite WAL 模式下，备份时应使用一致性备份方式，不能只复制正在写入的主数据库文件而忽略 WAL 状态。

## 8. 反馈错误时请提供什么

请尽量一次提供：

1. 完整执行命令（将 MID、Cookie 路径、私人 URL 和密钥脱敏）。
2. \`bci doctor\` 输出。
3. 从第一条异常开始的完整 traceback，而不只是最后一行。
4. \`bci queue-status\` 和 \`bci stats\` 输出。
5. 操作系统、CPU 架构、Python 版本。
6. 出错阶段：发现视频、读取元数据、字幕下载、音频下载、Whisper、LLM、SQLite 或导出。

**不要发送** \`.env\` 原文、Cookie、API Key、Authorization Header、私人视频地址、私人完整字幕或未经脱敏的网络请求日志。先发脱敏错误信息即可。

## 9. 当前已知边界

- 离线测试不等于真实 B站、Whisper 硬件和 LLM 端到端测试。
- yt-dlp 使用非官方提取器，接口可能变化，发现结果不保证完整。
- 分 P 清单当前会缓存；视频编辑后需要后续版本提供显式刷新和数据失效机制。
- RPM/TPM 和估算预算是进程内控制，不是多进程共享的账户级配额。
- 处理任务不是对外部网络/API 副作用的 exactly-once 保证。
