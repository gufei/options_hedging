"""
套利信号分析模块 - 分析波动率差异并生成交易信号
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum

from data_fetcher import MarketSnapshot

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    """信号方向"""
    BUY_SHFE_SELL_CME = "buy_shfe_sell_cme"   # 买沪铜IV，卖CME IV
    SELL_SHFE_BUY_CME = "sell_shfe_buy_cme"   # 卖沪铜IV，买CME IV
    NO_SIGNAL = "no_signal"


class SignalStrength(Enum):
    """信号强度"""
    STRONG = "strong"      # IV差 > 10%
    MEDIUM = "medium"      # IV差 5-10%
    WEAK = "weak"          # IV差 3-5%


@dataclass
class ArbitrageSignal:
    """套利信号"""
    direction: SignalDirection
    strength: SignalStrength
    iv_diff: float                     # 波动率差（百分点）
    shfe_iv: float                     # 沪铜IV
    cme_iv: float                      # CME IV
    shfe_price: float                  # 沪铜价格
    cme_price: float                   # CME价格（美元/磅）
    recommended_action: str            # 推荐操作
    risk_assessment: str               # 风险评估
    expected_profit: float             # 预期收益（元）
    timestamp: datetime = field(default_factory=datetime.now)

    def to_message(self) -> str:
        """生成通知消息（HTML格式）"""
        direction_text = {
            SignalDirection.BUY_SHFE_SELL_CME: "📈 买沪铜 + 卖CME",
            SignalDirection.SELL_SHFE_BUY_CME: "📉 卖沪铜 + 买CME",
            SignalDirection.NO_SIGNAL: "⏸ 无信号"
        }

        strength_emoji = {
            SignalStrength.STRONG: "🔴强",
            SignalStrength.MEDIUM: "🟡中",
            SignalStrength.WEAK: "🟢弱"
        }

        msg = f"""🔔 <b>跨境期权套利信号</b>

