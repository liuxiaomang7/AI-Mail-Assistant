import os
import time
import smtplib
import ssl
import socket
import logging
import logging.handlers 
import json 
from pathlib import Path 
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr

from dotenv import load_dotenv
from imap_tools import MailBox, AND
from openai import OpenAI
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import APITimeoutError, APIConnectionError, RateLimitError, APIStatusError

# --- 1. 初始化和配置 ---

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
load_dotenv(dotenv_path=BASE_DIR / '.env')

# 配置日志滚动
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "mail_processor.log"
LOG_DIR.mkdir(exist_ok=True) 

log_level = logging.INFO
handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
)
handler.setLevel(log_level)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

stream_handler = logging.StreamHandler()
stream_handler.setLevel(log_level)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger = logging.getLogger()
logger.setLevel(log_level)
logger.addHandler(handler)
logger.addHandler(stream_handler)


# 从环境变量读取配置
IMAP_HOST = os.getenv('IMAP_HOST')
IMAP_PORT = int(os.getenv('IMAP_PORT', 993))
IMAP_USER = os.getenv('IMAP_USER')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')

SMTP_HOST = os.getenv('SMTP_HOST')
SMTP_PORT = int(os.getenv('SMTP_PORT', 465))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')

# [v1.5.0] “标准”抄送列表
CC_LIST = [addr.strip() for addr in os.getenv('CC_LIST', '').split(',') if addr.strip()]

# [v1.5.0] “精确”排除地址
EXCLUDE_ADDRESSES = [
    addr.strip().lower() 
    for addr in os.getenv('EXCLUDE_ADDRESSES', '').split(',') 
    if addr.strip()
]

# [✅ v1.6.0] 加载排除的域名
DEFAULT_EXCLUDE_DOMAINS = '@reyoungh.com,@reyoung.com'
EXCLUDE_DOMAINS = [
    domain.strip().lower()
    for domain in os.getenv('EXCLUDE_DOMAINS', DEFAULT_EXCLUDE_DOMAINS).split(',')
    if domain.strip()
]

POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', 10))

# [v1.5.0] “优先区域”抄送列表
DEFAULT_PRIORITY_LIST = 'reyoung@reyoung.com,liu.yongjun@reyoungh.com'
PRIORITY_CC_LIST = [
    addr.strip() 
    for addr in os.getenv('PRIORITY_CC_LIST', DEFAULT_PRIORITY_LIST).split(',') 
    if addr.strip()
]

# 初始化 DeepSeek (OpenAI 兼容) 客户端
try:
    ai_client = OpenAI(
        api_key=os.getenv('DEEPSEEK_API_KEY'),
        base_url=os.getenv('DEEPSEEK_BASE_URL'),
        timeout=30.0 
    )
    logger.info("DeepSeek AI 客户端初始化成功。")
except Exception as e:
    logger.critical(f"AI 客户端初始化失败: {e}")
    exit(1)

# --- 2. 核心功能函数 ---

def clean_email_body(body_html):
    """使用 BeautifulSoup 清理 HTML 邮件，提取纯文本。"""
    if body_html:
        try:
            soup = BeautifulSoup(body_html, 'html.parser')
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            text = ' '.join(soup.stripped_strings)
            return text[:4000] # 限制长度以优化 AI API 调用
        except Exception:
            return body_html[:4000]
    return ""

