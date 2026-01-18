"""
多品种套利分析模块
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

from instruments import InstrumentConfig, INSTRUMENTS, CME_MONTH_CODES
from multi_data_fetcher import InstrumentData

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    BUY_DOMESTIC_SELL_FOREIGN = "buy_domestic_sell_foreign"
    SELL_DOMESTIC_BUY_FOREIGN = "sell_domestic_buy_foreign"
    NO_SIGNAL = "no_signal"


class SignalStrength(Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


@dataclass
class MultiArbitrageSignal:
    """多品种套利信号"""
    instrument: str                    # 品种代码
    instrument_name: str               # 品种名称
    direction: SignalDirection
    strength: SignalStrength
    iv_diff: float
    domestic_iv: float
    foreign_iv: float
    domestic_price: float
    foreign_price: float
    domestic_unit: str
    foreign_unit: str
    recommended_action: str
    risk_assessment: str
    expected_profit: float
    contracts: dict                    # 合约代码
    timestamp: datetime = field(default_factory=datetime.now)

    def to_message(self) -> str:
        """生成通知消息"""
        direction_text = {
            SignalDirection.BUY_DOMESTIC_SELL_FOREIGN: f"📈 买{self.instrument_name} + 卖境外",
            SignalDirection.SELL_DOMESTIC_BUY_FOREIGN: f"📉 卖{self.instrument_name} + 买境外",
            SignalDirection.NO_SIGNAL: "⏸ 无信号"
        }

        strength_emoji = {
            SignalStrength.STRONG: "🔴强",
            SignalStrength.MEDIUM: "🟡中",
            SignalStrength.WEAK: "🟢弱"
        }

        msg = f"""🔔 <b>【{self.instrument_name}】套利信号</b>

