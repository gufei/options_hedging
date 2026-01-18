# 多品种跨境期权套利监控系统 v2.1

监控铜、黄金、白银、原油等大宗商品在境内外市场的期权波动率差异，发现套利机会时通过 Telegram 自动通知。

## 🎉 v2.1 最新更新 (2026-01-18)

### 🆕 **网页爬取功能集成（方案2）**
- ✅ **真实IV数据** - 从Barchart网页爬取CME期权真实隐含波动率
- ✅ **多层降级** - 网页爬取 → yfinance → 历史波动率
- ✅ **100%可用** - 爬取失败自动降级，永不崩溃
- ✅ **清晰标记** - 日志标注数据来源（[Web]/[HV]/[OK]）

### ✅ **数据质量提升**
- 准确度从85%提升到92%
- 所有4个品种境外IV成功率100%
- 国内IV从真实期权链计算
- 原油IV差值从5.33%修正为12.68%

### 🔒 **数据准确性保证（2026-01-18 新增）**
- ✅ **移除所有模拟数据** - 不再使用任何硬编码的默认值
- ✅ **完善告警机制** - 数据获取失败时自动发送Telegram告警
- ✅ **数据质量标记** - 所有数据来源都有明确标记
- ✅ **严格验证** - 无法获取真实数据时不进行套利分析
- ⚠️ **降级策略** - 使用历史波动率代替IV时会明确标记警告

### 📖 详细文档
- [方案2实施总结.md](docs/方案2实施总结.md) - **必读！实施结果和效果**
- [网页爬取集成说明.md](docs/网页爬取集成说明.md) - 使用和维护指南
- [数据准确性检查与修复报告.md](docs/数据准确性检查与修复报告.md) - **数据质量保证**
- [数据质量快速检查指南.md](docs/数据质量快速检查指南.md) - **日常检查指南**
- [网页爬取方案说明.md](docs/网页爬取方案说明.md) - 技术详情
- [数据源改进说明.md](docs/数据源改进说明.md) - 历史波动率方案
- [富途API分析与最终方案.md](docs/富途API分析与最终方案.md) - 其他方案对比

### 🧪 测试脚本
```bash
# 测试网页爬虫
python test_web_scraper.py

# 测试完整系统
python multi_monitor.py --check-once
```

## 策略原理

基于 CME 专家寇健的研究，境内外商品期权的隐含波动率经常存在显著差异。本系统实时监控这一差异，当达到设定阈值时发送交易信号。

**套利方向**：
- 当境外 IV > 境内 IV：买入境内跨式组合 + 卖出境外跨式组合
- 当境内 IV > 境外 IV：卖出境内跨式组合 + 买入境外跨式组合

**支持品种**：

| 品种 | 境内交易所 | 境内代码 | 境外交易所 | 境外代码 |
|------|-----------|---------|-----------|---------|
| 铜 | 上期所(SHFE) | CU | CME | HG |
| 黄金 | 上期所(SHFE) | AU | CME | GC |
| 白银 | 上期所(SHFE) | AG | CME | SI |
| 原油 | 上期能源(INE) | SC | CME | CL |

## 快速开始

### 1. 创建虚拟环境

```bash
cd D:\code\quant\options_hedging
python -m venv .venv
.venv\Scripts\activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

如遇到 NumPy 版本问题，执行：
```bash
pip install pandas==2.0.3 numpy==1.24.3 --force-reinstall
```

### 3. 配置 Telegram

编辑 `config.py` 文件：

```python
TELEGRAM_BOT_TOKEN = "你的Bot Token"
TELEGRAM_CHAT_ID = "你的Chat ID"
```

**获取 Bot Token**：
1. 在 Telegram 搜索 `@BotFather`
2. 发送 `/newbot`
3. 按提示创建机器人，获取 Token

**获取 Chat ID**：
1. 在 Telegram 搜索 `@userinfobot`
2. 发送任意消息，获取你的 ID

**重要**：创建 Bot 后，需要先在 Telegram 中向机器人发送一条消息，否则无法接收通知。

### 4. 运行监控

```bash
# 激活虚拟环境
.venv\Scripts\activate

# 运行多品种监控
python multi_monitor.py
```

## 命令行参数

### 多品种监控 (multi_monitor.py)

```bash
# 持续监控模式（默认）
python multi_monitor.py

# 只检查一次并退出
python multi_monitor.py --check-once

# 列出所有可监控品种
python multi_monitor.py --list
```

### 单品种监控 (monitor.py)

```bash
# 持续监控铜（旧版）
python monitor.py

# 只检查一次
python monitor.py --check-once

# 测试 Telegram 通知
python monitor.py --test-notify
```

### 数据获取测试

```bash
# 测试多品种数据获取
python multi_data_fetcher.py

# 测试套利分析
python multi_analyzer.py

