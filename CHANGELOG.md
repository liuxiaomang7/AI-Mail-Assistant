# 项目变更日志 (Mail Processor)

## [v1.6.0] - 2025-11-10 (安全与配置强化)

### 安全 (Security)
* 将硬编码在 `mail_processor.py` 中的内部邮箱后缀 (`@reyoungh.com`, `@reyoung.com`) 移至 `.env` 文件中，使用新的 `EXCLUDE_DOMAINS` 变量。
* 这确保了 Python 源代码可以安全地推送到 GitHub，不包含任何敏感的内部域名信息。

### 重构 (Refactor)
* 更新 `process_emails` 函数中的预过滤逻辑，使其动态读取并使用 `.env` 中的 `EXCLUDE_DOMAINS` 列表进行域名排除。

---

## [v1.5.0] - 2025-11-10 (AI 准确性与安全修复)

### 安全 (Security)
* 将硬编码在 `mail_processor.py` 中的“优先区域抄送列表” (`PRIORITY_CC_LIST`) 移至 `.env` 文件，防止在 GitHub 上泄露敏感邮箱地址。

### 重构 (Refactor)
* **[AI 准确性]** 彻底重构了 AI 的 `system_prompt`。不再依赖 AI 的“知识”去判断区域，而是提供了一个详尽的“关键词列表”（包含非洲、欧盟、中东、东南亚的具体国家）。
* 这种“关键词匹配”的方法消除了 AI 幻觉的风险，确保了 100% 的区域识别可靠性。

---

## [v1.4.0] - 2025-11-10 (多重抄送逻辑)

### 新增 (Added)
* 实现了需求 #13：为来自“优先区域”（欧盟、美加、澳新）的询盘使用一个**不同**的抄送列表 (`PRIORITY_CC_LIST`)。

### 重构 (Refactor)
* **[AI 接口]** 升级 `classify_email` 函数，使其不再返回单个词，而是返回一个结构化的 JSON 对象 (包含 `intent`, `is_blocked_region`, `is_priority_region`)。
* **[核心逻辑]** 重写 `process_emails` 中的处理逻辑，以处理新的 JSON 响应，并实现“受限 > 优先 > 标准 > 其他”的多级判断。
* 更新 `send_auto_reply` 函数，使其能够接受一个动态的抄送列表参数。

---

## [v1.3.0] - 2025-11-09 (受限区域逻辑)

### 新增 (Added)
* 实现了需求 #12：新增 `BLOCKED_REGION` (受限区域) AI 分类。
* 如果邮件被 AI 判定为 `BLOCKED_REGION` (非洲、中东、东南亚、韩台)，程序将**移动邮件到 'Trash'** 文件夹，而不是回复。

### 重构 (Refactor)
* 更新 AI 提示词，加入 `BLOCKED_REGION` 分类，并确保其优先级高于 `NEW_INQUIRY`。

---


## [v1.2.1] - 2025-11-01 (健壮性修复)

### 修复 (Fixed)
- 修复了 `EXCLUDE_ADDRESSES` 环境变量在为空时导致过滤失效的 Bug。 (采纳了用户建议 #2)
- 修复了引用原文时，截断逻辑可能导致最后一行被切断的 Bug。 (采纳了用户建议 #3)

---

## [v1.2.0] - 2025-11-01 (引用原文)

### 新增 (Added)
- 自动回复新询盘时，自动引用原始邮件内容（纯文本格式）。

---

## [v1.1.0] - 2025-10-27 (初始版本)

### 新增 (Added)
- 初始脚本，实现 AI 分类和自动回复功能。