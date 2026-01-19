"""
合约手数计算模块

根据国内合约数量，计算对应的境外合约数量
考虑不同的计量单位和合约规格
"""

import logging
from typing import Tuple, Dict
from dataclasses import dataclass

from instruments import InstrumentConfig

logger = logging.getLogger(__name__)


# 单位转换系数
UNIT_CONVERSIONS = {
    # 重量单位
    ("吨", "磅"): 2204.62,          # 1吨 = 2204.62磅
    ("磅", "吨"): 1 / 2204.62,
    ("千克", "盎司"): 32.1507,      # 1千克 = 32.1507金衡盎司
    ("盎司", "千克"): 1 / 32.1507,
    ("克", "盎司"): 0.0321507,      # 1克 = 0.0321507金衡盎司
    ("盎司", "克"): 31.1035,
    
    # 体积单位（原油使用桶）
    ("桶", "桶"): 1.0,              # 原油两边都用桶
}


@dataclass
class LotCalculation:
    """手数计算结果"""
    domestic_lots: int              # 国内手数
    foreign_lots: int               # 境外手数
    domestic_total_units: float     # 国内总单位
    foreign_total_units: float      # 境外总单位
    domestic_base_unit: str         # 国内基础单位
    foreign_base_unit: str          # 境外基础单位
    conversion_ratio: float         # 转换比率
    hedge_ratio: float              # 对冲比例（%）
    explanation: str                # 计算说明


def get_conversion_factor(from_unit: str, to_unit: str) -> float:
    """
    获取单位转换系数
    
    Args:
        from_unit: 源单位
        to_unit: 目标单位
        
    Returns:
        转换系数
    """
    if from_unit == to_unit:
        return 1.0
    
    key = (from_unit, to_unit)
    if key in UNIT_CONVERSIONS:
        return UNIT_CONVERSIONS[key]
    
    # 如果找不到直接转换，尝试反向查找
    reverse_key = (to_unit, from_unit)
    if reverse_key in UNIT_CONVERSIONS:
        return 1.0 / UNIT_CONVERSIONS[reverse_key]
    
    raise ValueError(f"不支持的单位转换: {from_unit} -> {to_unit}")


def calculate_lots(
    config: InstrumentConfig,
    domestic_lots: int = 1,
    round_up: bool = True
) -> LotCalculation:
    """
    计算套利所需的手数
    
    Args:
        config: 品种配置
        domestic_lots: 国内购买手数（默认1手）
        round_up: 是否向上取整（True=向上取整，避免对冲不足；False=向下取整）
        
    Returns:
        LotCalculation 对象，包含计算结果和说明
    """
    # 计算国内总单位
    domestic_total_units = domestic_lots * config.domestic_lot_size
    
    # 获取单位转换系数
    conversion_factor = get_conversion_factor(
        config.domestic_base_unit,
        config.foreign_base_unit
    )
    
    # 转换到境外单位
    foreign_total_units = domestic_total_units * conversion_factor
    
    # 计算境外需要的手数
    foreign_lots_exact = foreign_total_units / config.foreign_lot_size
    
    # 根据参数决定取整方式
    import math
    if round_up:
        foreign_lots = math.ceil(foreign_lots_exact)
    else:
        foreign_lots = math.floor(foreign_lots_exact)
    
    # 避免境外手数为0
    if foreign_lots == 0:
        foreign_lots = 1
    
    # 实际境外总单位
    foreign_actual_units = foreign_lots * config.foreign_lot_size
    
    # 计算对冲比例
    domestic_in_foreign = domestic_total_units * conversion_factor
    hedge_ratio = (foreign_actual_units / domestic_in_foreign) * 100 if domestic_in_foreign > 0 else 0
    
    # 生成说明
    explanation = _generate_explanation(
        config,
        domestic_lots,
        domestic_total_units,
        foreign_lots,
        foreign_lots_exact,
        foreign_total_units,
        foreign_actual_units,
        conversion_factor
    )
    
    return LotCalculation(
        domestic_lots=domestic_lots,
        foreign_lots=foreign_lots,
        domestic_total_units=domestic_total_units,
        foreign_total_units=foreign_actual_units,
        domestic_base_unit=config.domestic_base_unit,
        foreign_base_unit=config.foreign_base_unit,
        conversion_ratio=foreign_lots / domestic_lots,
        hedge_ratio=hedge_ratio,
        explanation=explanation
    )


def calculate_optimal_lots(
    config: InstrumentConfig,
    max_foreign_lots: int = 10
) -> LotCalculation:
    """
    计算最优的套利手数组合（接近1:1对冲比例）
    
    Args:
        config: 品种配置
        max_foreign_lots: 最大境外手数限制
        
    Returns:
        LotCalculation 对象
    """
    # 获取单位转换系数
    conversion_factor = get_conversion_factor(
        config.domestic_base_unit,
        config.foreign_base_unit
    )
    
    # 计算最接近1:1对冲比例的手数组合
    best_ratio_diff = float('inf')
    best_domestic = 1
    best_foreign = 1
    
    # 遍历寻找最佳组合
    for foreign_lots in range(1, max_foreign_lots + 1):
        foreign_units = foreign_lots * config.foreign_lot_size
        domestic_units_needed = foreign_units / conversion_factor
        domestic_lots = round(domestic_units_needed / config.domestic_lot_size)
        
        if domestic_lots == 0:
            domestic_lots = 1
        
        # 计算实际对冲比例
        domestic_total = domestic_lots * config.domestic_lot_size * conversion_factor
        foreign_total = foreign_lots * config.foreign_lot_size
        ratio = foreign_total / domestic_total if domestic_total > 0 else float('inf')
        
        ratio_diff = abs(ratio - 1.0)
        
        if ratio_diff < best_ratio_diff:
            best_ratio_diff = ratio_diff
            best_domestic = domestic_lots
            best_foreign = foreign_lots
    
    # 使用最佳组合计算
    return calculate_lots(config, best_domestic)


