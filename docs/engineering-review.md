# 工程审查与迭代路线图

**审查对象：** \`1998x-stack/bilibili-creator-intelligence\`  
**审查基线：** \`main\` @ \`f6d02300abad7d2280c25798e22da9d41e3949ec\`（v0.3.0）  
**审查日期：** 2026-11-16

## 1. 总体判断

项目已经具备可运行的本地优先数据流水线，不建议重写或提前引入分布式基础设施。现阶段应优先确保：本地安装可诊断、数据写入安全、单视频链路可复现、失败可恢复、分析结果可追溯。

当前能力主要集中在视频级转录和分析。创作者级趋势分析、跨视频知识发现和可视化管理界面属于后续产品层，不应与首次运行稳定性混为一谈。

## 2. 当前架构

1. **采集：** 授权空间 URL / CSV manifest；yt-dlp 空间发现；视频元数据和互动指标快照。
2. **分 P：** yt-dlp 枚举 \`?p=N\`，写入 \`video_parts\`。
3. **转录：** 优先下载字幕；字幕不可用时下载音频并调用 faster-whisper。
4. **合并：** 所有分 P 都有转录后才生成完整 transcript 和时间戳 segments。
5. **分析：** tiktoken 分块、Map-Reduce、Pydantic JSON Schema 校验。
6. **调度：** SQLite \`work_items\`，租约、fencing token、heartbeat、重试和阶段信号量。
7. **持久化：** creators、videos、video_stats、parts、transcripts、analyses、llm_usage、FTS5。
8. **接口：** \`bci\` CLI、JSONL 导出和 FTS5 搜索。

## 3. 已经具备的工程优势

- 本地优先，默认不下载完整 MP4。
- 网络访问有明确的授权声明和访问边界。
- 缺失指标使用 SQL NULL，不把未知伪装成零。
- 多 P 清单和逐 P 转录，拒绝不完整的整条投稿合并。
- Whisper 模型进程内缓存，按阶段限制并发。
- SQLite 持久化队列支持租约恢复和显式失败重试。
- LLM 使用 Token-aware 分块、结构化 Schema 和用量记录。
- 分析缓存绑定转录哈希和 Prompt/Schema 指纹。
- CI 对 Python 3.11、3.13 执行编译和离线测试；v0.3.0 PR 报告 41 项离线测试通过。

## 4. 审查发现

### P1 — 数据安全：统计原始 JSON 的白名单边界不一致

manifest 可以从原始 JSON 中提取统计字段，并把原始统计对象传入数据库。旧版 \`add_stats()\` 直接序列化整个 raw stats 对象，没有像 \`raw_metadata\` 一样做统一白名单过滤。

**处理：** 在数据库写入边界过滤允许的统计键和标量值，并增加回归测试。后续所有来源都应复用同一个安全函数。

### P1 — 本地运行：缺少统一环境诊断

首次运行需要分别判断 Python、yt-dlp、FFmpeg、faster-whisper、LLM SDK、SQLite FTS5、Cookie 文件和输出目录。缺少单一入口会让用户在真正开始采集后才遇到依赖错误。

**处理：** 增加 \`bci doctor\`，只做本地检查，不发起网络请求，不显示密钥。

### P1 — 运行反馈：空视频列表可能被当成空任务

\`process\` 查询不到指定 MID 的视频时，调度器可能返回空汇总，用户难以区分“没有数据”和“任务成功完成”。

**处理：** 对空输入显式失败，并提示先运行 \`bci discover\` 或 \`bci ingest\`。

### P1 — LLM 缓存：没有纳入 Provider / Endpoint 身份

缓存键目前主要使用 transcript hash、model 和 prompt/schema fingerprint。切换不同 OpenAI-compatible 服务商但沿用相同模型字符串时，可能复用旧分析。

**后续方案：** 生成不可逆的 provider/endpoint 标识并纳入缓存键；不得把 API Key 写入数据库或日志。需要设计兼容旧 SQLite 数据库的迁移和缓存回填策略。

### P1 — 分 P 清单：缺少显式刷新和版本化

已存的 part inventory 会被持续复用。视频增加、删除或调整分 P 后，旧清单可能造成遗漏或保留过时内容。

**后续方案：** inventory revision、discovered_at、CID/数量差异比较；变更后使受影响 part transcript、整条 transcript、FTS segments 和分析缓存失效。刷新必须先备份并保留历史版本，不能简单覆盖后丢失来源记录。

### P1 — 可观测性：缺少单次运行报告

现有 jobs 是阶段事件记录，queue-status 主要展示状态数量。对首次使用和定位故障来说，还缺少每次 run 的耗时、失败阶段、重试次数、错误类型和产物位置汇总。

**后续方案：** 增加 run_id / task_id 关联、结构化 JSON 日志、\`bci inspect\` 或 \`bci report\`。日志必须脱敏，不记录 Cookie、Authorization、签名 URL 或 API Key。

### P2 — Prompt 双份文件

根目录 \`prompts/video_analysis.md\` 为 v1；运行时代码读取 \`src/bili_intel/prompts/video_analysis.md\` 的 v3。两份文件容易漂移。

**后续方案：** 明确包内 Prompt 为唯一运行时权威源，删除无用途的旧副本或用自动同步测试约束；所有 Prompt 修改都要更新指纹与回归测试。

### P2 — CI 缺少静态质量门禁

当前 CI 执行 compileall 和 pytest，但没有运行已声明为 dev 依赖的 Ruff，也没有覆盖率阈值或独立的依赖安全扫描。

**后续方案：** 先清理 lint 告警，再加入 \`ruff check src tests\`；逐步补充 coverage、依赖扫描和 3.12 测试。

### P2 — ASR 质量没有基准集

当前测试验证缓存、调用路径和字幕处理，不衡量转录质量。

**后续方案：** 建立经授权且脱敏的人工校对小样本，分别计算 WER、CER、空转录率、时间戳偏差和不同模型/计算精度的速度、内存占用。没有基准集之前，不应宣称模型精度提升。

### P2 — 本地音频和字幕产物缺少保留策略

音频、字幕和模型分析产物可能持续累积。MP3 192 kbps 对 ASR 来说未必必要，后续可评估保留源音频格式、任务完成后清理临时文件，以及按保留策略回收空间。

### 产品层缺口 — 创作者情报而不仅是视频摘要

目前主要是视频级分析与本地检索。以下能力尚不应被描述为已经实现：

- 创作者长期画像、内容节奏和主题变化。
- 播放、点赞、投币、收藏、评论等指标的时间序列和增长分析。
- 跨视频主题聚类、观点演化和知识关联。
- 语义检索、向量索引和证据回链。
- 评论/弹幕采集（必须先明确权限与合规边界）。
- Web Dashboard、任务管理和可视化报告。

## 5. 推荐迭代顺序

| 阶段 | 目标 | 验收标准 |
|---|---|---|
| Phase 0 | 本地运行准备 | doctor 通过；离线测试通过；一条视频元数据可入库 |
| Phase 1 | 真实转录链路 | 一条授权视频所有可访问 P 完整转录；无字幕时 ASR 回退；失败可续跑 |
| Phase 2 | LLM 稳定性 | Provider 缓存隔离；Schema/JSON 模式验证；用量、成本和错误可追踪 |
| Phase 3 | 数据一致性 | Inventory 刷新、迁移、备份、失效策略和 FTS 一致性测试 |
| Phase 4 | ASR 质量与效率 | WER/CER 基准、CPU/GPU 性能、音频缓存和保留策略 |
| Phase 5 | 创作者情报产品 | 跨视频分析、指标趋势、语义检索和 Web UI |

## 6. 本地真实运行的验收顺序

1. \`bci doctor\`：本地依赖和目录检查。
2. \`python -m compileall -q src && python -m pytest -q\`：离线回归。
3. \`bci run ... --max-videos 1 --metadata-only\`：授权元数据发现。
4. \`bci process ... --limit 1 --no-metadata --no-llm\`：字幕/ASR 与多 P 完整性。
5. \`bci process ... --no-metadata --no-subtitles --no-asr\`：独立 LLM 分析。
6. \`bci search\`、\`bci export\`、\`bci costs\`、\`bci queue-status\`：检索、导出、费用与恢复检查。

真实 B站、Whisper 权重和付费 LLM 请求必须由操作者在有权限的本地环境验证。CI 离线测试不能替代这些检查。
