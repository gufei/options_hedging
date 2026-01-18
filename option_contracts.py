"""
期权合约获取模块 - 从数据源动态获取真实的期权合约
"""

import logging
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptionContract:
    """期权合约信息"""
    call_symbol: str      # 看涨期权代码
    put_symbol: str       # 看跌期权代码
    strike_price: float   # 行权价
    call_price: float     # 看涨价格
    put_price: float      # 看跌价格
    atm_iv: Optional[float] = None  # 平值IV


class DomesticOptionContractFetcher:
    """国内期权合约获取器"""

    def __init__(self):
        self.ak = None
        self._init_akshare()

        # 品种名称映射
        self.instrument_name_map = {
            'copper': '沪铜期权',
            'gold': '黄金期权',
            'silver': '白银期权',
            'crude_oil': '原油期权'
        }

    def _init_akshare(self):
        """初始化akshare"""
        try:
            import akshare as ak
            self.ak = ak
            logger.info("akshare 初始化成功")
        except ImportError:
            logger.error("akshare 未安装")

    def get_available_months(self, instrument: str) -> List[str]:
        """
        获取某品种可用的期权月份合约

        Args:
            instrument: 品种代码 (copper/gold/silver/crude_oil)

        Returns:
            合约月份列表，如 ['cu2602', 'cu2603', 'cu2604']
        """
        if not self.ak:
            return []

        try:
            name = self.instrument_name_map.get(instrument)
            if not name:
                logger.error(f"不支持的品种: {instrument}")
                return []

            df = self.ak.option_commodity_contract_sina(symbol=name)
            if df.empty:
                return []

            # 返回合约列表（DataFrame有"序号"和"合约"两列）
            return df['合约'].tolist()

        except Exception as e:
            logger.error(f"获取{instrument}可用合约失败: {e}")
            return []

    def get_option_chain(
        self,
        instrument: str,
        month: str
    ) -> List[OptionContract]:
        """
        获取某月份的期权链

        Args:
            instrument: 品种代码
            month: 合约月份，如 '2603'

        Returns:
            期权合约列表
        """
        if not self.ak:
            return []

        try:
            name = self.instrument_name_map.get(instrument)
            if not name:
                return []

            # 获取期权链
            # 需要传入完整合约代码，如 'cu2603'
            symbol_prefix = {
                'copper': 'cu',
                'gold': 'au',
                'silver': 'ag',
                'crude_oil': 'sc'
            }.get(instrument, '')

            contract = f"{symbol_prefix}{month}"
            
            # 特殊处理：原油期权使用option_margin接口
            if instrument == 'crude_oil':
                return self._get_crude_oil_option_chain(contract)

            df = self.ak.option_commodity_contract_table_sina(
                symbol=name,
                contract=contract
            )

            if df.empty:
                return []

            # DataFrame列结构（从akshare返回）:
            # 0-6: 看涨合约信息, 7: 行权价, 8: 看涨期权代码, 9-16: 看跌合约信息, 16: 看跌期权代码
            contracts = []
            for idx, row in df.iterrows():
                try:
                    # 使用 iloc 按索引访问，但添加边界检查
                    if len(row) < 17:
                        logger.warning(f"第 {idx} 行数据不完整，跳过")
                        continue

                    contract = OptionContract(
                        call_symbol=row.iloc[8],   # 看涨期权代码
                        put_symbol=row.iloc[16],   # 看跌期权代码
                        strike_price=float(row.iloc[7]),  # 行权价
                        call_price=float(row.iloc[1] if not pd.isna(row.iloc[1]) else 0),  # 看涨最新价
                        put_price=float(row.iloc[10] if not pd.isna(row.iloc[10]) else 0)  # 看跌最新价
                    )
                    contracts.append(contract)
                except (ValueError, TypeError, IndexError) as e:
                    logger.debug(f"解析第 {idx} 行合约失败: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"解析第 {idx} 行时发生未预期的错误: {e}")
                    continue

            return contracts

        except Exception as e:
            logger.error(f"获取{instrument} {month}期权链失败: {e}")
            return []
    
    def _get_crude_oil_option_chain(self, contract: str) -> List[OptionContract]:
        """
        获取原油期权链（使用option_margin接口）
        
        Args:
            contract: 合约代码，如 'sc2603'
            
        Returns:
            期权合约列表
        """
        try:
            # 使用option_margin接口获取原油期权数据
            df = self.ak.option_margin(symbol="原油期权")
            
            if df.empty:
                logger.warning("原油期权数据为空")
                return []
            
            # 筛选指定月份的合约
            df_filtered = df[df['合约代码'].str.startswith(contract)]
            
            if df_filtered.empty:
                logger.warning(f"未找到 {contract} 月份的原油期权")
                return []
            
            contracts = []
            
            # 提取看涨和看跌期权
            # 合约代码格式: sc2603C440, sc2603P440
            calls = df_filtered[df_filtered['合约代码'].str.contains('C')]
            puts = df_filtered[df_filtered['合约代码'].str.contains('P')]
            
            # 按行权价分组
            strike_prices = set()
            for code in calls['合约代码']:
                # 从sc2603C440提取440
                strike = code.split('C')[1]
                strike_prices.add(int(strike))
            
            for strike in sorted(strike_prices):
                call_code = f"{contract}C{strike}"
                put_code = f"{contract}P{strike}"
                
                # 获取对应的数据
                call_data = calls[calls['合约代码'] == call_code]
                put_data = puts[puts['合约代码'] == put_code]
                
                if not call_data.empty and not put_data.empty:
                    call_price = float(call_data.iloc[0]['结算价'])
                    put_price = float(put_data.iloc[0]['结算价'])
                    
                    contract_obj = OptionContract(
                        call_symbol=call_code,
                        put_symbol=put_code,
                        strike_price=float(strike),
                        call_price=call_price,
                        put_price=put_price,
                        atm_iv=None  # option_margin接口不提供IV
                    )
                    contracts.append(contract_obj)
            
            logger.info(f"成功获取 {len(contracts)} 个原油期权合约（{contract}月份）")
            return contracts
            
        except Exception as e:
            logger.error(f"获取原油期权链失败: {e}")
            return []

    def get_atm_contract(
        self,
        instrument: str,
        underlying_price: float,
        month: Optional[str] = None
    ) -> Optional[OptionContract]:
        """
        获取平值期权合约

        Args:
            instrument: 品种代码
            underlying_price: 标的价格
            month: 指定月份，如不指定则选择下下月

        Returns:
            最接近平值的期权合约
        """
        # 如果没有指定月份，计算下下月
        if not month:
            now = datetime.now()
            target_month = now.month + 2
            target_year = now.year
            if target_month > 12:
                target_month -= 12
                target_year += 1
            year_short = target_year % 100
            month = f"{year_short:02d}{target_month:02d}"

        # 获取期权链
        contracts = self.get_option_chain(instrument, month)
        if not contracts:
            logger.warning(f"{instrument} {month} 无可用期权合约")
            return None

        # 找到最接近平值的合约
        min_diff = float('inf')
        atm_contract = None

        for contract in contracts:
            diff = abs(contract.strike_price - underlying_price)
            if diff < min_diff:
                min_diff = diff
                atm_contract = contract

        if atm_contract:
            logger.info(
                f"{instrument} 标的价格 {underlying_price}, "
                f"选择行权价 {atm_contract.strike_price}, "
                f"差值 {min_diff:.2f}"
            )

        return atm_contract
    
    def _generate_placeholder_contract(
        self,
        instrument: str,
        underlying_price: float,
        month: str
    ) -> OptionContract:
        """
        生成占位符合约（当真实数据不可用时）
        
        Args:
            instrument: 品种代码
            underlying_price: 标的价格
            month: 月份代码
            
        Returns:
            占位符期权合约
        """
        # 品种前缀映射
        symbol_prefix = {
            'copper': 'cu',
            'gold': 'au',
            'silver': 'ag',
            'crude_oil': 'sc'
        }.get(instrument, 'xx')
        
        # 根据价格确定合理的行权价（取整到合适的档位）
        if instrument == 'crude_oil':
            # 原油：按5元档位取整
            strike = round(underlying_price / 5) * 5
        elif instrument == 'copper':
            # 铜：按1000元档位取整
            strike = round(underlying_price / 1000) * 1000
        elif instrument == 'gold':
            # 黄金：按2元档位取整
            strike = round(underlying_price / 2) * 2
        elif instrument == 'silver':
            # 白银：按500元档位取整
            strike = round(underlying_price / 500) * 500
        else:
            strike = round(underlying_price)
        
        # 生成合约代码
        call_symbol = f"{symbol_prefix}{month}C{int(strike)}"
        put_symbol = f"{symbol_prefix}{month}P{int(strike)}"
        
        logger.info(
            f"{instrument} 生成占位符合约: "
            f"{call_symbol}/{put_symbol} "
            f"行权价 {strike} (数据不可用)"
        )
        
        return OptionContract(
            call_symbol=call_symbol,
            put_symbol=put_symbol,
            strike_price=strike,
            call_price=0.0,
            put_price=0.0,
            atm_iv=None
        )


class ForeignOptionContractFetcher:
    """境外期权合约获取器（CME）"""

    def __init__(self):
        self.yf = None
        self._init_yfinance()

        # CME月份代码
        self.month_codes = {
            1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
            7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
        }

    def _init_yfinance(self):
        """初始化yfinance"""
        try:
            import yfinance as yf
            self.yf = yf
            logger.info("yfinance 初始化成功")
        except ImportError:
            logger.error("yfinance 未安装")

    def get_option_chain(
        self,
        symbol: str,
        expiry_date: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        获取CME期权链

        Args:
            symbol: yfinance代码，如 'HG=F'
            expiry_date: 到期日，如不指定则使用最近的

        Returns:
            (calls DataFrame, puts DataFrame)
        """
        if not self.yf:
            return pd.DataFrame(), pd.DataFrame()

        try:
            ticker = self.yf.Ticker(symbol)
            expiry_dates = ticker.options

            if not expiry_dates:
                logger.warning(f"{symbol} 无可用期权")
                return pd.DataFrame(), pd.DataFrame()

            # 选择到期日
            target_date = expiry_date if expiry_date else expiry_dates[0]
            if target_date not in expiry_dates:
                target_date = expiry_dates[0]

            # 获取期权链
            opt_chain = ticker.option_chain(target_date)
            return opt_chain.calls, opt_chain.puts

        except Exception as e:
            logger.error(f"获取{symbol}期权链失败: {e}")
            return pd.DataFrame(), pd.DataFrame()

    def get_atm_contract(
        self,
        symbol: str,
        underlying_price: float,
        expiry_date: Optional[str] = None
    ) -> Optional[Dict]:
        """
        获取平值期权

        Returns:
            {'call_symbol': str, 'put_symbol': str, 'strike': float}
        """
        calls, puts = self.get_option_chain(symbol, expiry_date)

        if calls.empty or puts.empty:
            logger.warning(f"{symbol} 期权链为空")
            return None

        # 找最接近平值的行权价
        calls['strike_diff'] = abs(calls['strike'] - underlying_price)

        # 检查 calls 是否为空
        if calls.empty:
            logger.warning(f"{symbol} 看涨期权数据为空")
            return None

        atm_call = calls.loc[calls['strike_diff'].idxmin()]
        atm_strike = atm_call['strike']

        # 找对应的 put（优化：避免重复计算）
        matching_puts = puts[puts['strike'] == atm_strike]
        if matching_puts.empty:
            logger.warning(f"{symbol} 未找到行权价 {atm_strike} 的看跌期权")
            return None

        atm_put = matching_puts.iloc[0]

        return {
            'call_symbol': atm_call['contractSymbol'],
            'put_symbol': atm_put['contractSymbol'],
            'strike': atm_strike,
            'call_price': atm_call.get('lastPrice', 0),
            'put_price': atm_put.get('lastPrice', 0)
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # 测试国内期权
    print("=" * 60)
    print("测试国内期权合约获取")
    print("=" * 60)

    fetcher = DomesticOptionContractFetcher()

    # 获取铜期权可用月份
    months = fetcher.get_available_months('copper')
    print(f"\n沪铜可用合约月份: {months}")

    # 获取cu2603期权链
    if months:
        month = months[1] if len(months) > 1 else months[0]
        month_code = month[-4:]  # 提取2603
        print(f"\n获取 {month} 期权链...")
        contracts = fetcher.get_option_chain('copper', month_code)
        print(f"找到 {len(contracts)} 个行权价")

        if contracts:
            print("\n前5个行权价:")
            for i, c in enumerate(contracts[:5]):
                print(f"  {i+1}. 行权价 {c.strike_price}: {c.call_symbol} / {c.put_symbol}")

    # 获取平值合约
    print(f"\n根据标的价格 103390 获取平值合约...")
    atm = fetcher.get_atm_contract('copper', 103390)
    if atm:
        print(f"  行权价: {atm.strike_price}")
        print(f"  看涨: {atm.call_symbol}")
        print(f"  看跌: {atm.put_symbol}")
