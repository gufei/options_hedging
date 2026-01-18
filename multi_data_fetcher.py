"""
多品种数据获取模块
"""

import logging
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass

from instruments import InstrumentConfig, INSTRUMENTS, get_enabled_instruments

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """市场快照"""
    instrument: str                # 品种代码
    instrument_name: str           # 品种名称
    market: str                    # 'domestic' or 'foreign'
    exchange: str                  # 交易所
    symbol: str                    # 合约代码
    price: float                   # 价格
    unit: str                      # 单位
    atm_iv: float                  # 平值IV
    timestamp: datetime


@dataclass
class InstrumentData:
    """品种完整数据"""
    instrument: str                # 品种代码
    config: InstrumentConfig       # 品种配置
    domestic: Optional[MarketSnapshot]   # 国内数据
    foreign: Optional[MarketSnapshot]    # 境外数据
    iv_diff: Optional[float]       # IV差值
    timestamp: datetime


class MultiInstrumentFetcher:
    """多品种数据获取器"""

    def __init__(self):
        self.ak = None
        self.yf = None
        self._init_libraries()

    def _init_libraries(self):
        """初始化数据库"""
        try:
            import akshare as ak
            self.ak = ak
            logger.info("akshare 初始化成功")
        except ImportError:
            logger.warning("akshare 未安装")

        try:
            import yfinance as yf
            self.yf = yf
            logger.info("yfinance 初始化成功")
        except ImportError:
            logger.warning("yfinance 未安装")

    def fetch_domestic_data(self, instrument: str) -> Optional[MarketSnapshot]:
        """
        获取国内市场数据

        Args:
            instrument: 品种代码 (copper/gold/silver/crude_oil)
        """
        config = INSTRUMENTS.get(instrument)
        if not config:
            logger.error(f"未知品种: {instrument}")
            return None

        try:
            if self.ak:
                # 根据品种获取数据
                symbol_map = {
                    "copper": "CU0",
                    "gold": "AU0",
                    "silver": "AG0",
                    "crude_oil": "SC0"
                }

                sina_symbol = symbol_map.get(instrument)
                if sina_symbol:
                    df = self.ak.futures_main_sina(symbol=sina_symbol)
                    if not df.empty:
                        price = float(df.iloc[-1]['close'])

                        # 获取期权IV（简化处理，实际需要从期权数据计算）
                        # 这里使用模拟值，实际应从期权行情获取
                        iv = self._get_domestic_iv(instrument, price)

                        return MarketSnapshot(
                            instrument=instrument,
                            instrument_name=config.name,
                            market="domestic",
                            exchange=config.domestic_exchange,
                            symbol=config.domestic_symbol,
                            price=price,
                            unit=config.domestic_unit,
                            atm_iv=iv,
                            timestamp=datetime.now()
                        )

        except Exception as e:
            logger.error(f"获取{config.name}国内数据失败: {e}")

        # 返回模拟数据
        return self._get_domestic_fallback(instrument)

    def _get_domestic_iv(self, instrument: str, price: float) -> float:
        """获取国内期权IV（简化实现）"""
        # 实际应该从期权行情计算
        # 这里返回模拟值
        default_ivs = {
            "copper": 20.75,
            "gold": 15.5,
            "silver": 25.0,
            "crude_oil": 30.0
        }
        return default_ivs.get(instrument, 20.0)

    def _get_domestic_fallback(self, instrument: str) -> MarketSnapshot:
        """国内数据回退"""
        config = INSTRUMENTS.get(instrument)

        # 模拟价格
        fallback_prices = {
            "copper": 103390.0,
            "gold": 680.0,
            "silver": 8500.0,
            "crude_oil": 550.0
        }

        fallback_ivs = {
            "copper": 20.75,
            "gold": 15.5,
            "silver": 25.0,
            "crude_oil": 30.0
        }

        return MarketSnapshot(
            instrument=instrument,
            instrument_name=config.name,
            market="domestic",
            exchange=config.domestic_exchange,
            symbol=config.domestic_symbol,
            price=fallback_prices.get(instrument, 100.0),
            unit=config.domestic_unit,
            atm_iv=fallback_ivs.get(instrument, 20.0),
            timestamp=datetime.now()
        )

    def fetch_foreign_data(self, instrument: str) -> Optional[MarketSnapshot]:
        """
        获取境外市场数据

        Args:
            instrument: 品种代码
        """
        config = INSTRUMENTS.get(instrument)
        if not config:
            return None

        try:
            if self.yf:
                ticker = self.yf.Ticker(config.foreign_yf_symbol)
                hist = ticker.history(period="5d")

                if not hist.empty:
                    price = float(hist['Close'].iloc[-1])

                    # 尝试获取期权IV
                    iv = self._get_foreign_iv(ticker, price, instrument)

                    return MarketSnapshot(
                        instrument=instrument,
                        instrument_name=config.name,
                        market="foreign",
                        exchange=config.foreign_exchange,
                        symbol=config.foreign_symbol,
                        price=price,
                        unit=config.foreign_unit,
                        atm_iv=iv,
                        timestamp=datetime.now()
                    )

        except Exception as e:
            logger.error(f"获取{config.name}境外数据失败: {e}")

        return self._get_foreign_fallback(instrument)

    def _get_foreign_iv(self, ticker, price: float, instrument: str) -> float:
        """获取境外期权IV"""
        try:
            expiry_dates = ticker.options
            if expiry_dates:
                opt_chain = ticker.option_chain(expiry_dates[0])
                calls = opt_chain.calls

                if not calls.empty:
                    atm_idx = (calls['strike'] - price).abs().idxmin()
                    iv = calls.loc[atm_idx, 'impliedVolatility'] * 100
                    return iv
        except:
            pass

        # 返回默认值
        default_ivs = {
            "copper": 32.82,
            "gold": 18.5,
            "silver": 32.0,
            "crude_oil": 38.0
        }
        return default_ivs.get(instrument, 30.0)

    def _get_foreign_fallback(self, instrument: str) -> MarketSnapshot:
        """境外数据回退"""
        config = INSTRUMENTS.get(instrument)

        fallback_prices = {
            "copper": 4.70,
            "gold": 2950.0,
            "silver": 32.5,
            "crude_oil": 75.0
        }

        fallback_ivs = {
            "copper": 32.82,
            "gold": 18.5,
            "silver": 32.0,
            "crude_oil": 38.0
        }

        return MarketSnapshot(
            instrument=instrument,
            instrument_name=config.name,
            market="foreign",
            exchange=config.foreign_exchange,
            symbol=config.foreign_symbol,
            price=fallback_prices.get(instrument, 100.0),
            unit=config.foreign_unit,
            atm_iv=fallback_ivs.get(instrument, 30.0),
            timestamp=datetime.now()
        )

    def fetch_instrument(self, instrument: str) -> Optional[InstrumentData]:
        """
        获取单个品种的完整数据

        Args:
            instrument: 品种代码

        Returns:
            InstrumentData
        """
        config = INSTRUMENTS.get(instrument)
        if not config or not config.enabled:
            return None

        domestic = self.fetch_domestic_data(instrument)
        foreign = self.fetch_foreign_data(instrument)

        iv_diff = None
        if domestic and foreign:
            iv_diff = foreign.atm_iv - domestic.atm_iv

        return InstrumentData(
            instrument=instrument,
            config=config,
            domestic=domestic,
            foreign=foreign,
            iv_diff=iv_diff,
            timestamp=datetime.now()
        )

    def fetch_all_instruments(self) -> Dict[str, InstrumentData]:
        """
        获取所有启用品种的数据

        Returns:
            品种数据字典
        """
        results = {}

        for instrument in get_enabled_instruments():
            logger.info(f"获取 {INSTRUMENTS[instrument].name} 数据...")
            data = self.fetch_instrument(instrument)
            if data:
                results[instrument] = data
                logger.info(
                    f"  {data.config.name}: "
                    f"国内IV={data.domestic.atm_iv:.2f}% "
                    f"境外IV={data.foreign.atm_iv:.2f}% "
                    f"差值={data.iv_diff:+.2f}%"
                )

        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = MultiInstrumentFetcher()
    data = fetcher.fetch_all_instruments()

    print("\n" + "=" * 50)
    print("品种数据汇总")
    print("=" * 50)

    for instrument, inst_data in data.items():
        print(f"\n{inst_data.config.name}:")
        print(f"  国内: {inst_data.domestic.price:,.2f} {inst_data.domestic.unit}, IV={inst_data.domestic.atm_iv:.2f}%")
        print(f"  境外: {inst_data.foreign.price:,.2f} {inst_data.foreign.unit}, IV={inst_data.foreign.atm_iv:.2f}%")
        print(f"  IV差: {inst_data.iv_diff:+.2f}%")