⏰ {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

📊 <b>市场数据</b>
• 国内: {self.domestic_price:,.2f} {self.domestic_unit}
• 境外: {self.foreign_price:,.4f} {self.foreign_unit}
• 国内IV: {self.domestic_iv:.2f}%
• 境外IV: {self.foreign_iv:.2f}%
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


class MultiArbitrageAnalyzer:
    """多品种套利分析器"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.usd_cny_rate = self.config.get('usd_cny_rate', 7.20)
        self.signal_history: Dict[str, List] = {}

    def analyze(self, inst_data: InstrumentData) -> Optional[MultiArbitrageSignal]:
        """
        分析单个品种的套利机会

        Args:
            inst_data: 品种数据

        Returns:
            MultiArbitrageSignal 或 None
        """
        if not inst_data.domestic or not inst_data.foreign:
            return None

        config = inst_data.config
        iv_diff = inst_data.iv_diff

        # 检查是否超过阈值
        if abs(iv_diff) < config.min_iv_diff:
            logger.info(f"{config.name}: IV差 {iv_diff:.2f}% 小于阈值 {config.min_iv_diff}%")
            return None

        if abs(iv_diff) < config.iv_open_threshold:
            logger.info(f"{config.name}: IV差 {iv_diff:.2f}% 未达开仓阈值 {config.iv_open_threshold}%")
            return None

        # 确定方向
        if iv_diff > 0:
            direction = SignalDirection.BUY_DOMESTIC_SELL_FOREIGN
        else:
            direction = SignalDirection.SELL_DOMESTIC_BUY_FOREIGN

        # 确定强度
        strength = self._get_strength(abs(iv_diff), config)

        # 获取合约代码
        contracts = self._get_contracts(inst_data)

        # 生成操作建议
        recommended_action = self._generate_recommendation(
            direction, inst_data, contracts
        )

        # 风险评估
        risk_assessment = self._assess_risk(direction, config)

        # 预估收益
        expected_profit = self._estimate_profit(abs(iv_diff), inst_data)

        signal = MultiArbitrageSignal(
            instrument=inst_data.instrument,
            instrument_name=config.name,
            direction=direction,
            strength=strength,
            iv_diff=iv_diff,
            domestic_iv=inst_data.domestic.atm_iv,
            foreign_iv=inst_data.foreign.atm_iv,
            domestic_price=inst_data.domestic.price,
            foreign_price=inst_data.foreign.price,
            domestic_unit=config.domestic_unit,
            foreign_unit=config.foreign_unit,
            recommended_action=recommended_action,
            risk_assessment=risk_assessment,
            expected_profit=expected_profit,
            contracts=contracts
        )

        return signal

    def analyze_all(self, all_data: Dict[str, InstrumentData]) -> List[MultiArbitrageSignal]:
        """
        分析所有品种

        Returns:
            信号列表
        """
        signals = []

        for instrument, data in all_data.items():
            signal = self.analyze(data)
            if signal:
                signals.append(signal)
                logger.info(f"{data.config.name}: 发现套利信号，IV差={signal.iv_diff:.2f}%")

        return signals

    def _get_strength(self, iv_diff: float, config: InstrumentConfig) -> SignalStrength:
        """确定信号强度"""
        if iv_diff >= config.iv_open_threshold * 1.5:
            return SignalStrength.STRONG
        elif iv_diff >= config.iv_open_threshold:
            return SignalStrength.MEDIUM
        else:
            return SignalStrength.WEAK

    def _get_contracts(self, inst_data: InstrumentData) -> dict:
        """获取合约代码"""
        config = inst_data.config
        now = datetime.now()

        # 取下下月合约
        month = now.month + 2
        year = now.year
        if month > 12:
            month -= 12
            year += 1

        year_short = year % 100

        # 国内合约
        domestic_base = f"{config.domestic_symbol}{year_short:02d}{month:02d}"

        # 根据品种计算行权价
        if inst_data.domestic:
            price = inst_data.domestic.price
            if config.domestic_symbol == "CU":
                strike = round(price / 1000) * 1000
            elif config.domestic_symbol == "AU":
                strike = round(price / 10) * 10
            elif config.domestic_symbol == "AG":
                strike = round(price / 100) * 100
            elif config.domestic_symbol == "SC":
                strike = round(price / 10) * 10
            else:
                strike = round(price)
        else:
            strike = 0

        domestic_call = f"{domestic_base}C{int(strike)}"
        domestic_put = f"{domestic_base}P{int(strike)}"

        # 境外合约
        cme_month_code = CME_MONTH_CODES.get(month, 'F')
        foreign_base = f"{config.foreign_symbol}{cme_month_code}{year_short:02d}"

        if inst_data.foreign:
            foreign_price = inst_data.foreign.price
            if config.foreign_symbol == "HG":
                foreign_strike = round(foreign_price * 100)
            elif config.foreign_symbol == "GC":
                foreign_strike = round(foreign_price / 10) * 10
            elif config.foreign_symbol == "SI":
                foreign_strike = round(foreign_price * 2) / 2  # 0.5 increments
                foreign_strike = int(foreign_strike * 100)
            elif config.foreign_symbol == "CL":
                foreign_strike = round(foreign_price)
            else:
                foreign_strike = round(foreign_price)
        else:
            foreign_strike = 0

        foreign_call = f"{foreign_base}C{foreign_strike}"
        foreign_put = f"{foreign_base}P{foreign_strike}"

        return {
            "domestic_call": domestic_call,
            "domestic_put": domestic_put,
            "foreign_call": foreign_call,
            "foreign_put": foreign_put,
            "domestic_strike": strike,
            "foreign_strike": foreign_strike
        }

    def _generate_recommendation(
        self,
        direction: SignalDirection,
        inst_data: InstrumentData,
        contracts: dict
    ) -> str:
        """生成操作建议"""
        config = inst_data.config

        if direction == SignalDirection.BUY_DOMESTIC_SELL_FOREIGN:
            return f"""
<b>【买入】{config.domestic_exchange}</b>
• <code>{contracts['domestic_call']}</code> 看涨
• <code>{contracts['domestic_put']}</code> 看跌

<b>【卖出】{config.foreign_exchange}</b>
• <code>{contracts['foreign_call']}</code> 看涨
• <code>{contracts['foreign_put']}</code> 看跌

行权价: 国内 {contracts['domestic_strike']:,} / 境外 {contracts['foreign_strike']}
汇率对冲: 买入CNH期货
"""
        else:
            return f"""
<b>【卖出】{config.domestic_exchange}</b>
• <code>{contracts['domestic_call']}</code> 看涨
• <code>{contracts['domestic_put']}</code> 看跌

<b>【买入】{config.foreign_exchange}</b>
• <code>{contracts['foreign_call']}</code> 看涨
• <code>{contracts['foreign_put']}</code> 看跌

行权价: 国内 {contracts['domestic_strike']:,} / 境外 {contracts['foreign_strike']}
汇率对冲: 卖出CNH期货
"""

    def _assess_risk(self, direction: SignalDirection, config: InstrumentConfig) -> str:
        """风险评估"""
        if direction == SignalDirection.SELL_DOMESTIC_BUY_FOREIGN:
            seller_risk = "国内卖权有无限亏损风险"
        else:
            seller_risk = "境外卖权有无限亏损风险"

        return f"""• 基差: 两市价格可能背离
• 汇率: USD/CNY波动
• 卖方: {seller_risk}
• 到期: 确保两边到期日接近"""

    def _estimate_profit(self, iv_diff: float, inst_data: InstrumentData) -> float:
        """估算收益"""
        # 简化估算
        config = inst_data.config

        # 基于品种的Vega估算
        vega_factors = {
            "copper": 800,
            "gold": 500,
            "silver": 600,
            "crude_oil": 700
        }

        vega = vega_factors.get(inst_data.instrument, 500)
        gross_profit = iv_diff * vega
        return gross_profit * 0.8  # 扣除成本


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from multi_data_fetcher import MultiInstrumentFetcher

    fetcher = MultiInstrumentFetcher()
    data = fetcher.fetch_all_instruments()

    analyzer = MultiArbitrageAnalyzer({'usd_cny_rate': 7.20})
    signals = analyzer.analyze_all(data)

    print(f"\n发现 {len(signals)} 个套利信号:")
    for signal in signals:
        print(f"\n{signal.instrument_name}: IV差={signal.iv_diff:+.2f}%")
        print(signal.to_message())
