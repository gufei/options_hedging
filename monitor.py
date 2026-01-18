"""
跨境期权套利监控系统 - 主程序

监控沪铜和CME铜期权的波动率差异，发现套利机会时通过Telegram通知
"""

import logging
import time
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional

# 项目模块
from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    IV_DIFF_THRESHOLD,
    MIN_IV_DIFF,
    MONITOR_INTERVAL,
    USD_CNY_RATE,
    LOG_LEVEL,
    LOG_FILE,
    SHFE_TRADING_HOURS,
    CLOSE_IV_THRESHOLD,
    STOP_LOSS_IV_THRESHOLD,
    DAYS_BEFORE_EXPIRY,
    MAX_HOLDING_DAYS
)
from data_fetcher import DataFetcherManager
from arbitrage_analyzer import ArbitrageAnalyzer, SignalStrength
from telegram_notifier import get_notifier
from position_tracker import PositionTracker

# 配置日志
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ArbitrageMonitor:
    """跨境期权套利监控器"""

    def __init__(self):
        """初始化监控器"""
        logger.info("初始化套利监控系统...")

        # 初始化组件
        self.data_manager = DataFetcherManager()
        self.analyzer = ArbitrageAnalyzer({
            'iv_threshold': IV_DIFF_THRESHOLD,
            'min_iv_diff': MIN_IV_DIFF,
            'usd_cny_rate': USD_CNY_RATE
        })
        self.notifier = get_notifier(
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            use_simple=True  # 使用 requests 版本，更简单
        )

        # 持仓追踪器
        self.position_tracker = PositionTracker({
            'close_iv_threshold': CLOSE_IV_THRESHOLD,
            'stop_loss_iv_threshold': STOP_LOSS_IV_THRESHOLD,
            'days_before_expiry': DAYS_BEFORE_EXPIRY,
            'max_holding_days': MAX_HOLDING_DAYS
        })

        # 运行状态
        self.running = False
        self.last_check_time: Optional[datetime] = None
        self.signal_count = 0
        self.error_count = 0

        # 每日统计
        self.daily_stats = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'signals': [],
            'strong_count': 0,
            'medium_count': 0,
            'weak_count': 0
        }

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("套利监控系统初始化完成")

    def _signal_handler(self, signum, frame):
        """处理终止信号"""
        logger.info(f"收到信号 {signum}，准备停止...")
        self.stop()

    def is_trading_hours(self) -> bool:
        """检查是否在交易时段"""
        now = datetime.now()
        current_time = now.strftime('%H:%M')

        # 日盘时段
        day_start = SHFE_TRADING_HOURS['day']['start']
        day_end = SHFE_TRADING_HOURS['day']['end']

        # 夜盘时段
        night_start = SHFE_TRADING_HOURS['night']['start']
        night_end = SHFE_TRADING_HOURS['night']['end']

        # 检查是否在交易时段
        in_day_session = day_start <= current_time <= day_end
        in_night_session = current_time >= night_start or current_time <= night_end

        # 周末不交易
        if now.weekday() >= 5:  # 周六、周日
            return False

        return in_day_session or in_night_session

    def check_once(self) -> Optional[dict]:
        """
        执行一次检查

        Returns:
            检查结果字典
        """
        logger.info("执行套利机会检查...")

        try:
            # 获取市场数据
            data = self.data_manager.get_all_data()

            shfe_data = data.get('SHFE')
            cme_data = data.get('CME')

            if not shfe_data or not cme_data:
                logger.warning("数据获取不完整")
                return None

            # 分析套利机会
            signal = self.analyzer.analyze(shfe_data, cme_data)

            result = {
                'timestamp': datetime.now(),
                'shfe_price': shfe_data.underlying_price,
                'cme_price': cme_data.underlying_price,
                'shfe_iv': shfe_data.atm_iv,
                'cme_iv': cme_data.atm_iv,
                'iv_diff': cme_data.atm_iv - shfe_data.atm_iv,
                'signal': signal
            }

            # 如果有开仓信号，发送通知
            if signal:
                logger.info(f"发现套利信号: IV差={signal.iv_diff:.2f}%, 强度={signal.strength.value}")

                # 发送 Telegram 通知
                if self.notifier.send_signal(signal):
                    self.signal_count += 1
                    self._update_daily_stats(signal)
                    logger.info("开仓通知发送成功")

                    # 记录持仓
                    self.position_tracker.add_position(signal)
                    logger.info("持仓已记录")
                else:
                    logger.error("通知发送失败")

            else:
                logger.info(f"无开仓信号 - 沪铜IV: {shfe_data.atm_iv:.2f}%, CME IV: {cme_data.atm_iv:.2f}%")

            # 检查平仓信号
            close_signals = self.position_tracker.check_close_signals(
                shfe_data.atm_iv,
                cme_data.atm_iv
            )

            for close_signal in close_signals:
                logger.info(f"发现平仓信号: {close_signal.reason}")
                if self.notifier.send_message(close_signal.to_message(), parse_mode="HTML"):
                    logger.info("平仓通知发送成功")
                else:
                    logger.error("平仓通知发送失败")

            self.last_check_time = datetime.now()
            return result

        except Exception as e:
            logger.error(f"检查过程出错: {e}", exc_info=True)
            self.error_count += 1

            # 连续错误过多时发送告警
            if self.error_count >= 5:
                self.notifier.send_error_message(f"连续错误 {self.error_count} 次: {str(e)}")

            return None

    def _update_daily_stats(self, signal):
        """更新每日统计"""
        today = datetime.now().strftime('%Y-%m-%d')

        # 重置每日统计
        if self.daily_stats['date'] != today:
            self.daily_stats = {
                'date': today,
                'signals': [],
                'strong_count': 0,
                'medium_count': 0,
                'weak_count': 0
            }

        self.daily_stats['signals'].append(signal)

        if signal.strength == SignalStrength.STRONG:
            self.daily_stats['strong_count'] += 1
        elif signal.strength == SignalStrength.MEDIUM:
            self.daily_stats['medium_count'] += 1
        else:
            self.daily_stats['weak_count'] += 1

    def run(self):
        """启动监控循环"""
        logger.info("启动套利监控...")
        self.running = True

        # 发送启动通知
        self.notifier.send_startup_message()

        try:
            while self.running:
                # 检查是否在交易时段
                if self.is_trading_hours():
                    self.check_once()
                else:
                    logger.debug("当前非交易时段，跳过检查")

                # 发送每日汇总（每天 15:30）
                now = datetime.now()
                if now.hour == 15 and now.minute == 30:
                    self._send_daily_summary()

                # 等待下一次检查
                logger.debug(f"等待 {MONITOR_INTERVAL} 秒后进行下一次检查...")
                time.sleep(MONITOR_INTERVAL)

        except KeyboardInterrupt:
            logger.info("收到键盘中断，停止监控...")
        except Exception as e:
            logger.error(f"监控循环异常: {e}", exc_info=True)
            self.notifier.send_error_message(f"监控异常退出: {str(e)}")
        finally:
            self.stop()

    def _send_daily_summary(self):
        """发送每日汇总"""
        try:
            data = self.data_manager.get_all_data()

            summary = {
                'date': self.daily_stats['date'],
                'shfe_close': data['SHFE'].underlying_price if data.get('SHFE') else 'N/A',
                'cme_close': data['CME'].underlying_price if data.get('CME') else 'N/A',
                'shfe_iv': data['SHFE'].atm_iv if data.get('SHFE') else 'N/A',
                'cme_iv': data['CME'].atm_iv if data.get('CME') else 'N/A',
                'iv_diff': (data['CME'].atm_iv - data['SHFE'].atm_iv)
                           if data.get('CME') and data.get('SHFE') else 'N/A',
                'signal_count': len(self.daily_stats['signals']),
                'strong_signals': self.daily_stats['strong_count'],
                'medium_signals': self.daily_stats['medium_count'],
                'weak_signals': self.daily_stats['weak_count'],
                'recommendation': self._generate_recommendation()
            }

            self.notifier.send_daily_summary(summary)

        except Exception as e:
            logger.error(f"发送每日汇总失败: {e}")

    def _generate_recommendation(self) -> str:
        """生成每日建议"""
        if self.daily_stats['strong_count'] > 0:
            return "今日出现强套利信号，建议重点关注明日开盘机会"
        elif self.daily_stats['medium_count'] > 0:
            return "今日有中等强度信号，建议保持观察"
        else:
            return "今日无明显套利机会，继续监控"

    def stop(self):
        """停止监控"""
        logger.info("停止套利监控...")
        self.running = False

        # 发送停止通知
        self.notifier.send_shutdown_message()

        logger.info("套利监控已停止")


