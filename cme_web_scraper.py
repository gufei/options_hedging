"""
CME期权数据网页爬取模块
通过爬取公开网页获取CME期权链数据
"""

import logging
import time
import re
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CMEWebScraper:
    """CME期权数据网页爬取器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
        })
        
        # CME产品代码映射
        self.product_codes = {
            'copper': 'HG',  # CME铜
            'gold': 'GC',    # CME黄金
            'silver': 'SI',  # CME白银
            'crude_oil': 'CL' # CME原油
        }
        
        # CME月份代码
        self.month_codes = {
            1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
            7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
        }
    
    def _get_contract_symbol(self, instrument: str) -> Optional[str]:
        """
        获取期货合约代码
        
        Args:
            instrument: 品种代码
            
        Returns:
            合约代码，如 'HGH26'
        """
        symbol = self.product_codes.get(instrument)
        if not symbol:
            return None
        
        # 计算下下月合约
        now = datetime.now()
        month = now.month + 2
        year = now.year
        
        if month > 12:
            month -= 12
            year += 1
        
        year_short = year % 100
        month_code = self.month_codes.get(month, 'H')
        
        return f"{symbol}{month_code}{year_short:02d}"
    
    def get_barchart_options(
        self,
        instrument: str,
        underlying_price: float
    ) -> Optional[Dict]:
        """
        从Barchart获取期权数据（15分钟延迟）
        
        Args:
            instrument: 品种代码
            underlying_price: 标的价格
            
        Returns:
            期权数据字典: {
                'iv': float,  # 隐含波动率
                'call_symbol': str,  # 看涨期权代码
                'put_symbol': str,   # 看跌期权代码
                'strike': float      # 行权价
            }
        """
        try:
            contract = self._get_contract_symbol(instrument)
            if not contract:
                logger.error(f"不支持的品种: {instrument}")
                return None
            
            url = f"https://www.barchart.com/futures/quotes/{contract}/options"
            
            logger.info(f"尝试从Barchart获取 {contract} 期权数据...")
            
            # 添加延迟，避免被封
            time.sleep(1)
            
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 尝试多种解析方法
            option_data = self._parse_barchart_page(
                soup,
                underlying_price,
                instrument,
                contract
            )
            
            if option_data:
                logger.info(
                    f"[Barchart] {instrument} 期权IV获取成功: "
                    f"{option_data['iv']:.2f}%"
                )
                return option_data
            else:
                logger.warning(f"[Barchart] {instrument} 无法解析期权数据")
                return None
                
        except requests.exceptions.Timeout:
            logger.warning(f"Barchart请求超时")
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"Barchart网络请求失败: {e}")
            return None
        except Exception as e:
            logger.warning(f"Barchart数据解析失败: {e}")
            return None
    
    def _parse_barchart_page(
        self,
        soup: BeautifulSoup,
        underlying_price: float,
        instrument: str,
        contract: str
    ) -> Optional[Dict]:
        """
        解析Barchart期权页面
        
        尝试多种方法提取数据：
        1. 查找期权表格
        2. 查找JSON数据
        3. 查找特定class的元素
        """
        try:
            # 方法1：尝试从表格提取
            result = self._parse_from_table(soup, underlying_price, contract)
            if result:
                return result
            
            # 方法2：尝试从JSON数据提取（如果页面包含）
            result = self._parse_from_json(soup, underlying_price)
            if result:
                return result
            
            # 方法3：尝试从特定元素提取
            result = self._parse_from_elements(soup, underlying_price, contract)
            if result:
                return result
            
            logger.debug(f"所有解析方法都失败")
            return None
            
        except Exception as e:
            logger.error(f"解析Barchart页面失败: {e}", exc_info=True)
            return None
    
    def _parse_from_table(
        self,
        soup: BeautifulSoup,
        underlying_price: float,
        contract: str
    ) -> Optional[Dict]:
        """从HTML表格提取期权数据"""
        try:
            # 查找所有表格
            tables = soup.find_all('table')
            
            for table in tables:
                # 检查表头是否包含期权相关关键词
                headers_text = str(table.find_all('th')).lower()
                
                if not any(kw in headers_text for kw in ['strike', 'call', 'put', 'iv', 'implied']):
                    continue
                
                logger.debug(f"找到可能的期权表格")
                
                # 提取所有行
                rows = table.find_all('tr')
                
                options = []
                for row in rows[1:]:  # 跳过表头
                    cols = row.find_all('td')
                    if len(cols) < 3:
                        continue
                    
                    try:
                        # 尝试提取行权价和IV
                        row_data = [col.text.strip() for col in cols]
                        
                        # 查找行权价（通常是数字）
                        strike = None
                        iv = None
                        
                        for i, text in enumerate(row_data):
                            # 清理文本
                            clean_text = text.replace(',', '').replace('$', '').strip()
                            
                            # 尝试解析为浮点数
                            try:
                                value = float(clean_text)
                                
                                # 判断是行权价还是IV
                                if 0.01 <= value <= 200:  # 可能是IV（百分比）
                                    if iv is None and '%' not in text:
                                        iv = value
                                elif strike is None:  # 较大的数字可能是行权价
                                    strike = value
                            except ValueError:
                                continue
                        
                        if strike and iv:
                            options.append({
                                'strike': strike,
                                'iv': iv
                            })
                    
                    except Exception as e:
                        logger.debug(f"解析行失败: {e}")
                        continue
                
                if options:
                    # 找到最接近ATM的期权
                    atm = min(options, key=lambda x: abs(x['strike'] - underlying_price))
                    
                    return {
                        'iv': atm['iv'],
                        'strike': atm['strike'],
                        'call_symbol': f"{contract}C{atm['strike']:.0f}",
                        'put_symbol': f"{contract}P{atm['strike']:.0f}"
                    }
            
            return None
            
        except Exception as e:
            logger.debug(f"从表格解析失败: {e}")
            return None
    
    def _parse_from_json(
        self,
        soup: BeautifulSoup,
        underlying_price: float
    ) -> Optional[Dict]:
        """从页面中的JSON数据提取"""
        try:
            # 查找script标签中的JSON数据
            scripts = soup.find_all('script')
            
            for script in scripts:
                if not script.string:
                    continue
                
                # 查找包含期权数据的JSON
                if 'impliedVolatility' in script.string or 'optionChain' in script.string:
                    logger.debug("找到包含期权数据的script标签")
                    
                    # 尝试提取JSON
                    # 这里需要根据实际格式调整
                    import json
                    
                    # 简单示例：查找IV值
                    iv_match = re.search(r'"impliedVolatility["\s:]+(\d+\.?\d*)', script.string)
                    if iv_match:
                        iv = float(iv_match.group(1))
                        
                        return {
                            'iv': iv,
                            'strike': underlying_price,
                            'call_symbol': 'N/A',
                            'put_symbol': 'N/A'
                        }
            
            return None
            
        except Exception as e:
            logger.debug(f"从JSON解析失败: {e}")
            return None
    
    def _parse_from_elements(
        self,
        soup: BeautifulSoup,
        underlying_price: float,
        contract: str
    ) -> Optional[Dict]:
        """从特定HTML元素提取数据"""
        try:
            # 查找包含IV关键词的元素
            iv_elements = soup.find_all(text=re.compile(r'(implied|volatility)', re.I))
            
            for elem in iv_elements:
                parent = elem.parent
                if not parent:
                    continue
                
                # 在父元素附近查找数字
                text = parent.get_text()
                numbers = re.findall(r'\d+\.?\d*', text)
                
                for num in numbers:
                    try:
                        value = float(num)
                        if 1 <= value <= 200:  # 合理的IV范围
                            logger.debug(f"从元素中找到可能的IV: {value}%")
                            
                            return {
                                'iv': value,
                                'strike': underlying_price,
                                'call_symbol': f"{contract}C{underlying_price:.0f}",
                                'put_symbol': f"{contract}P{underlying_price:.0f}"
                            }
                    except ValueError:
                        continue
            
            return None
            
        except Exception as e:
            logger.debug(f"从元素解析失败: {e}")
            return None
    
    def get_option_iv_with_fallback(
        self,
        instrument: str,
        underlying_price: float,
        calculate_hv_func=None
    ) -> Tuple[Optional[float], str]:
        """
        获取期权IV，失败时降级到历史波动率
        
        Args:
            instrument: 品种代码
            underlying_price: 标的价格
            calculate_hv_func: 计算历史波动率的函数
            
        Returns:
            (iv值, 数据来源标记): (float, str)
            数据来源: 'web' 或 'hv' 或 None
        """
        # 尝试从网页获取真实IV
        option_data = self.get_barchart_options(instrument, underlying_price)
        
        if option_data and option_data.get('iv'):
            return option_data['iv'], 'web'
        
        # 如果网页获取失败，使用历史波动率
        if calculate_hv_func:
            logger.info(f"{instrument} 网页爬取失败，降级到历史波动率")
            hv = calculate_hv_func(instrument)
            if hv:
                return hv, 'hv'
        
        return None, None


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("CME期权数据爬虫测试")
    print("=" * 60)
    
    scraper = CMEWebScraper()
    
    # 测试不同品种
    test_cases = [
        ('copper', 4.15),
        ('gold', 2850.0),
        ('silver', 32.5),
        ('crude_oil', 75.0)
    ]
    
    for instrument, price in test_cases:
        print(f"\n测试 {instrument} (价格: {price}):")
        print("-" * 60)
        
        result = scraper.get_barchart_options(instrument, price)
        
        if result:
            print(f"✅ 成功获取数据:")
            print(f"   IV: {result['iv']:.2f}%")
            print(f"   行权价: {result['strike']}")
            print(f"   看涨: {result['call_symbol']}")
            print(f"   看跌: {result['put_symbol']}")
        else:
            print(f"❌ 数据获取失败")
        
        # 避免请求过快
        time.sleep(2)
