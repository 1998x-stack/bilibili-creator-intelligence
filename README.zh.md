# Bilibili Creator Intelligence

**本地优先的 B 站 UP 主内容研究工具｜v0.3.0**

输入 UP 主空间链接（或导入已获授权的视频 CSV 清单），建立 SQLite 本地知识库：视频发现 → 统计指标快照 → **全分 P** 字幕/语音转录 → **带时间戳文本** → **Token 感知的结构化 LLM 分析** → 可检索/导出。

[English](README.md) · [工程架构](docs/architecture.md) · [数据源/权限](docs/source-adapters.md) · [验证矩阵](docs/verification.md) · [安全](SECURITY.md)

> **访问权限**：Bilibili 视频发现由 yt-dlp 的非官方 `BilibiliSpaceVideo` 提取器实现，需确保拥有操作/内容处理权限；`--authorized-content-use` 只是操作人的确认，**不代表自动获得平台或创作者授权**。存在平台访问限制、已删除/私密投稿或分 P 不可访问情况。工具不绕过验证码、登录或访问控制；无法保证空间枚举的绝对完整性。

## 快速开始

```bash
# macOS
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all,dev]'
cp .env.example .env
```

在 `.env` 中配置本地 ASR 与 LLM（不要提交密钥）：

```dotenv
BCI_DB_PATH=./data/bilibili.sqlite3
BCI_ARTIFACTS_DIR=./data/artifacts
BCI_WHISPER_MODEL=small
BCI_WHISPER_DEVICE=cpu
BCI_WHISPER_COMPUTE_TYPE=int8
BCI_WHISPER_LANGUAGE=
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=
BCI_LLM_MODEL=gpt-4o-mini
BCI_LLM_MODE=schema
BCI_LLM_MAX_INPUT_TOKENS=6000
BCI_LLM_MAX_OUTPUT_TOKENS=1500

# 进程内受控并发：视频/网络/ASR/LLM
BCI_WORKERS=2
BCI_NETWORK_WORKERS=1
BCI_ASR_WORKERS=1
BCI_LLM_WORKERS=2
BCI_LLM_RPM=30
BCI_LLM_TPM=60000
```

macOS 上的 faster-whisper/CTranslate2 不应被当成 Apple MPS GPU 后端；`cpu + int8` 是保守配置。CUDA 设备可测试 `BCI_WHISPER_DEVICE=cuda` 与 `float16`，但需要正确安装 CTranslate2 的 CUDA/cuDNN 运行环境。首轮 ASR 会下载模型权重。只有 LLM 阶段发送字幕文本到所配置的服务。

## 运行命令

先限定一个已获授权 UP 主的 1 条视频进行真实环境试运行：

```bash
# 仅读取元数据（不下载音频、调用 ASR 或 LLM）
bci run --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp --max-videos 1 --authorized-content-use --metadata-only

# 完整流水线，逐 P 提取字幕，缺失时运行 Whisper
bci run --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp --max-videos 1 --authorized-content-use
```

批量与进度控制：

```bash
bci discover --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp --authorized-content-use
bci process --mid 123456 --authorized-content-use --limit 10 \
  --workers 2 --network-workers 1 --asr-workers 1 --llm-workers 2
bci queue-status
bci costs
bci stats
bci search '知识点分析' --limit 20
bci export --mid 123456 --output data/export/creator.jsonl
```

可通过 `--no-metadata / --no-subtitles / --no-asr / --no-llm` 关闭对应步骤。注意关闭 ASR 后，**某一 P 没有合格字幕将导致整条投稿失败**，而不是将部分文本伪装成完整分析。

离线方式（不依赖 B 站空间发现）：

```bash
bci ingest --space-url 'https://space.bilibili.com/123456/video' \
  --manifest examples/videos.csv
bci process --mid 123456 --authorized-content-use --limit 3
```

CSV 指标不存在就记为 SQL `NULL` 而非零。投币/收藏/分享等数据是否可获取取决于有权限的数据源，不承诺 yt-dlp 能获取全部统计字段。

## v0.3 的具体改进

