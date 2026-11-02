# MCP 工具参考 — qualification-mcp-server

本 skill 连接的 MCP server：`handaas-mcp-server/qualification-mcp-server`（“资质大数据”）。

> **重要**：所有资质工具入参均为 `matchKeyword`（**企业全称** / 注册号 / 统一社会信用代码 / 企业 id）+ `keywordType`；
> 当用户只给企业关键词时，必须先调关键词模糊查询补全全称。

## 通用约定

- `keywordType` 枚举：`name`（企业名称）/ `nameId`（企业 id）/ `regNumber`（注册号）/ `socialCreditCode`（统一社会信用代码）。
- 分页：`pageIndex` 从 1 开始；`enterprise_qualifications` 的 `pageSize` 最多 10；`administrative_licenses` / `hitech_enterprise_cert` 的 `pageSize` 最多 50。这三个明细接口按显式页数预算采集（CLI `--max-pages`，默认 1 页；首屏同时作报告数据与 total 发现，不重复请求）；证书概况与荣誉资质接口不支持 pageIndex（单次调用），关键词模糊查询仅用于主体确认、不分页遍历。

---

## 工具清单

### 1. `qualification_bigdata_qualification_certificate_profile` — 资质证书概况

用途：按企业主体返回资质证书总量、近一年获证数、初次/最近获证日期、涵盖证书类别。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业名称 / 注册号 / 统一社会信用代码 / 企业 id（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |

返回：`certificateCount`（证书数量）、`certNumberThisYear`（近一年获证数）、`certFirstPublishTime`（初次获证日期）、`certLastPublishTime`（最近获证日期）、`certTypeList`（涵盖证书类别 list）。

product_id：`66a24df68912d491d34ab0a1`。

---

### 2. `qualification_bigdata_honor_qualifications` — 荣誉资质

用途：按企业主体返回荣誉资质明细（认定机关、资质级别、有效期）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |

返回（list + `total`）：`eaqTitle`（公告标题）、`eaqType`（资质类型）、`eaqRecognitionLevel`（资质级别）、`eaqAuthority`（认定机关）、`eaqPublishDate`（发布日期）、`eaqBeginDate` / `eaqEndDate`（有效期起止）。

product_id：`66b71b498dd25dbfbe8b0a9f`。

---

### 3. `qualification_bigdata_enterprise_qualifications` — 企业资质

用途：按企业主体返回企业资质明细（资质类型、级别、发布单位、高新行业分类）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |
| `pageIndex` | int | 否 | 从 1 开始（默认 1） |
| `pageSize` | int | 否 | 单页最多 10 |

返回（list + `total`）：`qualificationType`（资质类型）、`qualificationLevel`（资质级别）、`agency`（发布单位）、`publishDate`（发布日期）、`publishYear`（发布年份）、`qualificationClasses`（企业资质分类）、`highTechIndustryList`（高新行业分类）。

product_id：`67f3b410ac893a1d33dadef5`。

---

### 4. `qualification_bigdata_administrative_licenses` — 行政许可

用途：按企业主体返回行政许可明细（许可机关、许可内容、有效期、当前状态）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |
| `pageIndex` | int | 否 | 从 1 开始（默认 1） |
| `pageSize` | int | 否 | 单页最多 50（默认 10） |

返回（list + `total`）：`fileName`（决定文书名称）、`creditPubLicenseId`（决定文书号）、`content`（许可内容）、`authority`（许可机关）、`status`（当前状态）、`beginDate` / `endDate`（有效期起止）、`auditType`（审核类型）。

product_id：`669fb610a32fff27615b0c03`。

---

### 5. `qualification_bigdata_hitech_enterprise_cert` — 高新技术企业认证

用途：按企业主体返回高新技术企业认证明细（证书编号、类别、发证机构、有效期、证书状态）。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 企业主体（无全称则先调 fuzzy_search） |
| `keywordType` | string | 否 | 主体类型：name / nameId / regNumber / socialCreditCode |
| `pageIndex` | int | 否 | 从 1 开始（默认 1） |
| `pageSize` | int | 否 | 单页最多 50（默认 10） |

返回（list + `total`）：`certId`（证书编号）、`certType`（资质类别）、`certAuthority`（发证机构）、`certPublishTime`（颁证日期）、`certExpireTime`（截止日期）、`certStatus`（证书状态）。

product_id：`669f8ec259dda752d9799950`。

---

### 6. `qualification_bigdata_fuzzy_search` — 关键词模糊查询企业

用途：根据企业名称 / 人名 / 品牌 / 产品等关键词模糊查询企业列表，用于补全企业全称。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `matchKeyword` | string | 是 | 匹配关键词 |
| `pageIndex` | int | 否 | 分页开始位置（默认 1） |
| `pageSize` | int | 否 | 单页最多 50 |

返回：`total` + 企业列表（`name`、`nameId`、`regCapitalValue`、`foundTime`、`operStatus`、`address`、`legalRepresentative`、`enterpriseType`、`catchReason` 命中原因等）。

product_id：`675cea1f0e009a9ea37edaa1`。

---

## 推荐调用顺序（报告编排）

1. （若仅有关键词）`qualification_bigdata_fuzzy_search` → 取 `name` 作为全称。
2. `qualification_bigdata_qualification_certificate_profile` → 证书概况指标。
3. `qualification_bigdata_honor_qualifications` → 荣誉资质明细。
4. `qualification_bigdata_enterprise_qualifications` → 企业资质明细。
5. `qualification_bigdata_administrative_licenses` → 行政许可明细。
6. `qualification_bigdata_hitech_enterprise_cert` → 高新技术企业认证明细。

> 单次报告通常调用 5-6 个工具；所有工具入参均为企业主体 `matchKeyword` + `keywordType`。
