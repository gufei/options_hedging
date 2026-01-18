"""
数据获取模块 - 获取沪铜和CME铜期权数据
"""

import logging
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptionData:
    """期权数据结构"""
    symbol: str                    # 合约代码
    underlying_price: float        # 标的价格
    strike: float                  # 行权价
    expiry: str                    # 到期日
    option_type: str               # 'call' or 'put'
    bid: float                     # 买价
    ask: float                     # 卖价
    last: float                    # 最新价
    implied_volatility: float      # 隐含波动率
    delta: Optional[float] = None  # Delta
    volume: int = 0                # 成交量
    open_interest: int = 0         # 持仓量
    timestamp: Optional[datetime] = None


@dataclass
class MarketSnapshot:
    """市场快照"""
    market: str                    # 'SHFE' or 'CME'
    underlying_symbol: str         # 标的代码
    underlying_price: float        # 标的价格
    atm_call_iv: float            # 平值看涨期权IV
    atm_put_iv: float             # 平值看跌期权IV
    atm_iv: float                 # 平值IV (平均)
    options: List[OptionData]     # 期权链数据
    timestamp: datetime


class SHFEDataFetcher:
    """上期所沪铜期权数据获取"""

    def __init__(self):
        self.ak = None
        self._init_akshare()

    def _init_akshare(self):
        """初始化 akshare"""
        try:
            import akshare as ak
            self.ak = ak
            logger.info("akshare 初始化成功")
        except ImportError:
            logger.warning("akshare 未安装，将使用备用数据源")

    def get_copper_options(self, contract: str = None) -> Optional[MarketSnapshot]:
        """
        获取沪铜期权数据

        Args:
            contract: 合约月份，如 "2602"，为空则自动获取主力合约

        Returns:
            MarketSnapshot 或 None
        """
        if not self.ak:
            return self._get_fallback_data()

        try:
            # 获取铜期货价格
            futures_df = self.ak.futures_main_sina(symbol="CU0")
            if futures_df.empty:
                logger.warning("无法获取沪铜期货价格")
                return None

            underlying_price = float(futures_df.iloc[-1]['close'])

            # 获取期权行情
            # 注意：akshare 对于商品期权的接口较为有限
            # 这里使用备用方法直接从东方财富获取
            return self._get_from_eastmoney(underlying_price)

        except Exception as e:
            logger.error(f"获取沪铜期权数据失败: {e}")
            return self._get_fallback_data()

    def _get_from_eastmoney(self, underlying_price: float) -> Optional[MarketSnapshot]:
        """从东方财富获取数据（备用）"""
        import requests

        try:
            # 东方财富期权接口
            url = "https://push2.eastmoney.com/api/qt/optioncode/get"
            params = {
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "dession": "CU",
                "fields": "f1,f2,f3,f4,f5,f6,f7,f12,f13,f14,f152"
            }

            with requests.Session() as session:
                resp = session.get(url, params=params, timeout=10)
                data = resp.json()

                if data.get("data"):
                    # 解析数据...
                    logger.info("从东方财富获取数据成功")
                    # 此处需要根据实际API返回格式解析

            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"东方财富数据获取失败: {e}")
            return None
        except Exception as e:
            logger.error(f"东方财富数据解析失败: {e}")
            return None

    def _get_fallback_data(self) -> Optional[MarketSnapshot]:
        """无法获取真实数据时返回None，不使用模拟数据"""
        logger.error("【数据获取失败】无法获取沪铜真实数据，请检查数据源")
        return None

    def _parse_options_data(self, df, underlying_price: float) -> List[OptionData]:
        """
        解析期权数据

        注意：此方法当前未实现，返回空列表
        未来需要根据实际数据源的格式进行解析
        """
        # TODO: 根据实际数据格式解析
        logger.warning("_parse_options_data 方法未实现，返回空列表")
        return []

    def _find_atm_iv(self, options: List[OptionData], underlying_price: float):
        """找到平值期权的IV"""
        if not options:
            logger.error("【数据不可用】期权列表为空，无法获取真实IV")
            return None, None  # 返回None而不是默认值

        # 找到最接近标的价格的行权价
        atm_strike = min(
            set(opt.strike for opt in options),
            key=lambda x: abs(x - underlying_price)
        )

        atm_call_iv = None
        atm_put_iv = None

        for opt in options:
            if opt.strike == atm_strike:
                if opt.option_type == 'call':
                    atm_call_iv = opt.implied_volatility
                else:
                    atm_put_iv = opt.implied_volatility

        # 如果未找到，记录错误
        if atm_call_iv is None:
            logger.error(f"【数据不可用】未找到行权价 {atm_strike} 的看涨期权IV")
        if atm_put_iv is None:
            logger.error(f"【数据不可用】未找到行权价 {atm_strike} 的看跌期权IV")

        # 返回None而不是默认值，确保不使用估算数据
        return atm_call_iv, atm_put_iv