RETRYABLE_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)
@retry(
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    before_sleep=lambda retry_state: logger.warning(
        f"AI 分类失败，正在重试第 {retry_state.attempt_number} 次，原因: {retry_state.outcome.exception()}"
    )
)
def classify_email(sender, subject, body_text):
    """
    [✅ v1.5.0] 使用 DeepSeek API 分析邮件内容 (带重试功能)。
    使用详细的关键词列表来确保区域识别的准确性。
    """
    logger.info(f"开始 AI 分类邮件: {subject}")
    
    body_snippet = body_text[:4000]
    
    # [✅ v1.5.0] 极大地增强了提示词，以确保国家/地区识别的准确性
    system_prompt = """
    你是一个邮件分类助手。你的任务是分析邮件内容，判断其意图和来源地。
    请严格按照 JSON 格式返回，只返回 JSON 对象，不要有任何其他文字。

    JSON 结构:
    {
      "intent": "INQUIRY | SPAM | OTHER",
      "is_blocked_region": true | false,
      "is_priority_region": true | false
    }

    分类标准:
    1.  "intent":
        - "INQUIRY": 明确的、来自新客户的业务询盘或合作意向。
        - "SPAM": 广告、诈骗、垃圾邮件、订阅通讯。
        - "OTHER": 其他（如通知、客户支持、无效信息、退信通知等）。

    2.  "is_blocked_region" (受限区域 - 需求 #12):
        - true: 如果邮件正文、主题或发件人信息中 **明确提到** 以下任一关键词 (不区分大小写)。
        - 关键词 (地区): Africa, Middle East, Southeast Asia
        - 关键词 (国家/地区): Taiwan, Korea (South Korea)
        - 关键词 (非洲国家示例): Nigeria, Ethiopia, Egypt, DRC, Congo, Tanzania, South Africa, Kenya, Uganda, Algeria, Sudan, Morocco, Angola, Mozambique, Ghana, Madagascar, Cameroon, Côte d'Ivoire, Niger, Burkina Faso, Mali, Malawi, Zambia, Senegal, Chad, Somalia, Zimbabwe, Guinea, Rwanda, Benin, Burundi, Tunisia, Togo, Sierra Leone, Libya, Liberia, Mauritania, Namibia, Botswana, Gabon, Lesotho, Swaziland, Djibouti
        - 关键词 (中东国家示例): Bahrain, Cyprus, Egypt, Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Oman, Qatar, Saudi Arabia, Syria, Turkey, United Arab Emirates (UAE), Yemen, Palestine
        - 关键词 (东南亚国家示例): Vietnam, Thailand, Malaysia, Indonesia, Philippines, Singapore, Myanmar, Cambodia, Laos, Brunei, Timor-Leste

    3.  "is_priority_region" (优先区域 - 需求 #13):
        - true: 如果邮件正文、主题或发件人信息中 **明确提到** 以下任一关键词 (不区分大小写)。
        - 关键词 (地区): European Union (EU)
        - 关键词 (国家): Australia, New Zealand, USA (United States), Canada
        - 关键词 (欧盟国家示例): Austria, Belgium, Bulgaria, Croatia, Republic of Cyprus, Czech Republic, Denmark, Estonia, Finland, France, Germany, Greece, Hungary, Ireland, Italy, Latvia, Lithuania, Luxembourg, Malta, Netherlands, Poland, Portugal, Romania, Slovakia, Slovenia, Spain, Sweden

    [重要规则]:
    - 你的任务是“关键词匹配”。如果邮件中出现了 'Nigeria'，'is_blocked_region' 就必须是 true。
    - "is_blocked_region" 和 "is_priority_region" 可以同时为 true (例如邮件同时提到了德国和台湾)。
    - 我们的处理逻辑会优先处理 "is_blocked_region"。
    - "intent" 为 "INQUIRY" 的判断应独立于地区判断。
    """
    
    user_prompt = f"""
    请分类以下邮件：
    发件人: {sender}
    主题: {subject}
    正文摘要:
    ---
    {body_snippet}
    ---
    请严格返回 JSON:
    """
    
    default_response = {
        "intent": "OTHER", 
        "is_blocked_region": False, 
        "is_priority_region": False
    }
    
    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            max_tokens=200, 
            response_format={"type": "json_object"} 
        )
        
        raw_response = response.choices[0].message.content.strip()
        logger.info(f"AI 原始响应: {raw_response}")
        
        try:
            classification_data = json.loads(raw_response)
            if 'intent' not in classification_data or 'is_blocked_region' not in classification_data:
                logger.warning(f"AI 返回的 JSON 格式不完整: {raw_response}")
                return default_response

            logger.info(f"AI 分类结果: {classification_data}")
            return classification_data

        except json.JSONDecodeError:
            logger.error(f"AI 未能返回有效的 JSON: {raw_response}")
            return default_response
            
    except Exception as e:
        logger.error(f"调用 DeepSeek API 最终失败 (已重试): {e}")
        return default_response