def main():
    """主函数"""
    print("""
    ╔═══════════════════════════════════════════════════╗
    ║     跨境期权套利监控系统 v1.0                      ║
    ║     Cross-Border Options Arbitrage Monitor        ║
    ╠═══════════════════════════════════════════════════╣
    ║  监控品种: 沪铜期权 (SHFE) + CME铜期权            ║
    ║  策略: 波动率套利                                  ║
    ║  通知: Telegram Bot                               ║
    ╚═══════════════════════════════════════════════════╝
    """)

    # 检查配置
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n⚠️  警告: 请先配置 Telegram Bot Token!")
        print("   编辑 config.py 文件，设置 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID")
        print("\n如何获取 Bot Token:")
        print("   1. 在 Telegram 中搜索 @BotFather")
        print("   2. 发送 /newbot 创建新机器人")
        print("   3. 复制获得的 Token")
        print("\n如何获取 Chat ID:")
        print("   1. 在 Telegram 中搜索 @userinfobot")
        print("   2. 发送任意消息，获取你的 Chat ID")
        print()

        response = input("是否使用测试模式运行？(y/n): ")
        if response.lower() != 'y':
            sys.exit(1)

    # 启动监控
    monitor = ArbitrageMonitor()

    # 命令行参数处理
    if len(sys.argv) > 1:
        if sys.argv[1] == '--check-once':
            # 只执行一次检查
            result = monitor.check_once()
            if result:
                print(f"\n检查结果:")
                print(f"  沪铜价格: {result['shfe_price']:,.0f} 元/吨")
                print(f"  CME价格: ${result['cme_price']:.4f}/磅")
                print(f"  沪铜 IV: {result['shfe_iv']:.2f}%")
                print(f"  CME IV: {result['cme_iv']:.2f}%")
                print(f"  IV差值: {result['iv_diff']:+.2f}%")
                if result['signal']:
                    print(f"\n  [OK] 发现套利信号!")
                else:
                    print(f"\n  [--] 无套利信号")
            sys.exit(0)

        elif sys.argv[1] == '--test-notify':
            # 测试通知
            print("发送测试通知...")
            monitor.notifier.send_message("🔔 测试通知 - 套利监控系统正常运行")
            print("如果收到通知，说明配置正确！")
            sys.exit(0)

    # 正常运行监控
    monitor.run()


if __name__ == "__main__":
    main()
