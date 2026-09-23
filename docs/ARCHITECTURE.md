# 架构与事件模型

## 目标链路

```text
官方 RSS/API/网页 + 授权快讯流
          │
          ▼
采集适配器 → 原始条目 → 规范化/时间统一 → 精确与近似去重
                                            │
                                            ▼
                           分类 / 实体 / 重要性 / 影响资产
                                            │
                                            ▼
                    SQLite（MVP）→ Webhook → 飞书/企微/Telegram/邮件
                                            │
                                            └→ 原文链接与多源 sightings
```

## 设计原则

1. **一手结果优先**：决议、制裁、出口管制、政策文本以发布机构为事实源；媒体用于发现、翻译、背景和二次确认。
2. **原文可追溯**：每个事件保留规范化 URL、源、发布时间、抓取时间、原始摘要；同一事件的其他报道进入 `sightings`。
3. **优雅降级**：某一源故障不会中断全局；摘要模型、翻译和推送都应是可选后处理。
4. **确定性先行**：MVP 用可解释规则，后续让模型输出结构化候选结果，再由规则校验边界与阈值。

## 统一事件字段

核心字段包括 `event_id`、`fingerprint`、`event_type`、`importance(0–100)`、`severity`、`entities`、`assets`、`published_at`、`fetched_at`、`summary_zh`、`original_summary`、`canonical_url`、`authority` 和来源 sightings。

建议后续增加：

- `event_time` 与 `effective_time`：区分发布时间、事件发生时间和政策生效时间。
- `status`：rumor / preliminary / confirmed / corrected / withdrawn。
- `stance`：hawkish / dovish / escalation / de-escalation / supply_tightening 等。
- `surprise`：实际结果相对预期的差值；需接经济日历和一致预期授权数据。
- `evidence_spans`：实体、数字和判断所依据的原文片段位置。
- `model_provenance`：模型、提示版本、置信度和人工复核记录。

## 去重

MVP 依次使用规范 URL、标题指纹和三天窗口内标题 Jaccard 相似度。生产版建议引入：

- URL canonical ID 与官方公告编号；
- 多语种向量相似度和时间/实体约束；
- “事件簇”和“报道”分表，避免后续更新覆盖最初快讯；
- correction / update / full text 关系识别。

## 评分

当前分数由来源可信度、官方源、事件类别、紧急词、实体数、资产覆盖和新鲜度组成，所有权重位于 `config/rules.yaml`。生产版建议拆成三维：

- `credibility`：来源、是否一手、是否二次确认；
- `market_impact`：事件类型、意外程度、作用范围和交易时段；
- `urgency`：时效、是否正在发生、是否立即生效。

最终推送策略不应只看总分。例如“可信度低但潜在影响巨大”的消息应进入人工核验队列，不能直接当作已确认事实推送。

## 部署演进

- MVP：单进程轮询 + SQLite + Webhook。
- 小规模生产：异步采集器 + PostgreSQL + Redis 队列 + Prometheus 指标。
- 交易级：多区域采集、消息总线、幂等消费者、延迟 SLO、时钟同步、源级熔断与 replay。

最低监控项：每源最后成功时间、HTTP 状态、条目数、解析空值率、端到端延迟、重复率、推送失败率和数据库增长量。
