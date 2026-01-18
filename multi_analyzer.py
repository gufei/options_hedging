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
from option_contracts import DomesticOptionContractFetcher, ForeignOptionContractFetcher

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

        # 初始化期权合约获取器
        self.domestic_fetcher = DomesticOptionContractFetcher()
        self.foreign_fetcher = ForeignOptionContractFetcher()
        
        # 初始化网页爬虫（用于获取CME真实期权合约）
        self.web_scraper = None
        self._init_web_scraper()
    
    def _init_web_scraper(self):
        """初始化CME网页爬虫"""
        try:
            from cme_web_scraper import CMEWebScraper
            self.web_scraper = CMEWebScraper()
            logger.info("CME网页爬虫初始化成功")
        except Exception as e:
            logger.warning(f"CME网页爬虫初始化失败: {e}")
            self.web_scraper = None

    def analyze(self, inst_data: InstrumentData) -> Optional[MultiArbitrageSignal]:
        """
        分析单个品种的套利机会

        Args:
            inst_data: 品种数据

        Returns:
            MultiArbitrageSignal 或 None
        """
        if not inst_data.domestic or not inst_data.foreign:
            logger.warning(f"{inst_data.config.name} 数据不完整，跳过分析")
            return None
        
        # 验证IV数据有效性（必须为真实数据，不能为None）
        if inst_data.domestic.atm_iv is None or inst_data.foreign.atm_iv is None:
            logger.warning(
                f"{inst_data.config.name} IV数据不完整 "
                f"(国内: {inst_data.domestic.atm_iv}, "
                f"境外: {inst_data.foreign.atm_iv})，"
                f"无法进行套利分析"
            )
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
        """获取期权合约代码（从数据源动态获取）"""
        config = inst_data.config
        now = datetime.now()

        # 计算下下月
        month = now.month + 2
        year = now.year
        if month > 12:
            month -= 12
            year += 1

        year_short = year % 100
        month_str = f"{year_short:02d}{month:02d}"

        contracts = {
            "domestic_call": "",
            "domestic_put": "",
            "foreign_call": "",
            "foreign_put": "",
            "domestic_strike": 0,
            "foreign_strike": 0,
            "domestic_is_placeholder": False,  # 标记国内合约是否为占位符
            "foreign_is_placeholder": False    # 标记境外合约是否为占位符
        }

        # 获取国内期权合约
        if inst_data.domestic:
            try:
                atm_contract = self.domestic_fetcher.get_atm_contract(
                    inst_data.instrument,
                    inst_data.domestic.price,
                    month_str
                )

                if atm_contract:
                    contracts["domestic_call"] = atm_contract.call_symbol
                    contracts["domestic_put"] = atm_contract.put_symbol
                    contracts["domestic_strike"] = atm_contract.strike_price
                    
                    logger.info(
                        f"{config.name} 国内期权: "
                        f"{atm_contract.call_symbol}/{atm_contract.put_symbol} "
                        f"行权价 {atm_contract.strike_price}"
                    )
                else:
                    logger.warning(f"{config.name} 未找到国内ATM期权，无法提供真实合约")

            except Exception as e:
                logger.error(f"获取{config.name}国内期权失败: {e}")
                logger.warning(f"{config.name} 无法提供真实国内期权合约")

        # 获取境外期权合约
        if inst_data.foreign:
            try:
                # 优先使用网页爬虫获取真实CME期权数据
                foreign_contract = None
                
                if self.web_scraper:
                    try:
                        logger.info(f"{config.name} 尝试从网页获取CME期权合约")
                        option_data = self.web_scraper.get_barchart_options(
                            inst_data.instrument,
                            inst_data.foreign.price
                        )
                        
                        if option_data:
                            foreign_contract = {
                                'call_symbol': option_data['call_symbol'],
                                'put_symbol': option_data['put_symbol'],
                                'strike': option_data['strike']
                            }
                            logger.info(
                                f"{config.name} [Web] 成功获取境外期权合约: "
                                f"{option_data['call_symbol']}/{option_data['put_symbol']}"
                            )
                    except Exception as e:
                        logger.debug(f"{config.name} 网页获取期权合约失败: {e}")
                
                # 如果网页获取失败，尝试yfinance
                if not foreign_contract:
                    logger.info(f"{config.name} 尝试从yfinance获取期权合约")
                    foreign_contract = self.foreign_fetcher.get_atm_contract(
                        config.foreign_yf_symbol,
                        inst_data.foreign.price
                    )
                
                if foreign_contract:
                    contracts["foreign_call"] = foreign_contract['call_symbol']
                    contracts["foreign_put"] = foreign_contract['put_symbol']
                    contracts["foreign_strike"] = foreign_contract['strike']
                    logger.info(
                        f"{config.name} 境外期权: "
                        f"{foreign_contract['call_symbol']}/{foreign_contract['put_symbol']} "
                        f"行权价 {foreign_contract['strike']}"
                    )
                else:
                    logger.warning(f"{config.name} 未找到境外ATM期权，无真实合约数据")
                    # 标记为无真实数据
                    contracts["foreign_call"] = "无真实期权数据"
                    contracts["foreign_put"] = "使用历史波动率估算IV"
                    contracts["foreign_strike"] = inst_data.foreign.price if inst_data.foreign else 0

            except Exception as e:
                logger.error(f"获取{config.name}境外期权失败: {e}")
                logger.warning(f"{config.name} 无真实境外期权数据")
                # 标记为无真实数据
                contracts["foreign_call"] = "无真实期权数据"
                contracts["foreign_put"] = "使用历史波动率估算IV"
                contracts["foreign_strike"] = inst_data.foreign.price if inst_data.foreign else 0

        return contracts
    def _generate_recommendation(
        self,
        direction: SignalDirection,
        inst_data: InstrumentData,
        contracts: dict
    ) -> str:
        """生成操作建议"""
        config = inst_data.config
        
        # 准备数据来源说明（预留，目前不使用）
        domestic_note = ""
        foreign_note = ""

        if direction == SignalDirection.BUY_DOMESTIC_SELL_FOREIGN:
            return f"""
<b>【买入】{config.domestic_exchange}</b>
• <code>{contracts['domestic_call']}</code> 看涨
• <code>{contracts['domestic_put']}</code> 看跌{domestic_note}

<b>【卖出】{config.foreign_exchange}</b>
• <code>{contracts['foreign_call']}</code> 看涨
• <code>{contracts['foreign_put']}</code> 看跌{foreign_note}

行权价: 国内 {contracts['domestic_strike']:,} / 境外 {contracts['foreign_strike']}
汇率对冲: 买入CNH期货
"""
        else:
            return f"""
<b>【卖出】{config.domestic_exchange}</b>
• <code>{contracts['domestic_call']}</code> 看涨
• <code>{contracts['domestic_put']}</code> 看跌{domestic_note}

<b>【买入】{config.foreign_exchange}</b>
• <code>{contracts['foreign_call']}</code> 看涨
• <code>{contracts['foreign_put']}</code> 看跌{foreign_note}

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
        """
        估算收益（粗略估算，仅供参考）
        
        警告：使用固定系数的简化估算，不能作为实际交易依据
        """
        config = inst_data.config

        # 简化Vega估算（固定系数，非精确值）
        vega_factors = {
            "copper": 800,
            "gold": 500,
            "silver": 600,
            "crude_oil": 700
        }

        vega = vega_factors.get(inst_data.instrument, 500)
        gross_profit = iv_diff * vega
        net_profit = gross_profit * 0.8  # 扣除成本
        
        logger.debug(
            f"[收益估算] {config.name} 使用固定系数: "
            f"IV差={iv_diff:.2f}%, 估算净收益={net_profit:.0f}元 "
            "(粗略估算，仅供参考)"
        )
        
        return net_profit


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
