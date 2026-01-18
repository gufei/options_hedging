"""
持仓追踪模块 - 追踪已开仓头寸并生成平仓信号
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from dataclasses import dataclass, asdict, field
from pathlib import Path

logger = logging.getLogger(__name__)

# 持仓数据文件
POSITIONS_FILE = Path(__file__).parent / "positions.json"


@dataclass
class Position:
    """持仓记录"""
    id: str                          # 持仓ID
    open_time: str                   # 开仓时间
    direction: str                   # 'buy_shfe_sell_cme' or 'sell_shfe_buy_cme'

    # 开仓时的数据
    open_shfe_iv: float              # 开仓时沪铜IV
    open_cme_iv: float               # 开仓时CME IV
    open_iv_diff: float              # 开仓时IV差
    open_shfe_price: float           # 开仓时沪铜价格
    open_cme_price: float            # 开仓时CME价格

    # 合约信息
    shfe_call: str                   # 沪铜看涨合约
    shfe_put: str                    # 沪铜看跌合约
    cme_call: str                    # CME看涨合约
    cme_put: str                     # CME看跌合约

    # 到期日（预估）
    expiry_date: str                 # 到期日

    # 状态
    status: str = "open"             # 'open' or 'closed'
    close_time: Optional[str] = None
    close_reason: Optional[str] = None

    # 当前数据（更新用）
    current_iv_diff: Optional[float] = None
    unrealized_pnl: Optional[float] = None


@dataclass
class CloseSignal:
    """平仓信号"""
    position: Position
    reason: str                      # 平仓原因
    current_shfe_iv: float
    current_cme_iv: float
    current_iv_diff: float
    iv_diff_change: float            # IV差变化
    days_to_expiry: int              # 距离到期天数
    estimated_pnl: float             # 预估盈亏
    urgency: str                     # 'high', 'medium', 'low'
    timestamp: datetime = field(default_factory=datetime.now)

    def to_message(self) -> str:
        """生成平仓通知消息"""
        urgency_emoji = {
            'high': '🔴 紧急',
            'medium': '🟡 建议',
            'low': '🟢 可选'
        }

        pnl_emoji = '📈' if self.estimated_pnl > 0 else '📉'

        # 操作指令
        if self.position.direction == 'buy_shfe_sell_cme':
            close_action = """
<b>【平仓-卖出】上期所</b>
• <code>{}</code> 看涨
• <code>{}</code> 看跌

<b>【平仓-买入】CME</b>
• <code>{}</code> 看涨
• <code>{}</code> 看跌""".format(
                self.position.shfe_call,
                self.position.shfe_put,
                self.position.cme_call,
                self.position.cme_put
            )
        else:
            close_action = """
<b>【平仓-买入】上期所</b>
• <code>{}</code> 看涨
• <code>{}</code> 看跌

<b>【平仓-卖出】CME</b>
• <code>{}</code> 看涨
• <code>{}</code> 看跌""".format(
                self.position.shfe_call,
                self.position.shfe_put,
                self.position.cme_call,
                self.position.cme_put
            )

        msg = f"""🔔 <b>平仓信号</b>