def calculate_minimal_lots(config: InstrumentConfig) -> LotCalculation:
    """
    计算最小资金占用的手数组合（国内或境外其中一方为1手）
    
    选择对冲比例更接近1:1的方案
    
    Args:
        config: 品种配置
        
    Returns:
        LotCalculation 对象
    """
    # 方案1: 国内1手
    calc_domestic_1 = calculate_lots(config, domestic_lots=1)
    
    # 方案2: 境外1手，计算需要多少手国内
    conversion_factor = get_conversion_factor(
        config.domestic_base_unit,
        config.foreign_base_unit
    )
    
    foreign_units = config.foreign_lot_size
    domestic_units_needed = foreign_units / conversion_factor
    domestic_lots_needed = round(domestic_units_needed / config.domestic_lot_size)
    
    if domestic_lots_needed == 0:
        domestic_lots_needed = 1
    
    calc_foreign_1 = calculate_lots(config, domestic_lots=domestic_lots_needed)
    
    # 选择对冲比例更接近100%的方案
    ratio_diff_1 = abs(calc_domestic_1.hedge_ratio - 100)
    ratio_diff_2 = abs(calc_foreign_1.hedge_ratio - 100)
    
    if ratio_diff_1 <= ratio_diff_2:
        return calc_domestic_1
    else:
        return calc_foreign_1


def _generate_explanation(
    config: InstrumentConfig,
    domestic_lots: int,
    domestic_total_units: float,
    foreign_lots: int,
    foreign_lots_exact: float,
    foreign_total_units: float,
    foreign_actual_units: float,
    conversion_factor: float
) -> str:
    """生成计算说明"""
    
    lines = [
        f"【{config.name}套利手数计算】",
        "",
        f"国内 {config.domestic_exchange}:",
        f"  - 购买: {domestic_lots} 手",
        f"  - 每手: {config.domestic_lot_size} {config.domestic_base_unit}",
        f"  - 总量: {domestic_total_units:,.2f} {config.domestic_base_unit}",
        "",
        f"单位转换:",
        f"  - 转换系数: 1 {config.domestic_base_unit} = {conversion_factor:,.4f} {config.foreign_base_unit}",
        f"  - 换算为: {foreign_total_units:,.2f} {config.foreign_base_unit}",
        "",
        f"境外 {config.foreign_exchange}:",
        f"  - 每手: {config.foreign_lot_size:,.0f} {config.foreign_base_unit}",
        f"  - 理论手数: {foreign_lots_exact:.4f} 手",
        f"  - 实际购买: {foreign_lots} 手 (向上取整)",
        f"  - 实际总量: {foreign_actual_units:,.2f} {config.foreign_base_unit}",
    ]
    
    # 如果有差异，说明对冲比例
    if abs(foreign_total_units - foreign_actual_units) > 0.01:
        hedge_ratio = (foreign_actual_units / foreign_total_units) * 100
        lines.append("")
        lines.append(f"对冲比例: {hedge_ratio:.2f}% (略微超额对冲)")
    
    return "\n".join(lines)


def calculate_all_instruments(domestic_lots: int = 1) -> Dict[str, LotCalculation]:
    """
    计算所有品种的手数
    
    Args:
        domestic_lots: 国内购买手数
        
    Returns:
        品种代码 -> LotCalculation 的字典
    """
    from instruments import get_enabled_instruments, INSTRUMENTS
    
    results = {}
    for instrument_key in get_enabled_instruments():
        config = INSTRUMENTS[instrument_key]
        calc = calculate_lots(config, domestic_lots)
        results[instrument_key] = calc
        
    return results


if __name__ == "__main__":
    # 测试：计算所有品种购买1手国内合约时，需要多少手境外合约
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("套利手数计算 - 国内购买1手时的境外手数")
    print("=" * 60)
    print()
    
    results = calculate_all_instruments(domestic_lots=1)
    
    for instrument_key, calc in results.items():
        print(calc.explanation)
        print()
        print("-" * 60)
        print()
    
    print()
    print("=" * 60)
    print("最优套利手数计算 - 接近1:1对冲比例的建议")
    print("=" * 60)
    print()
    
    from instruments import get_enabled_instruments, INSTRUMENTS
    
    for instrument_key in get_enabled_instruments():
        config = INSTRUMENTS[instrument_key]
        optimal = calculate_optimal_lots(config)
        
        # 计算对冲比例
        domestic_units_in_foreign = optimal.domestic_total_units * get_conversion_factor(
            config.domestic_base_unit, config.foreign_base_unit
        )
        hedge_ratio = (optimal.foreign_total_units / domestic_units_in_foreign) * 100
        
        print(f"【{config.name}】")
        print(f"  建议: 国内 {optimal.domestic_lots} 手 -> 境外 {optimal.foreign_lots} 手")
        print(f"  对冲比例: {hedge_ratio:.2f}%")
        print()