def send_auto_reply(original_msg, custom_cc_list=None):
    """
    发送标准自动回复并抄送 (使用 465 端口, SMTPS, 带 20 秒超时)。
    [v1.4.0] 如果 custom_cc_list 提供了，则使用它，否则使用全局 CC_LIST。
    """
    
    cc_to_use = custom_cc_list if custom_cc_list is not None else CC_LIST
    
    logger.info(f"向 {original_msg.from_} 发送自动回复 (抄送至: {', '.join(cc_to_use)})...")

    # --- [v1.2.0] 新功能：构建引用原文 (此逻辑保留不变) ---
    original_text = original_msg.text
    if not original_text and original_msg.html:
        try:
            soup = BeautifulSoup(original_msg.html, 'html.parser')
            for script_or_style in soup(["script", "style"]):
                script_or_style.decompose()
            original_text = ' '.join(soup.stripped_strings)
        except Exception as parse_err:
            logger.warning(f"解析原始 HTML 邮件失败: {parse_err}")
            original_text = "[Could not parse original email body]"
    elif not original_text:
        original_text = "[Original email had no body]"

    # [v1.2.1 修复] 截断逻辑 (此逻辑保留不变)
    max_quote_len = 3000 
    lines = original_text.splitlines()
    quoted_lines = []
    total_len = 0
    truncation_message = "> [... truncated ...]"
    truncation_len = len(truncation_message) + 1 

    for line in lines:
        line_len_with_prefix = len(line) + 2 + 1 
        if (total_len + line_len_with_prefix + truncation_len) > max_quote_len:
            quoted_lines.append(truncation_message)
            total_len += truncation_len
            break 
        
        quoted_lines.append(f"> {line}")
        total_len += line_len_with_prefix

    quoted_body = "\n".join(quoted_lines)

    # 4. 构建回复正文 (此逻辑保留不变)
    reply_template = "Dear friend,\nGood day!\n\nGlad to receive your email, and I will contact you soon.\n\nBest Regards!\nJed"
    reply_header = f"\n\n--- Original Message ---\nOn {original_msg.date_str}, {original_msg.from_} wrote:\n"
    reply_body = f"{reply_template}\n{reply_header}\n{quoted_body}"

    msg = MIMEMultipart()
    msg['From'] = SMTP_USER
    msg['To'] = original_msg.from_
    msg['Cc'] = ", ".join(cc_to_use)
    msg['Subject'] = f"Re: {original_msg.subject}"

    if original_msg.headers.get('message-id'):
        msg['In-Reply-To'] = original_msg.headers['message-id'][0]
        msg['References'] = original_msg.headers['message-id'][0]

    msg.attach(MIMEText(reply_body, 'plain', 'utf-8'))

    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=context) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(
                SMTP_USER,
                [original_msg.from_] + cc_to_use,
                msg.as_string()
            )

        logger.info(f"自动回复发送成功: {original_msg.subject}")
        return True

    except smtplib.SMTPException as e:
        logger.error(f"发送 SMTP 邮件失败: {e}")
        return False
    except socket.timeout:
        logger.error(f"发送 SMTP 邮件失败: 连接 {SMTP_HOST}:{SMTP_PORT} 超时 (20 秒)。")
        return False
    except Exception as e:
        logger.error(f"发送 SMTP 邮件时发生意外错误: {e}")
        return False

# --- 3. 主处理循环 ---