⏰ {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>持仓信息</b>
• 开仓时间: {self.position.open_time}
• 开仓IV差: {self.position.open_iv_diff:+.2f}%
• 当前IV差: {self.current_iv_diff:+.2f}%
• IV差变化: {self.iv_diff_change:+.2f}%
• 距到期: {self.days_to_expiry}天

🎯 <b>平仓信号</b>
• 原因: {self.reason}
• 紧急度: {urgency_emoji[self.urgency]}
• {pnl_emoji} 预估盈亏: {self.estimated_pnl:+,.0f} 元

📋 <b>平仓操作</b>
{close_action}
"""
        return msg


class PositionTracker:
    """持仓追踪器"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.positions: List[Position] = []

        # 平仓阈值配置
        self.close_iv_threshold = self.config.get('close_iv_threshold', 5.0)  # IV差收敛到此值平仓
        self.stop_loss_iv_threshold = self.config.get('stop_loss_iv_threshold', 18.0)  # IV差扩大到此值止损
        self.days_before_expiry = self.config.get('days_before_expiry', 7)  # 到期前几天强制平仓
        self.max_holding_days = self.config.get('max_holding_days', 21)  # 最大持仓天数

        # 加载已有持仓
        self._load_positions()

    def _load_positions(self):
        """从文件加载持仓"""
        if POSITIONS_FILE.exists():
            try:
                with open(POSITIONS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.positions = [Position(**p) for p in data]
                logger.info(f"加载了 {len(self.positions)} 个持仓记录")
            except Exception as e:
                logger.error(f"加载持仓失败: {e}")
                self.positions = []
        else:
            self.positions = []

    def _save_positions(self):
        """保存持仓到文件"""
        try:
            with open(POSITIONS_FILE, 'w', encoding='utf-8') as f:
                data = [asdict(p) for p in self.positions]
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("持仓已保存")
        except Exception as e:
            logger.error(f"保存持仓失败: {e}")

    def add_position(self, signal) -> Position:
        """
        添加新持仓

        Args:
            signal: ArbitrageSignal 对象

        Returns:
            新建的 Position
        """
        from arbitrage_analyzer import ArbitrageAnalyzer

        # 生成持仓ID
        pos_id = f"POS_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 获取合约代码
        analyzer = ArbitrageAnalyzer()
        shfe_month, cme_month_code, cme_year = analyzer._get_contract_month()

        shfe_strike = round(signal.shfe_price / 1000) * 1000
        cme_strike_cents = round(signal.cme_price * 100)

        shfe_call = f"CU{shfe_month}C{int(shfe_strike)}"
        shfe_put = f"CU{shfe_month}P{int(shfe_strike)}"
        cme_call = f"HG{cme_month_code}{cme_year}C{cme_strike_cents}"
        cme_put = f"HG{cme_month_code}{cme_year}P{cme_strike_cents}"

        # 预估到期日（下下月第三个周五）
        now = datetime.now()
        expiry_month = now.month + 2
        expiry_year = now.year
        if expiry_month > 12:
            expiry_month -= 12
            expiry_year += 1
        expiry_date = f"{expiry_year}-{expiry_month:02d}-20"  # 简化处理

        position = Position(
            id=pos_id,
            open_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            direction=signal.direction.value,
            open_shfe_iv=signal.shfe_iv,
            open_cme_iv=signal.cme_iv,
            open_iv_diff=signal.iv_diff,
            open_shfe_price=signal.shfe_price,
            open_cme_price=signal.cme_price,
            shfe_call=shfe_call,
            shfe_put=shfe_put,
            cme_call=cme_call,
            cme_put=cme_put,
            expiry_date=expiry_date,
            status="open"
        )

        self.positions.append(position)
        self._save_positions()

        logger.info(f"新增持仓: {pos_id}")
        return position

    def get_open_positions(self) -> List[Position]:
        """获取所有未平仓持仓"""
        return [p for p in self.positions if p.status == "open"]

    def check_close_signals(
        self,
        current_shfe_iv: float,
        current_cme_iv: float
    ) -> List[CloseSignal]:
        """
        检查是否需要平仓

        Args:
            current_shfe_iv: 当前沪铜IV
            current_cme_iv: 当前CME IV

        Returns:
            平仓信号列表
        """
        close_signals = []
        current_iv_diff = current_cme_iv - current_shfe_iv
        now = datetime.now()

        for position in self.get_open_positions():
            signal = None
            reason = None
            urgency = 'low'

            # 计算IV差变化
            iv_diff_change = current_iv_diff - position.open_iv_diff

            # 计算距离到期天数
            try:
                expiry = datetime.strptime(position.expiry_date, '%Y-%m-%d')
                days_to_expiry = (expiry - now).days
            except:
                days_to_expiry = 30  # 默认值

            # 计算持仓天数
            try:
                open_time = datetime.strptime(position.open_time, '%Y-%m-%d %H:%M:%S')
                holding_days = (now - open_time).days
            except:
                holding_days = 0

            # 预估盈亏（简化计算）
            # 基于IV差变化和Vega估算
            if position.direction == 'buy_shfe_sell_cme':
                # 买沪铜卖CME: 希望IV差缩小（current_iv_diff < open_iv_diff）
                estimated_pnl = -iv_diff_change * 800  # 简化：每1%IV差约800元
            else:
                # 卖沪铜买CME: 希望IV差扩大
                estimated_pnl = iv_diff_change * 800

            # 检查平仓条件

            # 1. 获利平仓：IV差收敛
            if position.direction == 'buy_shfe_sell_cme':
                # 买低卖高策略，希望差值缩小
                if abs(current_iv_diff) < self.close_iv_threshold:
                    reason = f"✅ IV差收敛至{current_iv_diff:.1f}%，达到获利目标"
                    urgency = 'medium'
            else:
                # 卖低买高策略，希望差值扩大（较少见）
                if abs(current_iv_diff) > abs(position.open_iv_diff) * 1.5:
                    reason = f"✅ IV差扩大，达到获利目标"
                    urgency = 'medium'

            # 2. 止损：IV差继续扩大（对买低卖高策略不利）
            if position.direction == 'buy_shfe_sell_cme':
                if current_iv_diff > self.stop_loss_iv_threshold:
                    reason = f"⛔ IV差扩大至{current_iv_diff:.1f}%，触发止损"
                    urgency = 'high'

            # 3. 到期临近
            if days_to_expiry <= self.days_before_expiry:
                reason = f"⏰ 距到期仅{days_to_expiry}天，需平仓或移仓"
                urgency = 'high'

            # 4. 持仓时间过长
            if holding_days >= self.max_holding_days and reason is None:
                reason = f"📅 持仓已{holding_days}天，建议评估是否继续持有"
                urgency = 'low'

            # 生成平仓信号
            if reason:
                signal = CloseSignal(
                    position=position,
                    reason=reason,
                    current_shfe_iv=current_shfe_iv,
                    current_cme_iv=current_cme_iv,
                    current_iv_diff=current_iv_diff,
                    iv_diff_change=iv_diff_change,
                    days_to_expiry=days_to_expiry,
                    estimated_pnl=estimated_pnl,
                    urgency=urgency
                )
                close_signals.append(signal)

                # 更新持仓当前数据
                position.current_iv_diff = current_iv_diff
                position.unrealized_pnl = estimated_pnl

        if close_signals:
            self._save_positions()

        return close_signals

    def close_position(self, position_id: str, reason: str = None):
        """
        平仓

        Args:
            position_id: 持仓ID
            reason: 平仓原因
        """
        for position in self.positions:
            if position.id == position_id:
                position.status = "closed"
                position.close_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                position.close_reason = reason
                self._save_positions()
                logger.info(f"持仓 {position_id} 已平仓")
                return

        logger.warning(f"未找到持仓 {position_id}")

    def get_position_summary(self) -> str:
        """获取持仓汇总"""
        open_positions = self.get_open_positions()

        if not open_positions:
            return "当前无持仓"

        summary = f"当前持仓: {len(open_positions)} 个\n"
        for p in open_positions:
            summary += f"\n• {p.id}: IV差 {p.open_iv_diff:+.1f}% → {p.current_iv_diff or '?'}%"

        return summary


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)

    tracker = PositionTracker({
        'close_iv_threshold': 5.0,
        'stop_loss_iv_threshold': 18.0,
        'days_before_expiry': 7
    })

    print("当前持仓:")
    print(tracker.get_position_summary())
