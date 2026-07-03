import akshare as ak
import pandas as pd
import warnings
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 设置中文字体（避免中文乱码）
plt.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False  # 解决负号显示问题
warnings.filterwarnings('ignore')

# 下载纳斯达克股票（AAPL示例）的全部历史日线+成交量
def get_nasdaq_history(symbol="AAPL"):
    try:
        # 尝试带后缀的代码（美股常用格式），再尝试纯代码
        symbol_list = [symbol, f"{symbol}.O"]  # .O代表纳斯达克
        df = None
        for sym in symbol_list:
            try:
                df = ak.stock_us_daily(symbol=sym, adjust="")  # 基础不复权数据
                if df is not None and not df.empty:
                    break
                df = ak.stock_us_daily(symbol=sym, adjust="hfq")  # 备选复权数据
                if df is not None and not df.empty:
                    break
            except:
                continue
        
        if df is None or df.empty:
            print(f"❌ {symbol} 未获取到任何数据，请检查股票代码是否正确")
            return None
        
        # 仅保留核心字段：日期+收盘价
        df.rename(columns={"date": "Date", "close": "Close"}, inplace=True)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df[["Date", "Close"]].drop_duplicates().sort_values(by="Date")
        df.set_index("Date", inplace=True)
        
        # 保存到CSV（仅保留日期和收盘价）
        csv_path = f"{symbol}_nasdaq_close_history.csv"
        df.to_csv(csv_path, encoding="utf-8-sig")
        
        print(f"✅ {symbol} 收盘价数据下载成功！")
        print(f"📅 数据时间范围：{df.index.min()} 至 {df.index.max()}")
        print(f"📊 数据总行数：{len(df)} 行")
        print(f"💾 保存路径：{csv_path}")
        return df
    
    except Exception as e:
        print(f"❌ {symbol} 下载失败：{str(e)}")
        return None

# 仅绘制每日收盘价走势
def plot_close_price(df, symbol="AAPL"):
    if df is None or df.empty:
        print("❌ 无数据可绘图")
        return
    
    # 创建图表
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # 绘制收盘价曲线（核心）
    ax.plot(df.index, df["Close"], label="收盘价", color="#1f77b4", linewidth=1.8)
    
    # 图表美化
    ax.set_title(f"{symbol} 纳斯达克每日收盘价走势", fontsize=16, pad=20)
    ax.set_xlabel("日期", fontsize=12)
    ax.set_ylabel("收盘价 (USD)", fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=12)
    
    # 设置x轴日期格式（按年显示，避免拥挤）
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    plt.xticks(rotation=45)
    
    # 调整布局并保存
    plt.tight_layout()
    plt.savefig(f"{symbol}_close_price_chart.png", dpi=300, bbox_inches="tight")
    print(f"✅ 收盘价图表已保存：{symbol}_close_price_chart.png")
    
    # 显示图表
    plt.show()

# 主流程：下载收盘价数据 → 绘制收盘价图表
if __name__ == "__main__":
    symbol = "AAPL"  # 可修改为其他股票代码（如MSFT、GOOGL）
    df = get_nasdaq_history(symbol)
    plot_close_price(df, symbol)
    
    # 批量下载+绘制多只股票（取消注释即可）
    # tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
    # for ticker in tickers:
    #     df = get_nasdaq_history(ticker)
    #     plot_close_price(df, ticker)