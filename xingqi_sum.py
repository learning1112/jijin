import requests
import re
import json
import matplotlib.pyplot as plt
import datetime
from collections import defaultdict
import numpy as np  # 用于趋势线，若不需要可删除

# ====================== 可自定义配置项 ======================
# 在这里设置你想要绘制的星期（支持单个/多个，例如 ["周一"] 或 ["周一", "周三", "周五"]）
TARGET_WEEKDAYS = ["周五"]  # 核心配置：修改这里即可选择要显示的星期
number = "110020"
# ===========================================================

# 1. 请求数据（保留原有逻辑）
headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://fund.eastmoney.com/013880.html',
    'Sec-Fetch-Dest': 'script',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Microsoft Edge";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

params = {
    'v': '20250928213854',
}

response = requests.get(f'https://fund.eastmoney.com/pingzhongdata/{number}.js', params=params, headers=headers)
text = response.text
content = re.findall("Data_netWorthTrend = (.*?)]", text)
content = eval(content[0] + "]")

# 2. 提取并整理数据（时间戳、日期、星期、净值）
data_list = []
x = []
y = []
for item in content:
    ts = int(item["x"])
    val = float(item["y"])
    x.append(ts)
    y.append(val)
    
    # 转换为日期和星期
    dt = datetime.datetime.fromtimestamp(ts/1000, tz=datetime.timezone.utc).astimezone()
    date_str = dt.strftime("%Y-%m-%d")
    weekday_num = dt.weekday()
    weekday_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_zh[weekday_num]
    
    data_list.append((ts, date_str, weekday, val))

# 3. 时间戳转星期函数（保留）
def timestamp_to_weekday(timestamp_ms, lang='zh'):
    dt = datetime.datetime.fromtimestamp(timestamp_ms/1000, tz=datetime.timezone.utc).astimezone()
    weekday_num = dt.weekday()
    weekday_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return weekday_zh[weekday_num] if lang == 'zh' else weekday_en[weekday_num]

# 4. 按星期统计（保留原有逻辑）
weekday_data = defaultdict(list)
for ts, val in zip(x, y):
    weekday = timestamp_to_weekday(ts, lang='zh')
    weekday_data[weekday].append(val)

weekday_stats = {}
for weekday, values in weekday_data.items():
    if weekday == "周六" or weekday == "周日":
        print(f"{weekday}的数据点：{values}")
        continue
    total = sum(values)
    avg = total / len(values)
    weekday_stats[weekday] = {
        'sum': total,
        'avg': avg,
        'count': len(values)
    }

# 5. 绘制原有柱状图（星期平均值）
plt.rcParams['font.sans-serif'] = ['SimHei']  # 解决中文显示
plt.figure(figsize=(10, 6))
weekday_order_zh = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
sorted_weekdays = [wd for wd in weekday_order_zh if wd in weekday_stats]
avg_vals = [weekday_stats[wd]['avg'] for wd in sorted_weekdays]

bars = plt.bar(sorted_weekdays, avg_vals, color='skyblue', alpha=0.8)
for bar, val in zip(bars, avg_vals):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
             f'{val:.4f}', ha='center', va='bottom', fontsize=10)
plt.title('基金净值按星期分组的平均值', fontsize=14)
plt.xlabel('星期', fontsize=12)
plt.ylabel('净值平均值', fontsize=12)
plt.grid(axis='y', linestyle='--', alpha=0.3)
plt.tight_layout()
plt.show()

# 6. 绘制可自定义星期的散点图（核心修改部分）
# 定义星期配色（固定）
weekday_colors = {
    "周一": '#1f77b4',
    "周二": '#ff7f0e',
    "周三": '#2ca02c',
    "周四": '#d62728',
    "周五": '#9467bd',
    "周六": '#8c564b',
    "周日": '#e377c2'
}

# 筛选目标星期的数据
filtered_data = [item for item in data_list if item[2] in TARGET_WEEKDAYS]
if not filtered_data:
    print(f"⚠️  未找到 {TARGET_WEEKDAYS} 对应的任何数据，请检查星期名称是否正确！")
else:
    # 准备筛选后的散点数据
    time_index = [i for i, item in enumerate(data_list) if item[2] in TARGET_WEEKDAYS]  # 保持原时间顺序索引
    net_values = [item[3] for item in filtered_data]
    weekdays = [item[2] for item in filtered_data]
    colors = [weekday_colors[wd] for wd in weekdays]

    # 绘制散点图
    plt.figure(figsize=(12, 7))
    scatter = plt.scatter(
        time_index, 
        net_values, 
        c=colors, 
        alpha=0.8,
        s=60,
        edgecolors='black',
        linewidths=0.5
    )

    # 可选：添加目标星期的趋势线
    if len(time_index) > 1:
        z = np.polyfit(time_index, net_values, 1)
        p = np.poly1d(z)
        plt.plot(time_index, p(time_index), "r--", alpha=0.8, label='选中星期的趋势线')

    # 设置图表标题和标签
    target_weekdays_str = "、".join(TARGET_WEEKDAYS)
    plt.title(f'基金净值按时间顺序分布（仅显示：{target_weekdays_str}）', fontsize=14)
    plt.xlabel('时间顺序（索引）', fontsize=12)
    plt.ylabel('基金净值', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.3)

    # 只显示选中星期的图例
    legend_elements = [plt.Line2D([0], [0], marker='o', color='w', markerfacecolor=weekday_colors[wd],
                                  markersize=10, label=wd, markeredgecolor='black', markeredgewidth=0.5)
                       for wd in TARGET_WEEKDAYS if wd in weekday_colors]
    plt.legend(handles=legend_elements, loc='best', title='选中的星期')

    plt.tight_layout()
    plt.show()

    # 打印选中星期的统计信息
    print(f"\n=== 选中星期（{target_weekdays_str}）的统计信息 ===")
    for wd in TARGET_WEEKDAYS:
        if wd in weekday_data:
            values = weekday_data[wd]
            print(f"{wd}：数据量={len(values)}, 平均值={np.mean(values):.4f}, 最大值={np.max(values):.4f}, 最小值={np.min(values):.4f}")
        else:
            print(f"{wd}：无数据")

# 打印全部星期统计（保留）
print("\n=== 所有工作日统计结果 ===")
for weekday in sorted_weekdays:
    stats = weekday_stats[weekday]
    print(f"{weekday}: 数据量={stats['count']}, 求和={stats['sum']:.4f}, 平均值={stats['avg']:.4f}")
