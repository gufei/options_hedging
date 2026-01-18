"""
多品种数据获取模块
"""

import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass

from instruments import (
    InstrumentConfig,
    INSTRUMENTS,
    get_enabled_instruments
)

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

    def __init__(self, enable_web_scraping=True):
        """
        初始化多品种数据获取器
        
        Args:
            enable_web_scraping: 是否启用网页爬取（默认True）
        """
        self.ak = None
        self.yf = None
        self.web_scraper = None
        self.enable_web_scraping = enable_web_scraping
        
        self._init_libraries()
        
        if enable_web_scraping:
            self._init_web_scraper()

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
    
    def _init_web_scraper(self):
        """初始化网页爬虫"""
        try:
            from cme_web_scraper import CMEWebScraper
            self.web_scraper = CMEWebScraper()
            logger.info("网页爬虫初始化成功")
        except ImportError:
            logger.warning("无法导入CME爬虫模块，将禁用网页爬取功能")
            self.enable_web_scraping = False
        except Exception as e:
            logger.warning(f"网页爬虫初始化失败: {e}")
            self.enable_web_scraping = False

    def fetch_domestic_data(
        self,
        instrument: str
    ) -> Optional[MarketSnapshot]:
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
                        # 注意：获取最新数据，确保是当前时间的价格
                        # akshare 返回的列名是中文，需要使用中文列名
                        price = float(df.iloc[-1]['收盘价'])

                        # 获取期权IV（从真实期权链数据计算）
                        iv = self._get_domestic_iv(instrument, price)
                        
                        # 如果无法获取真实IV，返回None
                        if iv is None:
                            logger.error(f"{config.name} 无法获取真实国内期权IV数据")
                            return None

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
                    else:
                        msg = f"{config.name} 国内期货数据为空"
                        logger.warning(msg)

        except Exception as e:
            logger.error(
                f"获取{config.name}国内数据失败: {e}",
                exc_info=True
            )

        # 无法获取真实数据，返回None
        logger.error(f"{config.name} 国内数据获取失败，无真实数据可用")
        return None

    def _get_domestic_iv(
        self,
        instrument: str,
        price: float
    ) -> Optional[float]:
        """
        获取国内期权IV (使用option_vol_shfe接口获取真实IV)

        Args:
            instrument: 品种代码
            price: 标的价格

        Returns:
            平值期权IV (百分比)
        """
        if not self.ak:
            return self._get_default_domestic_iv(instrument)

        try:
            # 品种名称映射
            name_map = {
                'copper': '铜期权',
                'gold': '黄金期权',
                'silver': '白银期权',
                'crude_oil': '原油期权'
            }

            option_name = name_map.get(instrument)
            if not option_name:
                logger.warning(f"不支持的品种: {instrument}")
                return self._get_default_domestic_iv(instrument)

            # 符号前缀
            symbol_map = {
                'copper': 'cu',
                'gold': 'au',
                'silver': 'ag',
                'crude_oil': 'sc'
            }
            symbol_prefix = symbol_map.get(instrument, '')

            # 使用option_vol_shfe获取隐含波动率参考值
            try:
                from datetime import datetime, timedelta
                
                # 尝试最近几天的交易日（最多回溯7天）
                df_vol = None
                for days_back in range(0, 8):
                    try_date = (
                        datetime.now() - timedelta(days=days_back)
                    ).strftime("%Y%m%d")
                    
                    try:
                        df_temp = self.ak.option_vol_shfe(
                            symbol=option_name,
                            trade_date=try_date
                        )
                        
                        if df_temp is None or df_temp.empty:
                            continue
                        
                        # 检查是否有有效的IV数据（不是空字符串）
                        # 查找IV列
                        iv_col_found = None
                        for col in df_temp.columns:
                            if '隐含波动率' in str(col):
                                iv_col_found = col
                                break
                        
                        if not iv_col_found:
                            continue
                        
                        # 检查是否有非空的IV值
                        valid_iv = df_temp[
                            (df_temp[iv_col_found].notna()) &
                            (df_temp[iv_col_found].astype(str) != '') &
                            (df_temp[iv_col_found].astype(str) != '0')
                        ]
                        
                        if not valid_iv.empty:
                            df_vol = df_temp
                            if days_back > 0:
                                logger.info(
                                    f"{instrument} 使用 {try_date} 的IV数据"
                                    f"（向前回溯{days_back}天）"
                                )
                            break
                            
                    except Exception:
                        continue
                
                if df_vol is None:
                    df_vol = pd.DataFrame()  # 确保df_vol不是None

                if df_vol is None or df_vol.empty:
                    logger.warning(f"{instrument} option_vol_shfe返回数据为空")
                    # 降级：尝试使用旧方法估算
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )

                # 查找隐含波动率字段
                iv_col = None
                for col in df_vol.columns:
                    if '隐含波动率' in str(col) or 'iv' in str(col).lower():
                        iv_col = col
                        break

                if not iv_col:
                    logger.warning(
                        f"{instrument} option_vol_shfe数据中未找到隐含波动率字段"
                    )
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )

                # 筛选出相关合约（排除小计行）
                df_filtered = df_vol[
                    df_vol['合约系列'].str.contains(symbol_prefix, na=False)
                ].copy()
                
                logger.debug(
                    f"{instrument} 筛选后有 {len(df_filtered)} 个合约"
                )
                
                if df_filtered.empty:
                    logger.warning(
                        f"{instrument} 未找到包含'{symbol_prefix}'的合约系列"
                    )
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )
                
                # 过滤掉IV为空或无效的行
                # 注意：IV列的数据类型可能是object，需要安全处理
                mask = df_filtered[iv_col].notna()
                mask = mask & (df_filtered[iv_col].astype(str) != '')
                mask = mask & (df_filtered[iv_col].astype(str) != '0')
                
                df_filtered = df_filtered[mask]
                
                logger.debug(
                    f"{instrument} 过滤空IV后还剩 {len(df_filtered)} 个合约"
                )

                if df_filtered.empty:
                    logger.warning(f"{instrument} 过滤后无有效IV数据")
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )

                # 找到最活跃的合约（成交量最大的）
                if '成交量' in df_filtered.columns:
                    max_volume_idx = df_filtered['成交量'].idxmax()
                    most_active = df_filtered.loc[max_volume_idx]
                else:
                    # 如果没有成交量，取第一条
                    most_active = df_filtered.iloc[0]

                # 获取隐含波动率值（安全转换）
                try:
                    iv_value = float(most_active[iv_col])
                except (ValueError, TypeError):
                    logger.warning(
                        f"{instrument} 隐含波动率值无法转换: "
                        f"{most_active[iv_col]}"
                    )
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )
                
                # 转换为百分比
                iv_percent = iv_value * 100

                # 合理性检查
                if not (1 <= iv_percent <= 200):
                    logger.warning(
                        f"{instrument} IV值({iv_percent:.2f}%)超出合理范围"
                    )
                    return self._get_domestic_iv_fallback(
                        instrument,
                        price,
                        option_name,
                        symbol_prefix
                    )

                contract = most_active['合约系列']
                logger.info(
                    f"[真实IV] {instrument} 国内期权IV从SHFE获取: {iv_percent:.2f}% "
                    f"(合约: {contract})"
                )
                return iv_percent

            except Exception as e:
                msg = f"使用option_vol_shfe获取 {instrument} IV失败: {e}"
                logger.warning(msg)
                # 降级：使用旧方法
                return self._get_domestic_iv_fallback(
                    instrument,
                    price,
                    option_name,
                    symbol_prefix
                )

        except Exception as e:
            logger.error(f"获取 {instrument} 国内IV失败: {e}")
            return self._get_default_domestic_iv(instrument)
    
    def _get_domestic_iv_fallback(
        self,
        instrument: str,
        price: float,
        option_name: str,
        symbol_prefix: str
    ) -> Optional[float]:
        """
        降级方案：使用期权链数据估算IV
        
        Args:
            instrument: 品种代码
            price: 标的价格
            option_name: 期权名称
            symbol_prefix: 符号前缀
            
        Returns:
            估算的IV值（百分比）
        """
        try:
            # 获取可用合约月份
            df_contracts = self.ak.option_commodity_contract_sina(
                symbol=option_name
            )
            if df_contracts.empty:
                logger.warning(f"{instrument} 无可用期权合约")
                return self._get_default_domestic_iv(instrument)

            # 选择最近的合约（通常是第二个月份，跳过当月）
            contracts = df_contracts['合约'].tolist()
            if len(contracts) < 2:
                target_contract = contracts[0]
            else:
                target_contract = contracts[1]  # 使用下月合约

            # 提取月份代码 (如 'cu2603' -> '2603')
            month_code = target_contract[-4:]

            # 获取期权链数据
            contract_name = f"{symbol_prefix}{month_code}"
            df_chain = self.ak.option_commodity_contract_table_sina(
                symbol=option_name,
                contract=contract_name
            )

            if df_chain.empty:
                logger.warning(f"{instrument} 期权链数据为空")
                return self._get_default_domestic_iv(instrument)

            # 从期权链中估算IV
            iv = self._calculate_domestic_atm_iv(
                df_chain,
                price,
                instrument
            )

            return iv

        except Exception as e:
            logger.warning(f"降级方案失败 {instrument}: {e}")
            return self._get_default_domestic_iv(instrument)

    def _calculate_domestic_atm_iv(
        self,
        df_chain,
        underlying_price: float,
        instrument: str
    ) -> float:
        """
        从期权链计算平值IV

        Args:
            df_chain: 期权链DataFrame
            underlying_price: 标的价格
            instrument: 品种代码

        Returns:
            平值IV
        """
        try:
            # 找到最接近标的价格的行权价
            # 行权价在第7列 (iloc[7])
            strikes = []
            for idx, row in df_chain.iterrows():
                try:
                    strike = float(row.iloc[7])
                    strikes.append((idx, strike))
                except (ValueError, TypeError, IndexError):
                    continue

            if not strikes:
                logger.warning(f"{instrument} 无有效行权价")
                return self._get_default_domestic_iv(instrument)

            # 找最接近的行权价
            atm_idx, atm_strike = min(
                strikes,
                key=lambda x: abs(x[1] - underlying_price)
            )

            # 获取该行权价的看涨和看跌期权价格
            # 看涨最新价: iloc[1], 看跌最新价: iloc[10]
            try:
                row = df_chain.iloc[atm_idx]
                call_price = (
                    float(row.iloc[1])
                    if not pd.isna(row.iloc[1])
                    else 0
                )
                put_price = (
                    float(row.iloc[10])
                    if not pd.isna(row.iloc[10])
                    else 0
                )

                # 如果期权价格太低，可能没有成交
                if call_price < 0.01 and put_price < 0.01:
                    msg = f"【数据质量问题】{instrument} 行权价 {atm_strike} "
                    msg += "期权价格异常低，无法计算IV"
                    logger.error(msg)
                    return self._get_default_domestic_iv(instrument)

                # 警告：使用简化的IV估算公式
                # 注意：这不是精确的Black-Scholes模型反推，仅为粗略估算
                logger.warning(
                    f"【估算值警告】{instrument} 使用简化公式估算IV，"
                    "非精确隐含波动率"
                )
                
                if call_price > 0 and put_price > 0:
                    avg_option_price = (call_price + put_price) / 2
                else:
                    avg_option_price = max(call_price, put_price)

                if avg_option_price > 0:
                    # 简化IV估算公式 (粗略估算，非精确值)
                    iv_estimate = (
                        (avg_option_price / underlying_price) *
                        100 * 3.5
                    )

                    # 合理性检查: IV应该在5%-100%之间
                    if 5 <= iv_estimate <= 100:
                        logger.info(
                            f"[估算] {instrument} 国内IV估算值: {iv_estimate:.2f}% "
                            "(基于期权价格的粗略估算)"
                        )
                        return iv_estimate
                    else:
                        msg = f"【估算失败】{instrument} 计算的IV "
                        msg += f"({iv_estimate:.2f}%) 超出合理范围"
                        logger.error(msg)
                        return self._get_default_domestic_iv(instrument)

            except (ValueError, TypeError, IndexError) as e:
                msg = f"{instrument} 解析行权价 "
                msg += f"{atm_strike} 数据失败: {e}"
                logger.warning(msg)

        except Exception as e:
            msg = f"计算 {instrument} 国内ATM IV失败: {e}"
            logger.error(msg)

        return self._get_default_domestic_iv(instrument)

    def _calculate_domestic_historical_volatility(
        self,
        instrument: str,
        window: int = 30
    ) -> Optional[float]:
        """
        计算国内期货的历史波动率
        
        Args:
            instrument: 品种代码
            window: 计算窗口（天数）
            
        Returns:
            年化历史波动率（百分比）
        """
        if not self.ak:
            return None
            
        try:
            symbol_map = {
                "copper": "CU0",
                "gold": "AU0",
                "silver": "AG0",
                "crude_oil": "SC0"
            }
            
            sina_symbol = symbol_map.get(instrument)
            if not sina_symbol:
                return None
            
            # 获取历史数据
            df = self.ak.futures_main_sina(symbol=sina_symbol)
            
            if df.empty or len(df) < window:
                logger.warning(
                    f"{instrument} 国内历史数据不足，"
                    f"需要{window}天，实际{len(df)}天"
                )
                return None
            
            # 计算日收益率
            returns = df['收盘价'].pct_change().dropna()
            
            if len(returns) < window - 1:
                return None
            
            # 取最近window天的数据
            recent_returns = returns.tail(window)
            
            # 计算标准差并年化
            daily_vol = recent_returns.std()
            annual_vol = daily_vol * (252 ** 0.5) * 100  # 转换为百分比
            
            # 合理性检查
            if 1 <= annual_vol <= 200:
                config = INSTRUMENTS.get(instrument)
                name = config.name if config else instrument
                logger.info(
                    f"[HV] {name} 计算得到{window}天国内历史波动率: "
                    f"{annual_vol:.2f}% (注意：HV不等于IV)"
                )
                return annual_vol
            else:
                logger.warning(
                    f"{instrument} 国内历史波动率({annual_vol:.2f}%)超出合理范围"
                )
                return None
                
        except Exception as e:
            logger.error(f"计算{instrument}国内历史波动率失败: {e}")
            return None
    
    def _get_crude_oil_domestic_iv(self, underlying_price: float) -> Optional[float]:
        """
        获取原油期权IV（使用option_margin接口）
        
        Args:
            underlying_price: 标的价格
            
        Returns:
            平值期权IV（通过期权价格估算）
        """
        try:
            # 使用option_margin接口获取原油期权数据
            df = self.ak.option_margin(symbol="原油期权")
            
            if df.empty:
                logger.warning("原油期权数据为空")
                return self._get_default_domestic_iv('crude_oil')
            
            # 计算下下月合约
            now = datetime.now()
            target_month = now.month + 2
            target_year = now.year
            if target_month > 12:
                target_month -= 12
                target_year += 1
            year_short = target_year % 100
            month_str = f"{year_short:02d}{target_month:02d}"
            contract = f"sc{month_str}"
            
            # 筛选指定月份的合约
            df_filtered = df[df['合约代码'].str.startswith(contract)]
            
            if df_filtered.empty:
                logger.warning(f"未找到 {contract} 月份的原油期权")
                return self._get_default_domestic_iv('crude_oil')
            
            # 找到最接近ATM的期权
            calls = df_filtered[df_filtered['合约代码'].str.contains('C')]
            puts = df_filtered[df_filtered['合约代码'].str.contains('P')]
            
            if calls.empty or puts.empty:
                logger.warning("原油期权看涨或看跌数据为空")
                return self._get_default_domestic_iv('crude_oil')
            
            # 提取行权价
            strike_prices = []
            for code in calls['合约代码']:
                strike = int(code.split('C')[1])
                strike_prices.append(strike)
            
            # 找到最接近标的价格的行权价
            atm_strike = min(strike_prices, key=lambda x: abs(x - underlying_price))
            
            # 获取ATM期权的价格
            call_code = f"{contract}C{atm_strike}"
            put_code = f"{contract}P{atm_strike}"
            
            call_data = calls[calls['合约代码'] == call_code]
            put_data = puts[puts['合约代码'] == put_code]
            
            if call_data.empty or put_data.empty:
                logger.warning(f"未找到行权价 {atm_strike} 的期权数据")
                return self._get_default_domestic_iv('crude_oil')
            
            call_price = float(call_data.iloc[0]['结算价'])
            put_price = float(put_data.iloc[0]['结算价'])
            
            # 警告：使用简化的IV估算
            logger.warning(
                "【估算值警告】原油期权使用简化公式估算IV，"
                "非精确隐含波动率"
            )
            
            # 简化的IV估算：使用期权价格占标的价格的比例
            if call_price > 0 and put_price > 0:
                avg_option_price = (call_price + put_price) / 2
                # 简化IV估算公式 (粗略估算，非精确值)
                iv_estimate = (avg_option_price / underlying_price) * 100 * 3.5
                
                # 合理性检查: IV应该在5%-100%之间
                if 5 <= iv_estimate <= 100:
                    logger.info(
                        f"[估算] crude_oil 国内期权IV估算值: "
                        f"{iv_estimate:.2f}% (ATM行权价: {atm_strike}) "
                        "(基于期权价格的粗略估算)"
                    )
                    return iv_estimate
                else:
                    logger.error(
                        f"【估算失败】原油期权计算的IV ({iv_estimate:.2f}%) 超出合理范围"
                    )
                    return self._get_default_domestic_iv('crude_oil')
            else:
                logger.error("【数据质量问题】原油期权价格数据异常")
                return self._get_default_domestic_iv('crude_oil')
                
        except Exception as e:
            logger.error(f"获取原油期权IV失败: {e}")
            return self._get_default_domestic_iv('crude_oil')
    
    def _get_default_domestic_iv(self, instrument: str) -> Optional[float]:
        """无法获取真实期权数据时，尝试历史波动率（降级策略）"""
        config = INSTRUMENTS.get(instrument, None)
        name = config.name if config else instrument
        
        logger.warning(
            f"【降级警告】{name} 国内期权IV无法获取，"
            "尝试使用历史波动率（HV≠IV）"
        )
        
        # 尝试计算历史波动率
        hv = self._calculate_domestic_historical_volatility(instrument, window=30)
        
        if hv is not None:
            logger.warning(
                f"【使用历史波动率】{name} 使用HV={hv:.2f}%代替IV，"
                "请注意这不是真实的隐含波动率"
            )
            return hv
        
        msg = f"【数据完全缺失】{name} 国内期权IV和历史波动率都无法获取"
        logger.error(msg)
        return None

    def fetch_foreign_data(
        self,
        instrument: str
    ) -> Optional[MarketSnapshot]:
        """
        获取境外市场数据 (改进版,支持多种ticker符号)

        Args:
            instrument: 品种代码
        """
        config = INSTRUMENTS.get(instrument)
        if not config:
            return None

        try:
            if self.yf:
                # 某些品种可能有多个可用的ticker符号
                ticker_symbols = self._get_ticker_symbols(
                    instrument,
                    config
                )

                for ticker_symbol in ticker_symbols:
                    try:
                        msg = f"尝试获取 {instrument} 数据，"
                        msg += f"使用ticker: {ticker_symbol}"
                        logger.debug(msg)

                        ticker = self.yf.Ticker(ticker_symbol)
                        hist = ticker.history(period="5d")

                        if hist.empty:
                            msg = f"{ticker_symbol} 历史数据为空"
                            logger.debug(msg)
                            continue

                        price = float(hist['Close'].iloc[-1])

                        # 价格合理性检查
                        if price <= 0:
                            msg = f"{ticker_symbol} 价格异常: {price}"
                            logger.warning(msg)
                            continue

                        # 尝试获取期权IV
                        iv = self._get_foreign_iv(
                            ticker,
                            price,
                            instrument
                        )
                        
                        # 如果无法获取真实期权IV，尝试使用历史波动率
                        if iv is None:
                            logger.warning(
                                f"{ticker_symbol} 无法获取期权IV，"
                                f"尝试使用历史波动率"
                            )
                            iv = self._calculate_historical_volatility(
                                ticker,
                                instrument,
                                window=30
                            )
                        
                        # 如果仍然无法获取，尝试下一个ticker
                        if iv is None:
                            logger.warning(
                                f"{ticker_symbol} 历史波动率也无法计算，"
                                f"尝试下一个ticker"
                            )
                            continue

                        msg = f"[OK] {instrument} 境外数据获取成功 "
                        msg += f"(ticker: {ticker_symbol})"
                        logger.info(msg)

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
                        msg = f"使用ticker {ticker_symbol} 获取 "
                        msg += f"{instrument} 数据失败: {e}"
                        logger.debug(msg)
                        continue

                msg = f"{instrument} 所有ticker符号都无法获取真实数据"
                logger.error(msg)

        except Exception as e:
            logger.error(f"获取{config.name}境外数据失败: {e}")

        # 无法获取真实数据，返回None
        logger.error(f"{config.name} 境外数据获取失败，无真实数据可用")
        return None

    def _get_ticker_symbols(self, instrument: str, config) -> list:
        """
        获取可用的ticker符号列表 (某些品种有多个可选符号)

        Args:
            instrument: 品种代码
            config: 品种配置

        Returns:
            ticker符号列表
        """
        # 主要ticker符号
        primary_symbol = config.foreign_yf_symbol

        # 备用ticker符号
        alternative_symbols = {
            'crude_oil': ['CL=F', 'BZ=F'],  # WTI原油, 布伦特原油
            'copper': ['HG=F', 'CPER'],     # CME铜, 铜ETF
            'gold': ['GC=F', 'GLD'],        # CME黄金, 黄金ETF
            'silver': ['SI=F', 'SLV'],      # CME白银, 白银ETF
        }

        # 构建符号列表 (主要符号在前)
        symbols = [primary_symbol]

        # 添加备用符号
        if instrument in alternative_symbols:
            for alt_symbol in alternative_symbols[instrument]:
                if alt_symbol != primary_symbol:
                    symbols.append(alt_symbol)

        return symbols

    def _get_foreign_iv(
        self,
        ticker,
        price: float,
        instrument: str
    ) -> Optional[float]:
        """
        获取境外期权IV (改进版,优先网页爬取,然后yfinance,最后历史波动率)

        Args:
            ticker: yfinance Ticker对象
            price: 标的价格
            instrument: 品种代码

        Returns:
            平值期权IV
        """
        # 方法1：尝试网页爬取（如果启用）
        if self.enable_web_scraping and self.web_scraper:
            try:
                logger.debug(f"{instrument} 尝试网页爬取获取期权IV")
                
                option_data = self.web_scraper.get_barchart_options(
                    instrument,
                    price
                )
                
                if option_data and option_data.get('iv'):
                    iv = option_data['iv']
                    
                    # 合理性检查
                    if 1 <= iv <= 200:
                        logger.info(
                            f"[Web] {instrument} 从网页获取期权IV: {iv:.2f}%"
                        )
                        return iv
                    else:
                        logger.warning(
                            f"{instrument} 网页IV({iv:.2f}%)超出合理范围"
                        )
            except Exception as e:
                logger.debug(f"{instrument} 网页爬取失败: {e}")
        
        # 方法2：尝试yfinance期权链
        max_retries = 2
        retry_count = 0

        while retry_count < max_retries:
            try:
                # 获取期权到期日
                expiry_dates = ticker.options

                if not expiry_dates:
                    logger.warning(f"{instrument} 无可用期权到期日")
                    break

                # 尝试多个到期日(有些品种第一个到期日可能数据不全)
                for expiry_idx in range(min(3, len(expiry_dates))):
                    try:
                        expiry = expiry_dates[expiry_idx]
                        opt_chain = ticker.option_chain(expiry)

                        calls = opt_chain.calls
                        puts = opt_chain.puts

                        # 确保数据不为空
                        if calls.empty and puts.empty:
                            msg = f"{instrument} 到期日 {expiry} "
                            msg += "期权链为空，尝试下一个"
                            logger.debug(msg)
                            continue

                        # 计算平值IV (同时考虑call和put)
                        iv_values = []

                        # 处理看涨期权
                        if not calls.empty:
                            # 过滤掉IV为0或NaN的数据
                            valid_calls = calls[
                                (calls['impliedVolatility'] > 0) &
                                (calls['impliedVolatility'].notna())
                            ]

                            if not valid_calls.empty:
                                strike_diff = (
                                    valid_calls['strike'] - price
                                ).abs()
                                atm_idx = strike_diff.idxmin()
                                call_iv = (
                                    valid_calls.loc[
                                        atm_idx,
                                        'impliedVolatility'
                                    ] * 100
                                )

                                # 合理性检查
                                if 1 <= call_iv <= 200:
                                    iv_values.append(call_iv)
                                    msg = f"{instrument} 看涨IV: "
                                    msg += f"{call_iv:.2f}%"
                                    logger.debug(msg)

                        # 处理看跌期权
                        if not puts.empty:
                            valid_puts = puts[
                                (puts['impliedVolatility'] > 0) &
                                (puts['impliedVolatility'].notna())
                            ]

                            if not valid_puts.empty:
                                strike_diff = (
                                    valid_puts['strike'] - price
                                ).abs()
                                atm_idx = strike_diff.idxmin()
                                put_iv = (
                                    valid_puts.loc[
                                        atm_idx,
                                        'impliedVolatility'
                                    ] * 100
                                )

                                if 1 <= put_iv <= 200:
                                    iv_values.append(put_iv)
                                    msg = f"{instrument} 看跌IV: "
                                    msg += f"{put_iv:.2f}%"
                                    logger.debug(msg)

                        # 如果找到了有效的IV值
                        if iv_values:
                            avg_iv = sum(iv_values) / len(iv_values)
                            msg = f"[OK] {instrument} 境外期权IV"
                            msg += f"从真实数据获取: {avg_iv:.2f}%"
                            logger.info(msg)
                            return avg_iv
                        else:
                            msg = f"{instrument} 到期日 {expiry} "
                            msg += "无有效IV数据"
                            logger.debug(msg)
                            continue

                    except Exception as e:
                        msg = f"{instrument} 处理到期日 "
                        msg += f"{expiry_idx} 失败: {e}"
                        logger.debug(msg)
                        continue

                # 如果所有到期日都失败，跳出重试循环
                break

            except Exception as e:
                retry_count += 1
                msg = f"{instrument} 境外IV获取失败 "
                msg += f"(尝试 {retry_count}/{max_retries}): {e}"
                logger.debug(msg)

                if retry_count < max_retries:
                    import time
                    time.sleep(1)  # 重试前等待1秒
                    continue

        # 所有尝试都失败，返回None
        return self._get_default_foreign_iv(instrument)

    def _calculate_historical_volatility(
        self,
        ticker,
        instrument: str,
        window: int = 30
    ) -> Optional[float]:
        """
        计算历史波动率作为IV的替代
        
        Args:
            ticker: yfinance Ticker对象
            instrument: 品种代码
            window: 计算窗口（天数）
            
        Returns:
            年化历史波动率（百分比）
        """
        try:
            # 获取历史价格数据
            hist = ticker.history(period=f"{window + 10}d")
            
            if hist.empty or len(hist) < window:
                logger.warning(
                    f"{instrument} 历史数据不足，"
                    f"需要{window}天，实际{len(hist)}天"
                )
                return None
            
            # 计算日收益率
            returns = hist['Close'].pct_change().dropna()
            
            if len(returns) < window - 1:
                return None
            
            # 取最近window天的数据
            recent_returns = returns.tail(window)
            
            # 计算标准差并年化
            daily_vol = recent_returns.std()
            annual_vol = daily_vol * (252 ** 0.5) * 100  # 转换为百分比
            
            # 合理性检查
            if 1 <= annual_vol <= 200:
                logger.info(
                    f"[HV] {instrument} 计算得到{window}天境外历史波动率: "
                    f"{annual_vol:.2f}% (注意：HV不等于IV)"
                )
                return annual_vol
            else:
                logger.warning(
                    f"{instrument} 历史波动率({annual_vol:.2f}%)超出合理范围"
                )
                return None
                
        except Exception as e:
            logger.error(f"计算{instrument}历史波动率失败: {e}")
            return None
    
    def _get_default_foreign_iv(self, instrument: str) -> Optional[float]:
        """无法获取真实期权数据时返回None，不使用任何估算"""
        config = INSTRUMENTS.get(instrument, None)
        name = config.name if config else instrument
        msg = f"【数据完全缺失】{name} 境外期权IV无法获取真实数据"
        logger.error(msg)
        return None

    def fetch_instrument(
        self,
        instrument: str
    ) -> Optional[InstrumentData]:
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
        if (domestic and foreign and 
            domestic.atm_iv is not None and 
            foreign.atm_iv is not None):
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
                
                # 处理可能的None值
                domestic_iv_str = (
                    f"{data.domestic.atm_iv:.2f}%" 
                    if data.domestic and data.domestic.atm_iv is not None 
                    else "N/A"
                )
                foreign_iv_str = (
                    f"{data.foreign.atm_iv:.2f}%" 
                    if data.foreign and data.foreign.atm_iv is not None 
                    else "N/A"
                )
                iv_diff_str = (
                    f"{data.iv_diff:+.2f}%" 
                    if data.iv_diff is not None 
                    else "N/A"
                )
                
                logger.info(
                    f"  {data.config.name}: "
                    f"国内IV={domestic_iv_str} "
                    f"境外IV={foreign_iv_str} "
                    f"差值={iv_diff_str}"
                )
            else:
                logger.warning(f"  {INSTRUMENTS[instrument].name}: 数据获取失败")

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
        domestic_line = (
            f"  国内: {inst_data.domestic.price:,.2f} "
            f"{inst_data.domestic.unit}, "
            f"IV={inst_data.domestic.atm_iv:.2f}%"
        )
        print(domestic_line)
        foreign_line = (
            f"  境外: {inst_data.foreign.price:,.2f} "
            f"{inst_data.foreign.unit}, "
            f"IV={inst_data.foreign.atm_iv:.2f}%"
        )
        print(foreign_line)
        print(f"  IV差: {inst_data.iv_diff:+.2f}%")
