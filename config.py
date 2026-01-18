"""
跨境期权套利监控系统 - 配置文件

所有可调整的参数都在这里配置
"""

# ============================================================
#                    Telegram 配置
# ============================================================
TELEGRAM_BOT_TOKEN = "8029479427:AAEOJqdxUeQu8mIbIyKEsOGDWsH0v4DXcZU"
TELEGRAM_CHAT_ID = "-5154029819"


# ============================================================
#                    监控品种配置
# ============================================================
# 每个品种的配置参数：
#   enabled: 是否启用监控
#   iv_open_threshold: 开仓IV差阈值（超过此值触发开仓信号）
#   iv_close_threshold: 平仓IV差阈值（低于此值触发平仓信号）
#   iv_stop_loss: 止损IV差阈值（超过此值触发止损）
#   min_iv_diff: 最小IV差（过滤噪音）

INSTRUMENTS_CONFIG = {

    # ========== 铜 ==========
    "copper": {
        "enabled": True,                # 是否启用
        "name": "铜",                   # 中文名称
        "name_en": "Copper",            # 英文名称

        # 国内市场
        "domestic_exchange": "SHFE",    # 交易所
        "domestic_symbol": "CU",        # 合约代码
        "domestic_unit": "元/吨",       # 单位

        # 境外市场
        "foreign_exchange": "CME",
        "foreign_symbol": "HG",
        "foreign_yf_symbol": "HG=F",    # yfinance代码
        "foreign_unit": "美元/磅",

        # 套利参数
        "iv_open_threshold": 8.0,       # 开仓阈值
        "iv_close_threshold": 5.0,      # 平仓阈值
        "iv_stop_loss": 18.0,           # 止损阈值
        "min_iv_diff": 3.0,             # 最小IV差
    },

    # ========== 黄金 ==========
    "gold": {
        "enabled": True,
        "name": "黄金",
        "name_en": "Gold",

        "domestic_exchange": "SHFE",
        "domestic_symbol": "AU",
        "domestic_unit": "元/克",

        "foreign_exchange": "CME",
        "foreign_symbol": "GC",
        "foreign_yf_symbol": "GC=F",
        "foreign_unit": "美元/盎司",

        "iv_open_threshold": 6.0,
        "iv_close_threshold": 4.0,
        "iv_stop_loss": 15.0,
        "min_iv_diff": 2.0,
    },

    # ========== 白银 ==========
    "silver": {
        "enabled": True,
        "name": "白银",
        "name_en": "Silver",

        "domestic_exchange": "SHFE",
        "domestic_symbol": "AG",
        "domestic_unit": "元/千克",

        "foreign_exchange": "CME",
        "foreign_symbol": "SI",
        "foreign_yf_symbol": "SI=F",
        "foreign_unit": "美元/盎司",

        "iv_open_threshold": 8.0,
        "iv_close_threshold": 5.0,
        "iv_stop_loss": 18.0,
        "min_iv_diff": 3.0,
    },

    # ========== 原油 ==========
    "crude_oil": {
        "enabled": True,
        "name": "原油",
        "name_en": "Crude Oil",

        "domestic_exchange": "INE",
        "domestic_symbol": "SC",
        "domestic_unit": "元/桶",

        "foreign_exchange": "CME",
        "foreign_symbol": "CL",
        "foreign_yf_symbol": "CL=F",
        "foreign_unit": "美元/桶",

        "iv_open_threshold": 8.0,
        "iv_close_threshold": 5.0,
        "iv_stop_loss": 18.0,
        "min_iv_diff": 3.0,
    },
}


# ============================================================
#                    全局套利参数
# ============================================================
# 到期前几天强制平仓
DAYS_BEFORE_EXPIRY = 7

# 最大持仓天数
MAX_HOLDING_DAYS = 21


# ============================================================
#                    监控配置
# ============================================================
# 监控间隔（秒）
MONITOR_INTERVAL = 300  # 5分钟

# 同一品种信号最小间隔（秒），避免重复通知
SIGNAL_MIN_INTERVAL = 1800  # 30分钟

# 交易时段（北京时间）
TRADING_HOURS = {
    "day": {"start": "09:00", "end": "15:00"},
    "night": {"start": "21:00", "end": "01:00"}
}

# 兼容旧代码
SHFE_TRADING_HOURS = TRADING_HOURS


# ============================================================
#                    风险参数
# ============================================================
# 汇率（用于收益计算）
USD_CNY_RATE = 7.20


# ============================================================
#                    日志配置
# ============================================================
LOG_LEVEL = "INFO"
LOG_FILE = "options_hedging.log"


# ============================================================
#                    兼容旧版本的配置
# ============================================================
# 以下参数保留用于兼容单品种监控程序
IV_DIFF_THRESHOLD = 5.0
MIN_IV_DIFF = 3.0
CLOSE_IV_THRESHOLD = 5.0
STOP_LOSS_IV_THRESHOLD = 18.0