class CMEDataFetcher:
    """CME 铜期权数据获取"""

    def __init__(self):
        self.yf = None
        self._init_yfinance()

    def _init_yfinance(self):
        """初始化 yfinance"""
        try:
            import yfinance as yf
            self.yf = yf
            logger.info("yfinance 初始化成功")
        except ImportError:
            logger.warning("yfinance 未安装")

    def get_copper_options(self) -> Optional[MarketSnapshot]:
        """
        获取CME铜期权数据

        Returns:
            MarketSnapshot 或 None
        """
        if not self.yf:
            return self._get_fallback_data()

        try:
            # CME 铜期货 ETF 代理：CPER 或直接用 HG=F
            ticker = self.yf.Ticker("HG=F")

            # 获取期货价格
            hist = ticker.history(period="1d")
            if hist.empty:
                logger.warning("无法获取CME铜价格")
                return self._get_fallback_data()

            underlying_price = float(hist['Close'].iloc[-1])

            # 获取期权链
            options = []
            atm_call_iv = None  # 不使用默认估算值
            atm_put_iv = None

            try:
                # 尝试获取期权链
                expiry_dates = ticker.options
                if expiry_dates:
                    nearest_expiry = expiry_dates[0]
                    opt_chain = ticker.option_chain(nearest_expiry)

                    calls = opt_chain.calls
                    puts = opt_chain.puts

                    # 找平值期权
                    if not calls.empty:
                        atm_idx = (calls['strike'] - underlying_price).abs().idxmin()
                        atm_call_iv = calls.loc[atm_idx, 'impliedVolatility'] * 100

                    if not puts.empty:
                        atm_idx = (puts['strike'] - underlying_price).abs().idxmin()
                        atm_put_iv = puts.loc[atm_idx, 'impliedVolatility'] * 100

                    # 解析期权数据
                    options = self._parse_option_chain(calls, puts, underlying_price, nearest_expiry)

            except Exception as e:
                logger.error(f"【数据获取失败】获取CME期权链失败: {e}")

            # 检查是否获取到有效的IV数据
            if atm_call_iv is None or atm_put_iv is None:
                logger.error("【数据不可用】CME期权IV数据缺失，无法提供真实数据")
                return None
            
            return MarketSnapshot(
                market="CME",
                underlying_symbol="HG",
                underlying_price=underlying_price,
                atm_call_iv=atm_call_iv,
                atm_put_iv=atm_put_iv,
                atm_iv=(atm_call_iv + atm_put_iv) / 2,
                options=options,
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"获取CME铜期权数据失败: {e}")
            return self._get_fallback_data()

    def _parse_option_chain(self, calls, puts, underlying_price, expiry) -> List[OptionData]:
        """解析期权链数据"""
        options = []

        for _, row in calls.iterrows():
            options.append(OptionData(
                symbol=row.get('contractSymbol', ''),
                underlying_price=underlying_price,
                strike=row['strike'],
                expiry=expiry,
                option_type='call',
                bid=row.get('bid', 0),
                ask=row.get('ask', 0),
                last=row.get('lastPrice', 0),
                implied_volatility=row.get('impliedVolatility', 0) * 100,
                delta=None,
                volume=int(row.get('volume') or 0),
                open_interest=int(row.get('openInterest') or 0)
            ))

        for _, row in puts.iterrows():
            options.append(OptionData(
                symbol=row.get('contractSymbol', ''),
                underlying_price=underlying_price,
                strike=row['strike'],
                expiry=expiry,
                option_type='put',
                bid=row.get('bid', 0),
                ask=row.get('ask', 0),
                last=row.get('lastPrice', 0),
                implied_volatility=row.get('impliedVolatility', 0) * 100,
                delta=None,
                volume=int(row.get('volume') or 0),
                open_interest=int(row.get('openInterest') or 0)
            ))

        return options

    def _get_fallback_data(self) -> Optional[MarketSnapshot]:
        """无法获取真实数据时返回None，不使用模拟数据"""
        logger.error("【数据获取失败】无法获取CME真实数据，请检查数据源")
        return None


class DataFetcherManager:
    """数据获取管理器"""

    def __init__(self):
        self.shfe_fetcher = SHFEDataFetcher()
        self.cme_fetcher = CMEDataFetcher()

    def get_all_data(self) -> Dict[str, Optional[MarketSnapshot]]:
        """获取所有市场数据"""
        return {
            "SHFE": self.shfe_fetcher.get_copper_options(),
            "CME": self.cme_fetcher.get_copper_options()
        }


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)

    manager = DataFetcherManager()
    data = manager.get_all_data()

    for market, snapshot in data.items():
        if snapshot:
            print(f"\n{market}:")
            print(f"  标的价格: {snapshot.underlying_price}")
            print(f"  平值IV: {snapshot.atm_iv:.2f}%")
