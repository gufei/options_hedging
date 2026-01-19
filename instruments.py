"""
品种配置模块 - 从 config.py 读取品种配置
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from config import INSTRUMENTS_CONFIG


@dataclass
class InstrumentConfig:
    """品种配置"""
    key: str                     # 品种key
    name: str                    # 品种名称（中文）
    name_en: str                 # 品种名称（英文）

    # 国内市场
    domestic_exchange: str
    domestic_symbol: str
    domestic_unit: str
    domestic_lot_size: float     # 每手数量
    domestic_base_unit: str      # 基础单位

    # 境外市场
    foreign_exchange: str
    foreign_symbol: str
    foreign_yf_symbol: str
    foreign_unit: str
    foreign_lot_size: float      # 每手数量
    foreign_base_unit: str       # 基础单位

    # 套利参数
    iv_open_threshold: float     # 开仓阈值
    iv_close_threshold: float    # 平仓阈值
    iv_stop_loss: float          # 止损阈值
    min_iv_diff: float           # 最小IV差

    # 是否启用
    enabled: bool = True


def _load_instruments() -> Dict[str, InstrumentConfig]:
    """从配置加载品种"""
    instruments = {}

    for key, cfg in INSTRUMENTS_CONFIG.items():
        instruments[key] = InstrumentConfig(
            key=key,
            name=cfg.get("name", key),
            name_en=cfg.get("name_en", key),
            domestic_exchange=cfg.get("domestic_exchange", ""),
            domestic_symbol=cfg.get("domestic_symbol", ""),
            domestic_unit=cfg.get("domestic_unit", ""),
            domestic_lot_size=cfg.get("domestic_lot_size", 1.0),
            domestic_base_unit=cfg.get("domestic_base_unit", ""),
            foreign_exchange=cfg.get("foreign_exchange", ""),
            foreign_symbol=cfg.get("foreign_symbol", ""),
            foreign_yf_symbol=cfg.get("foreign_yf_symbol", ""),
            foreign_unit=cfg.get("foreign_unit", ""),
            foreign_lot_size=cfg.get("foreign_lot_size", 1.0),
            foreign_base_unit=cfg.get("foreign_base_unit", ""),
            iv_open_threshold=cfg.get("iv_open_threshold", 8.0),
            iv_close_threshold=cfg.get("iv_close_threshold", 5.0),
            iv_stop_loss=cfg.get("iv_stop_loss", 18.0),
            min_iv_diff=cfg.get("min_iv_diff", 3.0),
            enabled=cfg.get("enabled", True)
        )

    return instruments


# 加载品种配置
INSTRUMENTS: Dict[str, InstrumentConfig] = _load_instruments()


def get_enabled_instruments() -> List[str]:
    """获取启用的品种列表"""
    return [k for k, v in INSTRUMENTS.items() if v.enabled]


def get_instrument(name: str) -> Optional[InstrumentConfig]:
    """获取品种配置"""
    return INSTRUMENTS.get(name)


def get_all_instruments() -> Dict[str, InstrumentConfig]:
    """获取所有品种配置"""
    return INSTRUMENTS


# 月份代码映射（CME）
CME_MONTH_CODES = {
    1: 'F', 2: 'G', 3: 'H', 4: 'J', 5: 'K', 6: 'M',
    7: 'N', 8: 'Q', 9: 'U', 10: 'V', 11: 'X', 12: 'Z'
}


if __name__ == "__main__":
    # 显示所有品种配置
    print("=" * 60)
    print("可监控品种列表（配置来自 config.py）")
    print("=" * 60)

    for key, config in INSTRUMENTS.items():
        status = "[ON]" if config.enabled else "[OFF]"
        print(f"\n{status} {config.name} ({config.name_en})")
        print(f"    国内: {config.domestic_exchange} {config.domestic_symbol} ({config.domestic_unit})")
        print(f"    境外: {config.foreign_exchange} {config.foreign_symbol} ({config.foreign_unit})")
        print(f"    开仓阈值: {config.iv_open_threshold}%")
        print(f"    平仓阈值: {config.iv_close_threshold}%")
        print(f"    止损阈值: {config.iv_stop_loss}%")
