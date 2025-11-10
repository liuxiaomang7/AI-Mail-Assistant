# AI Mail Assistant (v1.6.0)

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/downloads/release/python-311/)
[![Docker](https://img.shields.io/badge/Docker-Powered-blue.svg)](https://www.docker.com)

一个 7x24 小时、全自动的邮件处理机器人。它能持续监控指定的 IMAP 邮箱，使用大型语言模型（LLM，例如 DeepSeek）智能分类新邮件，并根据复杂的业务规则自动执行操作（如回复、删除或抄送）。

此机器人专为自动化外贸工作流程而设计，能从海量邮件中自动筛选出有价值的新客户询盘，拦截受限区域的邮件，并将来自分不同区域的询盘升级给不同的团队成员。

## 🚀 核心功能

* **智能 AI 分类**：连接 DeepSeek API（兼容 OpenAI），分析邮件意图 (询盘, 垃圾邮件, 其他)。
* **多重业务逻辑**：
    * **拦截 (删除)**：自动将来自“受限区域”（如非洲、中东、东南亚、韩国、台湾）的邮件**移动到垃圾箱**。
    * **优先 (特殊抄送)**：自动回复来自“优先区域”（如欧盟、美加、澳新）的询盘，并**抄送给特定管理层** (`PRIORITY_CC_LIST`)。
    * **标准 (常规抄送)**：自动回复来自其他地区的“标准询盘”，并**抄送给常规团队** (`CC_LIST`)。
    * **忽略 (标记已读)**：自动忽略（标记为已读）`SPAM`、`OTHER` 或来自公司**内部**的邮件。
* **安全配置**：所有敏感信息（密码、API 密钥、抄送列表、内部域名）均通过 `.env` 文件管理，确保代码可以安全地提交到 GitHub。
* **Docker 部署**：专为 Docker 设计，使用 `docker-compose` 部署，可在 NAS 或任何云服务器（如 Google Cloud）上实现“零维护”稳定运行。
* **引用原文**：自动回复时，会引用原始邮件的正文摘要，方便收件人快速了解上下文。
* **健壮性**：包含 API 调用重试机制 (`tenacity`)  和日志滚动功能 (`logging.handlers`)。

## 🛠️ 技术栈

* **后端**: Python 3.11
* **部署**: Docker & Docker Compose
* **Python 库**:
    * `openai`: 用于连接 DeepSeek API 
    * `imap-tools`: 用于 IMAP 邮件收发 
    * `python-dotenv`: 用于加载 `.env` 环境变量 
    * `beautifulsoup4`: 用于清理 HTML 邮件正文 
    * `tenacity`: 用于 API 调用的指数退避重试 

## 📁 项目结构

```

ai-mail-assistant/
├── .env                \# \<-- 您的本地密钥 (被 .gitignore 忽略)
├── .gitignore          \# \<-- 确保 .env 和 logs/ 不被提交
├── CHANGELOG.md        \# \<-- 项目变更日志
├── docker-compose.yml  \# \<-- Docker 编排文件
├── Dockerfile          \# \<-- Docker 镜像构建文件
├── requirements.txt    \# \<-- Python 依赖项 
└── src/
    └── mail\_processor.py   \# \<-- 核心应用逻辑 (v1.6.0)

````

## ⚙️ 部署与运行 (NAS / 服务器)

### 1. 准备工作

* 确保您的服务器（如飞牛 NAS 或 Google GCE）已安装 `Docker` 和 `docker-compose`。

### 2. 克隆或下载项目

```bash
git clone [https://github.com/](https://github.com/)[您的GitHub用户名]/ai-mail-assistant.git
cd ai-mail-assistant
````

### 3\. 配置环境变量 (`.env`)

这是**最重要**的一步。项目依赖 `.env` 文件来获取所有密钥。请在项目根目录（`ai-mail-assistant/`）中创建一个名为 `.env` 的文件，并将以下内容粘贴进去，然后**修改为您自己的信息**。

```plaintext
# --- 邮箱 IMAP 配置 (接收邮件) ---
IMAP_HOST=mail.your-domain.com
IMAP_PORT=993
IMAP_USER=your-email@your-domain.com
IMAP_PASSWORD='your-email-password'

# --- 邮箱 SMTP 配置 (发送邮件) ---
SMTP_HOST=mail.your-domain.com
SMTP_PORT=465
SMTP_USER=your-email@your-domain.com
SMTP_PASSWORD='your-email-password'

# --- AI (DeepSeek) 配置 ---
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
DEEPSEEK_BASE_URL=https.api.deepseek.com

# --- 业务逻辑配置 ---
# 标准抄送列表
CC_LIST=email1@your-domain.com,email2@your-domain.com
# 优先抄送列表
PRIORITY_CC_LIST=boss@your-domain.com,email2@your-domain.com
# 排除的精确地址 (用于防止回复自己)
EXCLUDE_ADDRESSES=your-email@your-domain.com,email1@your-domain.com
# 排除的内部域名 (用于防止回复同事)
EXCLUDE_DOMAINS=@internal-domain.com,@another-internal.com

# 轮询间隔 (秒)
POLLING_INTERVAL=10
```

**安全提示:** `.gitignore` 文件已配置为**忽略** `.env` 文件，因此您的密钥永远不会被提交到 GitHub。

### 4\. 构建并启动容器

在项目根目录（`docker-compose.yml` 所在的目录）运行以下命令：

```bash
docker-compose up -d --build
```

  * `--build` 会强制根据 `Dockerfile` 构建新镜像。
  * `-d` 会使容器在后台 (detached) 运行。

### 5\. 检查日志

要查看机器人的实时运行状态，请使用：

```bash
docker-compose logs -f
```

您应该能看到日志输出 "邮件自动处理器 v1.6.0 启动..."。

### 6\. 更新与维护

  * **停止服务**: `docker-compose down`
  * **更新代码**: 如果您修改了 `src/mail_processor.py`（例如调整 AI 提示词），您**无需**重新构建。由于 `volumes` 挂载，您只需重启容器即可：
    ```bash
    docker-compose restart mail-processor
    ```
  * **更新依赖**: 如果您修改了 `requirements.txt`，则必须重新构建：
    ```bash
    docker-compose up -d --build
    ```

## 🔄 核心工作流

机器人处理每封未读邮件的逻辑顺序如下：

1.  **[预过滤]** 邮件是否来自 `EXCLUDE_DOMAINS` 或 `EXCLUDE_ADDRESSES`？
      * **是**: 标记已读。**(结束)**
2.  **[AI 分类]** **否** -\> 发送给 DeepSeek AI 进行分析。
3.  **[受限区域?]** AI 是否标记 `is_blocked_region` = `true`？
      * **是**: 移动邮件到 `Trash`。**(结束)**
4.  **[优先区域?]** AI 是否标记 `intent` = `INQUIRY` 且 `is_priority_region` = `true`？
      * **是**: 使用 `PRIORITY_CC_LIST` 回复并抄送。标记已读。**(结束)**
5.  **[标准询盘?]** AI 是否标记 `intent` = `INQUIRY`？
      * **是**: 使用标准 `CC_LIST` 回复并抄送。标记已读。**(结束)**
6.  **[其他情况]** (如 `SPAM`, `OTHER`):
      * 标记已读。**(结束)**

## 📚 变更日志

查看 [CHANGELOG.md](CHANGELOG.md) 以获取详细的版本历史记录。

```
```
