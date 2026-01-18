"""
多品种跨境期权套利监控系统 - 主程序

监控铜、黄金、白银、原油的波动率差异，发现套利机会时通过Telegram通知
"""

import logging
import time
import signal
import sys
import warnings
from datetime import datetime
from typing import Optional, Dict

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    MONITOR_INTERVAL,
    USD_CNY_RATE,
    LOG_LEVEL,
    LOG_FILE,
    SHFE_TRADING_HOURS
)
from instruments import INSTRUMENTS, get_enabled_instruments
from multi_data_fetcher import MultiInstrumentFetcher
from multi_analyzer import MultiArbitrageAnalyzer
from telegram_notifier import get_notifier

# 过滤akshare的非交易日警告（不影响功能，只是为了日志更清晰）
warnings.filterwarnings('ignore', message='.*非交易日.*')
warnings.filterwarnings('ignore', module='akshare.option.option_commodity')

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


class MultiInstrumentMonitor:
    """多品种套利监控器"""

    def __init__(self):
        logger.info("初始化多品种套利监控系统...")

        # 数据获取器
        self.fetcher = MultiInstrumentFetcher()

        # 分析器
        self.analyzer = MultiArbitrageAnalyzer({
            'usd_cny_rate': USD_CNY_RATE
        })

        # 通知器
        self.notifier = get_notifier(
            TELEGRAM_BOT_TOKEN,
            TELEGRAM_CHAT_ID,
            use_simple=True
        )

        # 运行状态
        self.running = False
        self.last_check_time: Optional[datetime] = None

        # 统计
        self.stats = {
            'total_checks': 0,
            'signals_by_instrument': {
                inst: 0 for inst in get_enabled_instruments()
            }
        }

        # 上次信号时间（避免重复通知）
        self.last_signal_time: Dict[str, datetime] = {}

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        # Windows 不支持 SIGTERM，需要条件判断
        if sys.platform != 'win32':
            signal.signal(signal.SIGTERM, self._signal_handler)

        names = ', '.join(
            INSTRUMENTS[i].name for i in get_enabled_instruments()
        )
        logger.info(f"监控品种: {names}")

    def _signal_handler(self, signum, frame):
        logger.info(f"收到信号 {signum}，准备停止...")
        self.stop()

    def is_trading_hours(self) -> bool:
        """检查是否在交易时段"""
        now = datetime.now()
        current_time = now.strftime('%H:%M')

        # 周末不交易
        if now.weekday() >= 5:
            return False

        day_start = SHFE_TRADING_HOURS['day']['start']
        day_end = SHFE_TRADING_HOURS['day']['end']
        night_start = SHFE_TRADING_HOURS['night']['start']
        night_end = SHFE_TRADING_HOURS['night']['end']

        in_day_session = day_start <= current_time <= day_end
        
        # 夜盘跨越午夜的情况
        # 跨日（例如 21:00 到次日 01:00）
        if night_start > night_end:
            in_night_session = (
                current_time >= night_start or current_time <= night_end
            )
        else:
            in_night_session = night_start <= current_time <= night_end

        return in_day_session or in_night_session

    def _should_send_signal(self, instrument: str) -> bool:
        """检查是否应该发送信号（避免短时间重复）"""
        last_time = self.last_signal_time.get(instrument)
        if not last_time:
            return True

        # 30分钟内不重复发送同一品种的信号
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed > 1800

    def check_once(self) -> Dict[str, any]:
        """执行一次全品种检查"""
        logger.info("=" * 50)
        logger.info("执行多品种套利检查...")

        self.stats['total_checks'] += 1
        results = {
            'timestamp': datetime.now(),
            'instruments': {},
            'signals': []
        }

        try:
            # 获取所有品种数据
            all_data = self.fetcher.fetch_all_instruments()

            # 检查数据完整性并发送告警
            failed_instruments = []
            for instrument, data in all_data.items():
                config = data.config

                # 检查数据是否缺失
                if data.domestic is None or data.foreign is None:
                    failed_instruments.append(
                        f"{config.name}: "
                        f"{'国内数据缺失 ' if data.domestic is None else ''}"
                        f"{'境外数据缺失' if data.foreign is None else ''}"
                    )
                    continue

                # 检查IV数据有效性
                if (data.domestic.atm_iv is None or
                        data.foreign.atm_iv is None):
                    failed_instruments.append(
                        f"{config.name}: "
                        f"{'国内IV缺失 ' if data.domestic.atm_iv is None else ''}"  # noqa: E501
                        f"{'境外IV缺失' if data.foreign.atm_iv is None else ''}"
                    )

            # 如果有品种数据获取失败，发送告警（每小时一次）
            if failed_instruments:
                current_hour = datetime.now().hour
                if (not hasattr(self, '_last_alert_hour') or
                        self._last_alert_hour != current_hour):
                    alert_msg = (
                        "【数据获取警告】\n\n"
                        "以下品种数据获取失败:\n" +
                        "\n".join(f"• {msg}" for msg in failed_instruments) +
                        "\n\n请检查数据源连接"
                    )
                    self.notifier.send_message(
                        f"⚠️ {alert_msg}",
                        parse_mode="HTML"
                    )
                    self._last_alert_hour = current_hour
                    logger.warning(
                        f"数据获取告警已发送: {len(failed_instruments)}个品种失败"
                    )

            # 分析所有品种
            arb_signals = self.analyzer.analyze_all(all_data)

            # 记录数据
            for instrument, data in all_data.items():
                results['instruments'][instrument] = {
                    'name': data.config.name,
                    'domestic_iv': (
                        data.domestic.atm_iv if data.domestic else None
                    ),
                    'foreign_iv': (
                        data.foreign.atm_iv if data.foreign else None
                    ),
                    'iv_diff': data.iv_diff
                }

            # 发送信号通知
            for arb_signal in arb_signals:
                if self._should_send_signal(arb_signal.instrument):
                    inst_name = arb_signal.instrument_name
                    logger.info(f"发送 {inst_name} 套利信号...")

                    msg_sent = self.notifier.send_message(
                        arb_signal.to_message(),
                        parse_mode="HTML"
                    )
                    if msg_sent:
                        self.stats['signals_by_instrument'][
                            arb_signal.instrument
                        ] += 1
                        self.last_signal_time[
                            arb_signal.instrument
                        ] = datetime.now()
                        logger.info(f"{inst_name} 通知发送成功")
                    else:
                        logger.error(f"{inst_name} 通知发送失败")

                results['signals'].append(arb_signal)

            self.last_check_time = datetime.now()

        except Exception as e:
            logger.error(f"检查出错: {e}", exc_info=True)

        return results

    def run(self):
        """启动监控循环"""
        logger.info("启动多品种套利监控...")
        self.running = True

        # 发送启动通知
        self._send_startup_message()

        try:
            while self.running:
                if self.is_trading_hours():
                    self.check_once()
                else:
                    logger.debug("当前非交易时段")

                logger.info(f"等待 {MONITOR_INTERVAL} 秒...")
                time.sleep(MONITOR_INTERVAL)

        except KeyboardInterrupt:
            logger.info("收到中断信号")
        finally:
            self.stop()

    def _send_startup_message(self):
        """发送启动通知"""
        instruments_list = "\n".join(
            f"• {INSTRUMENTS[i].name} "
            f"({INSTRUMENTS[i].domestic_symbol}/"
            f"{INSTRUMENTS[i].foreign_symbol})"
            for i in get_enabled_instruments()
        )

        msg = f"""🚀 <b>多品种套利监控系统已启动</b>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>监控品种</b>
{instruments_list}

⚙️ <b>参数</b>
• 监控间隔: {MONITOR_INTERVAL}秒
• 交易时段: 日盘9:00-15:00 / 夜盘21:00-01:00
"""  # noqa: E501
        self.notifier.send_message(msg, parse_mode="HTML")

    def stop(self):
        """停止监控"""
        logger.info("停止监控...")
        self.running = False

        msg = f"""⏹ <b>多品种套利监控系统已停止</b>

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>本次运行统计</b>
• 检查次数: {self.stats['total_checks']}
"""
        self.notifier.send_message(msg, parse_mode="HTML")