| 领域 | 实现 | 不作出的承诺 |
|---|---|---|
| 全分 P | `video_parts` + `part_transcripts`；逐 `?p=N` 获取，全部完成才合并 | 不保证平台列出所有隐藏分 P/交互视频 |
| Whisper | 同进程缓存 `WhisperModel`，可指定语言；ASR 并发信号量 | 不提供说话人分离/字词级时间戳/精度保证 |
| 持久队列 | SQLite `work_items`，原子认领、fencing token、租约心跳、指数退避、耗尽后失败 | 外部下载/付费 LLM API **不是 exactly-once** |
| LLM 可靠性 | tiktoken 分块、两两合并、每次输出 token 上限、Pydantic 严格字段校验 | Schema 有效不代表内容真实 |
| 限流/费用 | 进程内 RPM/TPM + LLM usage SQLite 记录 + 可选人工配置预算 | 不代表跨进程/跨设备的服务商统一限流 |
| 字幕选择 | 语言、人工/自动来源、cue 是否可解析、时长覆盖启发式评分 | 覆盖率只是质量代理指标 |
| 数据安全 | 对数据源元数据统一实施白名单，限制原始凭据和签名地址写入 | 不替代正式授权与安全审计 |
| 数据一致性 | Prompt + Schema hash 缓存；导出仅关联当前字幕对应的分析 | 旧版已有分析不会自动重跑 |

**费用预算（可选）**：先查阅你的实际模型/服务商定价，再在 `.env` 中设置：

```dotenv
# 单位：美元 / 百万 tokens。此处不提供假定价格。
BCI_LLM_INPUT_USD_PER_MTOK=
BCI_LLM_OUTPUT_USD_PER_MTOK=
BCI_LLM_BUDGET_USD=
```

需要同时指定两种价格后才能启用预算。实际用量优先读取 API 返回 `usage`；如提供商不返回则按 tokenizer 估算。预算防护仅保证**本进程内尽力控制估算值**，多进程或多个部署共享 API Key 时，必须另设统一额度服务。失败/超时请求可能仍被计费。

兼容 API 如不支持 JSON Schema Structured Outputs，可**显式**设 `BCI_LLM_MODE=json`；输出仍接受 Pydantic 验证，否则请求失败，不会静默切换弱模式。关于 Schema 支持的说明见 [OpenAI 官方文档](https://platform.openai.com/docs/guides/structured-outputs)。

## SQLite 数据模型

- `creators`, `videos`, `video_stats`：身份、投稿和统计时间快照。
- `video_parts`, `part_transcripts`：分 P 清单及原始/ASR 字幕。
- `transcripts`, `transcript_segments`, `transcript_segments_fts`：整条投稿的完整转录，逐 cue 时间戳与 FTS5 搜索。
- `analyses`, `llm_usage`：Prompt 指纹、模型结果与 API 使用量。
- `work_items`, `jobs`, `discovery_runs`：任务队列、处理事件、发现审计。

SQLite 使用 WAL，线程共享的仅是数据库文件，**每次操作独立连接**；并发写入仍被 SQLite 串行化。任务完成后可通过 `bci search` 获得 `video_id + part_index + start_ms`。FTS5 使用 trigram，少于 3 个字符的短查询暂不支持。

本项目**不下载整段 MP4**；仅有权限时尝试提取原字幕/音频。默认本地持久化路径在 `.gitignore` 中被排除。

## 测试、边界与故障恢复

```bash
python -m compileall -q src
python -m pytest -q
bci queue-status
```

本地测试全部使用模拟数据，不需要 B 站、模型或密钥；未把模拟测试称为真实端到端验证。空间发现仍可能遇到 352/412 等访问限制，整批处理失败记录不意味着可绕过风控。没有实际授权视频与 API Key 无法证明真实运行吞吐量。

队列崩溃恢复：重新执行 `bci process --mid ...` 会重新关联未完成任务，保留待重试的次数/退避。若任务超过重试次数而失败，需**显式**追加 `--retry-failed`。`--queue-only` 可以只将任务入队，不执行；随后使用 `bci process` 启动。处理时间较长可用 `--max-wait-seconds` 控制前台执行时长；未完成任务仍保留在 SQLite。

完整架构与限制：见 [docs/architecture.md](docs/architecture.md)。许可证 MIT。