def process_emails():
    """连接 IMAP，获取并处理新邮件。"""
    logger.info("开始检查新邮件...")

    mailbox = None
    try:
        mailbox = MailBox(IMAP_HOST, port=IMAP_PORT).login(IMAP_USER, IMAP_PASSWORD, initial_folder='INBOX')
        criteria = AND(seen=False)
        messages = list(mailbox.fetch(criteria, mark_seen=False, bulk=True))

        if not messages:
            logger.info("没有未读邮件。")
            return

        logger.info(f"发现 {len(messages)} 封未读邮件。")

        for msg in messages:
            try:
                sender = msg.from_.lower().strip()
                subject = msg.subject
                uid = msg.uid

                logger.info(f"--- 正在处理 (UID: {uid}): {sender} - {subject} ---")

                # [✅ v1.6.0 逻辑更新] 动态检查排除的域名
                # 1. 检查精确排除地址 (例如 'reyoung2@reyoung.com')
                is_excluded_address = sender in EXCLUDE_ADDRESSES
                
                # 2. 检查排除的域名后缀 (例如 '@reyoung.com')
                is_excluded_domain = False
                if not is_excluded_address: # 优化：如果已匹配精确地址，则跳过
                    for domain in EXCLUDE_DOMAINS:
                        if sender.endswith(domain):
                            is_excluded_domain = True
                            break # 找到一个匹配项即可
                
                # 如果任一条件满足，则跳过
                if is_excluded_address or is_excluded_domain:
                    logger.info(f"邮件来自排除地址或域 {sender}，标记为已读。")
                    mailbox.flag(uid, r'\Seen', True)
                    continue 
                # [✅ v1.6.0 逻辑更新结束]

                # 2. AI 分类 (已加入重试)
                body_text = clean_email_body(msg.html or msg.text)
                classification_data = classify_email(sender, subject, body_text)

                intent = classification_data.get('intent', 'OTHER')
                is_blocked = classification_data.get('is_blocked_region', False)
                is_priority = classification_data.get('is_priority_region', False)

                # --- [v1.4.0] 执行新的多重判断逻辑 ---

                # 规则 1 (需求 #12): 受限区域 (最高优先级)
                if is_blocked:
                    logger.warning(f"邮件 (UID: {uid}) 被分类为 [受限区域]，将移动到 'Trash'。")
                    try:
                        mailbox.move(uid, 'Trash')
                        logger.info(f"邮件 (UID: {uid}) 已成功移动到 'Trash'。")
                    except Exception as move_err:
                        logger.error(f"移动邮件 (UID: {uid}) 到 'Trash' 失败: {move_err}")
                        mailbox.flag(uid, r'\Seen', True) 
                    
                # 规则 2 (需求 #13): 优先区域询盘
                elif intent == 'INQUIRY' and is_priority:
                    logger.info(f"邮件 (UID: {uid}) 被分类为 [优先区域询盘]。")
                    # [v1.5.0] 使用从 .env 加载的 PRIORITY_CC_LIST
                    if send_auto_reply(msg, custom_cc_list=PRIORITY_CC_LIST):
                        logger.info("回复成功，标记为已读。")
                        mailbox.flag(uid, r'\Seen', True)
                    else:
                        logger.error(f"回复失败 (UID: {uid})，不标记已读，等待下次处理。")

                # 规则 3 (需求 #3): 标准新询盘
                elif intent == 'INQUIRY':
                    logger.info(f"邮件 (UID: {uid}) 被分类为 [标准新询盘]。")
                    # 使用“默认抄送列表” (传入 None)
                    if send_auto_reply(msg, custom_cc_list=None):
                        logger.info("回复成功，标记为已读。")
                        mailbox.flag(uid, r'\Seen', True)
                    else:
                        logger.error(f"回复失败 (UID: {uid})，不标记已读，等待下次处理。")

                # 规则 4 (需求 #2): SPAM / OTHER
                else: 
                    logger.info(f"邮件 (UID: {uid}) 被分类为 [{intent}]，标记已读。")
                    mailbox.flag(uid, r'\Seen', True)
                
                # --- [v1.4.0] 逻辑结束 ---

            except Exception as e:
                logger.error(f"处理邮件 (UID: {msg.uid}) 时发生内部错误: {e}")
                try:
                    mailbox.flag(msg.uid, r'\Seen', True)
                except Exception as flag_err:
                    logger.error(f"标记 UID {msg.uid} 为已读失败: {flag_err}")

        logger.info("邮件处理完成。")

    except Exception as e:
        logger.error(f"IMAP 连接或处理循环失败: {e}")
        logger.error("将等待下一个轮询周期。")

    finally:
        if mailbox:
            try:
                logger.info("正在登出 IMAP...")
                mailbox.logout()
                logger.info("IMAP 登出成功。")
            except Exception as logout_err:
                logger.warning(f"IMAP 登出时发生非致命错误 (可忽略): {logout_err}")

# --- 4. 启动器 ---

if __name__ == "__main__":
    # [✅ v1.6.0] 更新启动日志版本号
    logger.info(f"邮件自动处理器 v1.6.0 启动，轮询间隔: {POLLING_INTERVAL} 秒。")
    
    while True:
        try:
            process_emails()
        except Exception as e:
            logger.critical(f"主循环发生未捕J获的致命错误: {e}")
            
        logger.info(f"休眠 {POLLING_INTERVAL} 秒...")
        time.sleep(POLLING_INTERVAL)