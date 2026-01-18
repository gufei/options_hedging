"""
Telegram 通知模块 - 发送套利信号通知
"""

import logging
import asyncio
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram 通知器"""

    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化 Telegram 通知器

        Args:
            bot_token: Telegram Bot Token (从 @BotFather 获取)
            chat_id: 目标 Chat ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = None
        self._init_bot()

    def _init_bot(self):
        """初始化 Telegram Bot"""
        try:
            from telegram import Bot
            self.bot = Bot(token=self.bot_token)
            logger.info("Telegram Bot 初始化成功")
        except ImportError:
            logger.error("python-telegram-bot 未安装，请运行: pip install python-telegram-bot")
        except Exception as e:
            logger.error(f"Telegram Bot 初始化失败: {e}")

    async def send_message_async(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        异步发送消息

        Args:
            message: 消息内容
            parse_mode: 解析模式 ("Markdown" 或 "HTML")

        Returns:
            是否发送成功
        """
        if not self.bot:
            logger.error("Telegram Bot 未初始化")
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            logger.info(f"Telegram 消息发送成功")
            return True
        except Exception as e:
            logger.error(f"Telegram 消息发送失败: {e}")
            # 尝试不使用 Markdown 格式重发
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message.replace("**", "").replace("*", "")
                )
                return True
            except Exception as e2:
                logger.error(f"重试发送也失败: {e2}")
                return False

    def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        同步发送消息（包装异步方法）

        Args:
            message: 消息内容
            parse_mode: 解析模式

        Returns:
            是否发送成功
        """
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(self.send_message_async(message, parse_mode))

    def send_signal(self, signal) -> bool:
        """
        发送套利信号

        Args:
            signal: ArbitrageSignal 对象

        Returns:
            是否发送成功
        """
        message = signal.to_message()
        return self.send_message(message, parse_mode="HTML")

    def send_startup_message(self) -> bool:
        """发送启动通知"""
        message = f"""
🚀 **跨境期权套利监控系统已启动**

⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 监控品种:
├─ 沪铜期权 (SHFE)
└─ CME铜期权 (COMEX)

⚙️ 参数设置:
├─ IV差值阈值: 5%
└─ 监控间隔: 5分钟

系统将在发现套利机会时自动通知。
"""
        return self.send_message(message)

    def send_shutdown_message(self) -> bool:
        """发送停止通知"""
        message = f"""
⏹ **跨境期权套利监控系统已停止**

⏰ 停止时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)

    def send_error_message(self, error: str) -> bool:
        """发送错误通知"""
        message = f"""
❌ **系统错误**

⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

错误信息:
```
{error}
```
"""
        return self.send_message(message)

    def send_daily_summary(self, summary: dict) -> bool:
        """
        发送每日汇总

        Args:
            summary: 汇总数据
        """
        message = f"""
📈 **每日套利监控汇总**

📅 日期: {summary.get('date', datetime.now().strftime('%Y-%m-%d'))}

📊 **市场概况**
├─ 沪铜收盘价: {summary.get('shfe_close', 'N/A')} 元/吨
├─ CME铜收盘价: ${summary.get('cme_close', 'N/A')}/磅
├─ 沪铜 ATM IV: {summary.get('shfe_iv', 'N/A')}%
├─ CME ATM IV: {summary.get('cme_iv', 'N/A')}%
└─ IV差值: {summary.get('iv_diff', 'N/A')}%

📊 **信号统计**
├─ 今日信号数: {summary.get('signal_count', 0)}
├─ 强信号: {summary.get('strong_signals', 0)}
├─ 中信号: {summary.get('medium_signals', 0)}
└─ 弱信号: {summary.get('weak_signals', 0)}

💡 **建议**
{summary.get('recommendation', '继续观察市场')}
"""
        return self.send_message(message)


class TelegramNotifierSimple:
    """简化版 Telegram 通知器（使用 requests）"""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """使用 requests 发送消息"""
        try:
            import requests

            url = f"{self.api_url}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }

            response = requests.post(url, data=data, timeout=10)
            result = response.json()

            if result.get("ok"):
                logger.info("Telegram 消息发送成功")
                return True
            else:
                logger.error(f"Telegram API 返回错误: {result}")
                # 尝试不使用格式化
                data["text"] = message.replace("**", "").replace("*", "").replace("`", "")
                del data["parse_mode"]
                response = requests.post(url, data=data, timeout=10)
                return response.json().get("ok", False)

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    def send_signal(self, signal) -> bool:
        """发送套利信号"""
        return self.send_message(signal.to_message(), parse_mode="HTML")


def get_notifier(bot_token: str, chat_id: str, use_simple: bool = False):
    """
    获取通知器实例

    Args:
        bot_token: Bot Token
        chat_id: Chat ID
        use_simple: 是否使用简化版（仅依赖 requests）

    Returns:
        通知器实例
    """
    if use_simple:
        return TelegramNotifierSimple(bot_token, chat_id)

    try:
        return TelegramNotifier(bot_token, chat_id)
    except Exception:
        logger.warning("使用简化版通知器")
        return TelegramNotifierSimple(bot_token, chat_id)


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)

    # 使用测试 token 和 chat_id（需要替换为真实值）
    BOT_TOKEN = "YOUR_BOT_TOKEN"
    CHAT_ID = "YOUR_CHAT_ID"

    notifier = get_notifier(BOT_TOKEN, CHAT_ID, use_simple=True)

    # 测试发送
    test_message = """
🔔 **测试消息**

这是一条测试消息，用于验证 Telegram 通知功能是否正常工作。

⏰ 时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if notifier.send_message(test_message):
        print("测试消息发送成功！")
    else:
        print("测试消息发送失败，请检查 Token 和 Chat ID")
