# qualification-skill：已验收示例

本目录只展示 **6 个完全通过的真实正向场景**（最低要求4例）。

每例均为真实、非空、非缓存调用；技术检查、独立业务检查和离线浏览器检查全部通过。不把空数据、报错处理或仅生成页面计作通过。历史验收记录保留在本地 test-records/；本目录的 HTML/Markdown 由原 JSON 重渲染，不代表重新查询或重新验收。

| 场景 | 真实使用需求 | 报告 |
|---|---|---|
| [供应商资质准入](01-supplier-cert/README.md) | 核查华为技术有限公司的企业资质、荣誉资质、行政许可和高新技术企业认定。 | [HTML](01-supplier-cert/report.html) / [MD](01-supplier-cert/report.md) / [JSON](01-supplier-cert/report.json) |
| [工程企业资质核查](02-construction-cert/README.md) | 查看中国建筑第八工程局有限公司的企业资质和行政许可。 | [HTML](02-construction-cert/report.html) / [MD](02-construction-cert/report.md) / [JSON](02-construction-cert/report.json) |
| [高新技术认定核验](03-hitech-cert/README.md) | 核查宁德时代新能源科技股份有限公司的高新技术企业认定和其他资质。 | [HTML](03-hitech-cert/report.html) / [MD](03-hitech-cert/report.md) / [JSON](03-hitech-cert/report.json) |
| [消费品企业许可审阅](04-consumer-license/README.md) | 查看贵州茅台酒股份有限公司的行政许可、企业资质和荣誉资质。 | [HTML](04-consumer-license/report.html) / [MD](04-consumer-license/report.md) / [JSON](04-consumer-license/report.json) |
| [汽车企业资质画像](05-automotive-cert/README.md) | 生成比亚迪股份有限公司资质报告，关注企业资质、许可和高新认定。 | [HTML](05-automotive-cert/report.html) / [MD](05-automotive-cert/report.md) / [JSON](05-automotive-cert/report.json) |
| [资质快速抽样](07-compact-cert/README.md) | 对小米科技有限责任公司生成每类前 5 条的资质快报。 | [HTML](07-compact-cert/report.html) / [MD](07-compact-cert/report.md) / [JSON](07-compact-cert/report.json) |

- [逐例验收结果](results.json) · [业务复核](review.json) · [证据摘要](evidence-index.json)
- 完整测试记录仅存于本地 test-records/live-replaced-20261027/（仅本地审计用，不随本目录发布），不属于可展示示例。
- 当前数据与结论限于原查询时点及公开样本；覆盖率不代表准确率或低风险。