def main():
    # 设置控制台编码为 UTF-8（Windows 兼容性）
    import sys
    if sys.platform == 'win32':
        if sys.stdout.encoding != 'utf-8':
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("""
    ╔════════════════════════════════════════════════════╗
    ║     多品种跨境期权套利监控系统 v2.0                 ║
    ║     Multi-Instrument Options Arbitrage Monitor     ║
    ╠════════════════════════════════════════════════════╣
    ║  监控品种: 铜 / 黄金 / 白银 / 原油                  ║
    ║  策略: 波动率套利                                   ║
    ║  通知: Telegram Bot                                ║
    ╚════════════════════════════════════════════════════╝
    """)

    # 检查配置
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n警告: 请先配置 Telegram Bot Token!")
        sys.exit(1)

    monitor = MultiInstrumentMonitor()

    # 命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == '--check-once':
            results = monitor.check_once()

            print("\n" + "=" * 50)
            print("检查结果汇总")
            print("=" * 50)

            for inst, data in results['instruments'].items():
                name = data['name']
                iv_diff = data['iv_diff']
                if iv_diff is not None:
                    has_signal = any(
                        s.instrument == inst for s in results['signals']
                    )
                    status = "[SIGNAL]" if has_signal else "[--]"
                    print(f"{name}: IV diff {iv_diff:+.2f}% {status}")

            print(f"\n发现 {len(results['signals'])} 个套利信号")
            sys.exit(0)

        elif sys.argv[1] == '--list':
            print("\n可监控品种列表:")
            print("-" * 40)
            for key, config in INSTRUMENTS.items():
                status = "✓" if config.enabled else "✗"
                print(f"{status} {config.name} ({config.name_en})")
                print(
                    f"    国内: {config.domestic_exchange} "
                    f"{config.domestic_symbol}"
                )
                print(
                    f"    境外: {config.foreign_exchange} "
                    f"{config.foreign_symbol}"
                )
                print(f"    IV阈值: {config.iv_open_threshold}%")
            sys.exit(0)

    # 正常运行
    monitor.run()


if __name__ == "__main__":
    main()