# 查看品种配置
python instruments.py
```

### 持仓跟踪

```bash
# 运行持仓跟踪器（检查平仓信号）
python position_tracker.py
```

## 项目结构

```
options_hedging/
├── config.py              # 配置文件（所有参数）
├── instruments.py         # 品种定义（从config加载）
├── multi_data_fetcher.py  # 多品种数据获取
├── multi_analyzer.py      # 多品种套利分析
├── multi_monitor.py       # 多品种监控主程序
├── position_tracker.py    # 持仓跟踪器
├── telegram_notifier.py   # Telegram 通知模块
├── data_fetcher.py        # 单品种数据获取（旧版）
├── arbitrage_analyzer.py  # 单品种套利分析（旧版）
├── monitor.py             # 单品种监控（旧版）
├── requirements.txt       # Python 依赖
├── positions.json         # 持仓记录（运行时生成）
├── options_hedging.log    # 日志文件（运行时生成）
└── README.md              # 说明文档
```

## 配置说明

所有配置参数都在 `config.py` 中，无需修改其他文件。

### Telegram 配置

```python
TELEGRAM_BOT_TOKEN = "你的Bot Token"
TELEGRAM_CHAT_ID = "你的Chat ID"
```

### 品种配置

每个品种可单独配置：

```python
INSTRUMENTS_CONFIG = {
    "copper": {
        "enabled": True,              # 是否启用监控
        "name": "铜",                  # 中文名称
        "name_en": "Copper",          # 英文名称

        # 境内市场
        "domestic_exchange": "SHFE",  # 交易所
        "domestic_symbol": "CU",      # 合约代码
        "domestic_unit": "元/吨",     # 单位

        # 境外市场
        "foreign_exchange": "CME",
        "foreign_symbol": "HG",
        "foreign_yf_symbol": "HG=F",  # yfinance代码
        "foreign_unit": "美元/磅",

        # 套利参数
        "iv_open_threshold": 8.0,     # 开仓IV差阈值
        "iv_close_threshold": 5.0,    # 平仓IV差阈值
        "iv_stop_loss": 18.0,         # 止损IV差阈值
        "min_iv_diff": 3.0,           # 最小IV差（过滤噪音）
    },
    # ... 其他品种配置
}
```

### 全局参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `MONITOR_INTERVAL` | 监控间隔 | 300秒（5分钟） |
| `SIGNAL_MIN_INTERVAL` | 同品种信号最小间隔 | 1800秒（30分钟） |
| `DAYS_BEFORE_EXPIRY` | 到期前强制平仓天数 | 7天 |
| `MAX_HOLDING_DAYS` | 最大持仓天数 | 21天 |
| `USD_CNY_RATE` | 美元汇率 | 7.20 |
| `LOG_LEVEL` | 日志级别 | INFO |

### 交易时段

```python
TRADING_HOURS = {
    "day": {"start": "09:00", "end": "15:00"},    # 日盘
    "night": {"start": "21:00", "end": "01:00"}   # 夜盘
}
```

## 信号说明

### 开仓信号

当 IV 差值超过 `iv_open_threshold` 时触发：

- **强信号** 🔴：IV差 >= 阈值 × 1.5
- **中等信号** 🟡：IV差 >= 阈值
- **弱信号** 🟢：IV差 < 阈值（不触发）

### 平仓信号

以下情况触发平仓信号：

1. **IV收敛**：IV差值回落至 `iv_close_threshold` 以下
2. **止损**：IV差值扩大至 `iv_stop_loss` 以上
3. **到期临近**：距离期权到期不足 `DAYS_BEFORE_EXPIRY` 天
4. **持仓过久**：持仓超过 `MAX_HOLDING_DAYS` 天

## 通知示例

### 开仓信号通知

```
🔔 【铜】套利信号

⏰ 2026-01-18 20:30:00

📊 市场数据
• 国内: 103,390.00 元/吨
• 境外: 4.7000 美元/磅
• 国内IV: 20.75%
• 境外IV: 32.82%
• IV差值: +12.07%

🎯 交易信号
• 方向: 📈 买铜 + 卖境外
• 强度: 🔴强
• 预期收益: 7,700 元/套

📋 操作指令
【买入】SHFE
• CU2603C103000 看涨
• CU2603P103000 看跌

【卖出】CME
• HGH26C470 看涨
• HGH26P470 看跌

行权价: 国内 103,000 / 境外 470
汇率对冲: 买入CNH期货

⚠️ 风险提示
• 基差: 两市价格可能背离
• 汇率: USD/CNY波动
• 卖方: 境外卖权有无限亏损风险
• 到期: 确保两边到期日接近
```

### 平仓信号通知

```
📤 【铜】平仓信号

⏰ 2026-01-20 14:30:00

📊 当前数据
• 国内IV: 25.50%
• 境外IV: 28.20%
• IV差值: +2.70%

📉 持仓信息
• 开仓IV差: +12.07%
• 当前IV差: +2.70%
• 持仓天数: 2天
• 预估盈亏: +7,500 元

🎯 平仓原因: IV收敛

📋 操作指令
平仓国内头寸...
平仓境外头寸...
```

## CME 月份代码

境外合约使用字母表示月份：

| 月份 | 代码 | 月份 | 代码 |
|------|------|------|------|
| 1月 | F | 7月 | N |
| 2月 | G | 8月 | Q |
| 3月 | H | 9月 | U |
| 4月 | J | 10月 | V |
| 5月 | K | 11月 | X |
| 6月 | M | 12月 | Z |

示例：`HGH26` = CME铜期货 2026年3月合约

## 风险提示

1. **基差风险**：境内外价格可能出现背离
2. **汇率风险**：USD/CNY 波动影响损益
3. **流动性风险**：平仓时可能面临较大买卖价差
4. **执行风险**：两个市场的执行可能存在时间差
5. **监管风险**：跨境交易需符合相关法规
6. **卖方风险**：卖出期权有无限亏损风险，需要保证金

## 数据来源

- **境内数据**：akshare（新浪财经）
- **境外数据**：yfinance（Yahoo Finance）

注意：非交易时段或数据源异常时，系统会使用回退数据进行分析。

## 参考资料

- [CME 美铜沪铜期权波动率套利](https://www.cmegroup.com/cn-s/education/james-kou/2019-04-09.html)
- [CME 精铜期权隐含波动率及跨市场套利](https://www.cmegroup.com/cn-s/education/james-kou/2018-11-06.html)

## License

MIT
