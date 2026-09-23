# 信源矩阵与接入边界

## P0：第一阶段应接入

| 领域 | 一手源 | 推荐方式 | 边界/备注 |
|---|---|---|---|
| Fed | [Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm)、FOMC、讲话与证词 | 官方 RSS；决议窗口补充页面监控 | MVP 已接货币政策、讲话/证词 RSS |
| ECB | [ECB RSS](https://www.ecb.europa.eu/home/html/rss.en.html) 的决议、新闻稿、讲话、采访和发布会记录 | 官方 RSS | MVP 已接；可按文档类型再过滤 |
| BOJ | [BOJ Monetary Policy Releases](https://www.boj.or.jp/en/mopo/mpmdeci/index.htm)、Statements、Speeches | 官方 RSS + 页面增量采集 | MVP 已接 What’s New RSS；生产版按类别过滤 |
| PBOC | [中国人民银行](https://www.pbc.gov.cn/)公开市场、货币政策、公告与新闻 | 官方页面/栏目采集 | 中文页面型；注意栏目和编码变化 |
| 美国制裁 | [OFAC Recent Actions](https://ofac.treasury.gov/recent-actions)、[Treasury Press Releases](https://home.treasury.gov/news/press-releases) | 官方页面/邮件订阅/API（如提供） | OFAC 示例默认关闭，启用前复核选择器和条款 |
| 美国出口管制 | [Commerce BIS](https://www.bis.gov/) Newsroom、[Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1) | 官方页面与 API | 规则正文应保存文号、生效日和 PDF/HTML 链接 |
| 美国关税/贸易 | USTR、White House、Commerce、Federal Register | 官方 RSS/API/页面 | 同一政策常跨机构发布，需事件聚类 |
| 中国重大政策 | 中国政府网、国务院政策文件、新华社授权发布 | 官方 RSS/页面 | “发布”与“解读”分开；保留文号和生效日 |
| 中国外交 | 外交部例行记者会、声明、答记者问 | 官方页面 | 对涉台、制裁、冲突关键词提高权重 |
| 核与核安全 | [IAEA News](https://www.iaea.org/news)、Statements、Director General | 官方 RSS/页面 | MVP 已接 IAEA RSS |
| 能源 | [OPEC Press Releases](https://www.opec.org/press-releases.html)、[IEA News](https://www.iea.org/news)、[EIA](https://www.eia.gov/) | 官方 RSS/API/页面 | 区分政策声明、月报与供应中断 |
| 冲突事实 | 各国政府/国防部、UN、NATO、航行/航空官方通告 | 官方 API/RSS/页面 | 早期信号与确认分层，避免把单方声明当独立事实 |

## P1：高可信确认与发现层

| 类型 | 信源 | 用法 | 接入边界 |
|---|---|---|---|
| 通讯社 | Reuters / LSEG Workspace | 全球政策、外交、冲突事实确认 | 必须购买相应新闻/API授权；不抓网页替代 feed |
| 专业终端 | Bloomberg Terminal / B-PIPE | Breaking News、First Word、市场上下文 | 仅按合同许可在终端或企业接口使用，不转发全文 |
| 央行专业流 | MNI | 利率、央行、政治风险 | 商业授权；保留其内容使用和再分发限制 |
| 交易快讯 | Newsquawk、LiveSquawk、TradeTheNews | 极低延迟发现与音频 squawk | 付费账户和官方接口；不要采集公开延迟页规避订阅 |
| 开源事件发现 | GDELT | 广覆盖发现和回溯 | 不是事实确认源；必须回到原始报道或官方源 |

## P2：日历与预期

- 各央行官方会议日历、政府统计发布日历用于“已知事件窗口”。
- 市场一致预期、调查中值和 whisper 数值通常有许可约束；使用 Bloomberg、Reuters、MNI 等数据时需单独确认存储、展示与派生数据权限。
- 日历事件与实时结果要分表：预告是 `scheduled_event`，结果是 `event`，二者通过会议 ID 关联。

## 合法与稳定性准则

1. 优先顺序：官方 API > 官方 RSS/Atom > 官方邮件/webhook > 允许抓取的静态页面 > 浏览器自动化。
2. 遵守 robots.txt、条款、版权、访问频率和身份认证；不绕过验证码、登录、付费墙或技术限制。
3. 保存标题、短摘要、结构化事实与原文链接；商业源全文是否可存储和再分发以合同为准。
4. 每个适配器记录 ETag/Last-Modified（后续项）、解析版本、最后成功时间与失败样本。
5. 网页选择器必须有 fixture 测试；解析条目突然归零时报警，不应默默成功。