⏰ {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>市场数据</b>
• 沪铜: {self.shfe_price:,.0f} 元/吨
• CME: ${self.cme_price:.4f}/磅
• 沪铜IV: {self.shfe_iv:.2f}%
• CME IV: {self.cme_iv:.2f}%
• <b>IV差值: {self.iv_diff:+.2f}%</b>

🎯 <b>交易信号</b>
• 方向: {direction_text[self.direction]}
• 强度: {strength_emoji[self.strength]}
• 预期收益: {self.expected_profit:,.0f} 元/套

📋 <b>操作指令</b>
{self.recommended_action}
⚠️ <b>风险提示</b>
{self.risk_assessment}
"""
        return msg


class ArbitrageAnalyzer:
    """套利分析器"""

    def __init__(self, config: Dict = None):
        """
        初始化分析器

        Args:
            config: 配置参数
        """
        self.config = config or {}
        self.iv_threshold = self.config.get('iv_threshold', 5.0)
        self.min_iv_diff = self.config.get('min_iv_diff', 3.0)
        self.usd_cny_rate = self.config.get('usd_cny_rate', 7.20)

        # 历史信号记录（避免重复发送）
        self.signal_history: List[ArbitrageSignal] = []
        self.last_signal_time: Optional[datetime] = None

    def analyze(
        self,
        shfe_data: Optional[MarketSnapshot],
        cme_data: Optional[MarketSnapshot]
    ) -> Optional[ArbitrageSignal]:
        """
        分析套利机会

        Args:
            shfe_data: 沪铜市场数据
            cme_data: CME市场数据

        Returns:
            ArbitrageSignal 或 None
        """
        if not shfe_data or not cme_data:
            logger.warning("数据不完整，无法分析")
            return None

        # 计算 IV 差值
        iv_diff = cme_data.atm_iv - shfe_data.atm_iv

        logger.info(f"IV分析: 沪铜={shfe_data.atm_iv:.2f}%, CME={cme_data.atm_iv:.2f}%, 差值={iv_diff:+.2f}%")

        # 判断是否有套利机会
        if abs(iv_diff) < self.min_iv_diff:
            logger.info(f"IV差值 {abs(iv_diff):.2f}% 小于阈值 {self.min_iv_diff}%，无套利机会")
            return None

        # 确定信号方向
        if iv_diff > 0:
            # CME IV 高于 沪铜 IV -> 买沪铜期权，卖CME期权
            direction = SignalDirection.BUY_SHFE_SELL_CME
        else:
            # 沪铜 IV 高于 CME IV -> 卖沪铜期权，买CME期权
            direction = SignalDirection.SELL_SHFE_BUY_CME

        # 确定信号强度
        strength = self._get_signal_strength(abs(iv_diff))

        # 生成推荐操作
        recommended_action = self._generate_recommendation(
            direction, shfe_data, cme_data, iv_diff
        )

        # 风险评估
        risk_assessment = self._assess_risk(direction, shfe_data, cme_data)

        # 预期收益估算
        expected_profit = self._estimate_profit(abs(iv_diff), shfe_data, cme_data)

        signal = ArbitrageSignal(
            direction=direction,
            strength=strength,
            iv_diff=iv_diff,
            shfe_iv=shfe_data.atm_iv,
            cme_iv=cme_data.atm_iv,
            shfe_price=shfe_data.underlying_price,
            cme_price=cme_data.underlying_price,
            recommended_action=recommended_action,
            risk_assessment=risk_assessment,
            expected_profit=expected_profit,
            timestamp=datetime.now()
        )

        # 检查是否与最近信号重复
        if self._is_duplicate_signal(signal):
            logger.info("与最近信号重复，跳过")
            return None

        self.signal_history.append(signal)
        self.last_signal_time = datetime.now()

        return signal

    def _get_signal_strength(self, iv_diff: float) -> SignalStrength:
        """确定信号强度"""
        if iv_diff >= 10.0:
            return SignalStrength.STRONG
        elif iv_diff >= 5.0:
            return SignalStrength.MEDIUM
        else:
            return SignalStrength.WEAK

    def _get_contract_month(self) -> tuple:
        """
        获取当前主力合约月份

        Returns:
            (shfe_month, cme_month_code, cme_year)
            例如: ("2602", "H", "26") 表示2026年2月/3月合约
        """
        now = datetime.now()

        # 沪铜主力合约通常是下月或下下月
        # 简化逻辑：取下下月
        month = now.month + 2
        year = now.year
        if month > 12:
            month -= 12
            year += 1

        shfe_month = f"{year % 100:02d}{month:02d}"  # 如 "2602"

        # CME 月份代码映射
        cme_month_codes = {
            1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
            7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
        }
        cme_month_code = cme_month_codes[month]
        cme_year = f"{year % 100:02d}"

        return shfe_month, cme_month_code, cme_year

    def _generate_recommendation(
        self,
        direction: SignalDirection,
        shfe_data: MarketSnapshot,
        cme_data: MarketSnapshot,
        iv_diff: float
    ) -> str:
        """生成具体操作建议，包含具体合约代码"""

        # 获取合约月份
        shfe_month, cme_month_code, cme_year = self._get_contract_month()

        # 计算行权价（取整）
        shfe_strike = round(shfe_data.underlying_price / 1000) * 1000  # 取整千
        cme_strike_cents = round(cme_data.underlying_price * 100)  # 转换为美分整数
        cme_strike = cme_data.underlying_price

        # 生成具体合约代码
        # 沪铜期权代码格式: CU2602C103000
        shfe_call = f"CU{shfe_month}C{int(shfe_strike)}"
        shfe_put = f"CU{shfe_month}P{int(shfe_strike)}"

        # CME铜期权代码格式: HGH26 C 4.70 或 HGH26C470
        cme_call = f"HG{cme_month_code}{cme_year} C {cme_strike:.2f}"
        cme_put = f"HG{cme_month_code}{cme_year} P {cme_strike:.2f}"

        # 简化代码（用于交易系统）
        cme_call_short = f"HG{cme_month_code}{cme_year}C{cme_strike_cents}"
        cme_put_short = f"HG{cme_month_code}{cme_year}P{cme_strike_cents}"

        if direction == SignalDirection.BUY_SHFE_SELL_CME:
            return f"""
<b>【买入】上期所</b>
• <code>{shfe_call}</code> 看涨
• <code>{shfe_put}</code> 看跌

<b>【卖出】CME</b>
• <code>{cme_call_short}</code> 看涨
• <code>{cme_put_short}</code> 看跌

行权价: 沪铜 {shfe_strike:,.0f} / CME ${cme_strike:.2f}
头寸: 沪铜2手 + CME 1手
汇率对冲: 买入CNH期货
"""
        else:
            return f"""
<b>【卖出】上期所</b>
• <code>{shfe_call}</code> 看涨
• <code>{shfe_put}</code> 看跌

<b>【买入】CME</b>
• <code>{cme_call_short}</code> 看涨
• <code>{cme_put_short}</code> 看跌

行权价: 沪铜 {shfe_strike:,.0f} / CME ${cme_strike:.2f}
头寸: 沪铜2手 + CME 1手
汇率对冲: 卖出CNH期货
"""

    def _assess_risk(
        self,
        direction: SignalDirection,
        shfe_data: MarketSnapshot,
        cme_data: MarketSnapshot
    ) -> str:
        """风险评估"""
        if direction == SignalDirection.SELL_SHFE_BUY_CME:
            seller_risk = "境内卖权有无限亏损风险"
        else:
            seller_risk = "CME卖权有无限亏损风险"

        return f"""• 基差: 两市价格可能背离
• 汇率: USD/CNY波动
• 卖方: {seller_risk}
• 到期: 确保两边到期日接近"""

    def _estimate_profit(
        self,
        iv_diff: float,
        shfe_data: MarketSnapshot,
        cme_data: MarketSnapshot
    ) -> float:
        """
        估算预期收益

        基于波动率差异和Vega估算
        """
        # 简化估算：假设 Vega ≈ 0.1 * 标的价格 * sqrt(T)
        # 每1%的IV变化带来的收益

        # 沪铜一手 = 5吨
        shfe_vega_per_hand = shfe_data.underlying_price * 5 * 0.001  # 约 500元/%/手

        # CME一手 = 25000磅 ≈ 11.34吨
        # 转换为人民币
        cme_vega_per_hand = cme_data.underlying_price * 25000 * 0.001 * self.usd_cny_rate

        # 组合配比：CME 1手 ≈ 沪铜 2手
        # 套利收益 ≈ IV差 * 平均Vega
        avg_vega = (shfe_vega_per_hand * 2 + cme_vega_per_hand) / 2
        gross_profit = iv_diff * avg_vega

        # 扣除成本（约20%）
        net_profit = gross_profit * 0.8

        return net_profit

    def _is_duplicate_signal(self, signal: ArbitrageSignal) -> bool:
        """检查是否与最近信号重复"""
        if not self.last_signal_time:
            return False

        # 30分钟内相同方向的信号视为重复
        time_diff = (signal.timestamp - self.last_signal_time).total_seconds()
        if time_diff < 1800:  # 30分钟
            if self.signal_history:
                last_signal = self.signal_history[-1]
                if last_signal.direction == signal.direction:
                    # IV差变化小于2%视为重复
                    if abs(last_signal.iv_diff - signal.iv_diff) < 2.0:
                        return True

        return False


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)

    from data_fetcher import DataFetcherManager

    manager = DataFetcherManager()
    data = manager.get_all_data()

    analyzer = ArbitrageAnalyzer({
        'iv_threshold': 5.0,
        'min_iv_diff': 3.0,
        'usd_cny_rate': 7.20
    })

    signal = analyzer.analyze(data['SHFE'], data['CME'])

    if signal:
        print(signal.to_message())
    else:
        print("当前无套利信号")
