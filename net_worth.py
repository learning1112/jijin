import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://fund.eastmoney.com/000307.html?spm=search',
    'Sec-Fetch-Dest': 'script',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0',
    'sec-ch-ua': '"Chromium";v="142", "Microsoft Edge";v="142", "Not_A Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

current_time_str = datetime.now().strftime("%Y%m%d%H%M%S")
params = {
    'spm': 'search',
    # "v":current_time_str
}
def fetch_fund_data(number):
    response = requests.get(f'https://fund.eastmoney.com/pingzhongdata/{number}.js', params=params, headers=headers)
    text = response.text
    pattern = r'var Data_millionCopiesIncome = (\[\[.*?\]\]);'
    if "Data_millionCopiesIncome" in text:
        match = re.search(pattern, text, re.DOTALL)
        if match:
        # 提取捕获组中的数组字符串（如 "[[1364140800000, 21.2775], ...]"）
            array_str = match.group(1)
            # 解析为 Python 列表（兼容空格、整数/小数）
            # 步骤1：提取所有数字对（时间戳+数值）
            item_pattern = r'\[(\d+),\s*(\d+\.?\d*)\]'  # 匹配 [数字, 数值]，允许空格
            matches = re.findall(item_pattern, array_str)
            # 步骤2：转换类型（时间戳→int，数值→float）
            result = [[int(ts), float(val)] for ts, val in matches]

            print("仅 Data_millionCopiesIncome 对应的数组：")
            x = [int(i[0]) for i in result]
            y = [float(i[1]) for i in result]
            z = 0
            # return (dict(zip(x,y)),z)
            return x,y,z
        else:
            print("未找到 Data_millionCopiesIncome 变量的数组")
            return [],[],-1
    elif "Data_netWorthTrend" in text:
        content = re.findall("Data_netWorthTrend = (.*?)]", text)
        content = eval(content[0] + "]")
        # print(content)
        x = [int(i["x"]) for i in content]
        y = [float(i["y"]) for i in content]
        z = 1
        # print(y)
        # return (dict(zip(x,y)),z)
        return x,y,z
def cal_pnl(cash,net_worth,type):
    pnl = []
    if type == 0:
        all_cash = cash
        for i in net_worth:
            if i != i:
                pnl.append(cash)
            else:
                returns = all_cash / 10000 * i
                cash = cash + returns
                pnl.append(cash)
    elif type == 1:
        num = 0
        for i in net_worth:
            if i != i:
                pnl.append(cash)
            else:
                if num == 0:
                    num = cash / i
                    pnl.append(cash)
                else:
                    cash = num *i
                    pnl.append(cash)
    return pnl
def cal_distribution(distribution):
    type_dict = {}
    data_list = []  
    for id in distribution:
        x,y,z = fetch_fund_data(id)
        type_dict[id] = z
        df = pd.DataFrame({"date":x,id:y})
        df.set_index("date",inplace=True)
        data_list.append(df)
    merged_df = pd.concat(data_list,axis=1,join='outer',sort=True)
    pnl_df = merged_df.copy()
    for id in distribution:
        
        pnl = cal_pnl(10000*distribution[id],merged_df[id].tolist(),type_dict[id])
        pnl2 = cal_pnl(10000,merged_df[id].tolist(),type_dict[id])
        plt.plot(merged_df.index, pnl2, label=id)
        pnl_df[id] = pnl
    pnl_df['total'] = pnl_df.sum(axis=1)
    all_worth = pnl_df["total"].to_list()
    all_dd = []
    for i in range(len(pnl_df)):
        worth = all_worth[:i+1]
        max_worth = max(worth)
        worth_now = all_worth[i]
        dd = (max_worth - worth_now)/max_worth
        all_dd.append(dd)
    pnl_df['drawdown'] = all_dd
    drawdown = max(pnl_df['drawdown'])
    margin = ((all_worth[-1] - all_worth[0]) / (len(pnl_df)/365)) / 10000
    return margin*100,drawdown*100



if __name__ == "__main__":


    distribution = {"000307":0.25,"019567":0.25,"012693":0.25,"513110":0.25}
    type_dict = {}
    data_list = []  
    for id in distribution:
        x,y,z = fetch_fund_data(id)
        type_dict[id] = z
        df = pd.DataFrame({"date":x,id:y})
        df.set_index("date",inplace=True)
        data_list.append(df)
    merged_df = pd.concat(data_list,axis=1,join='outer',sort=True)
    pnl_df = merged_df.copy()
    
    plt.figure(figsize=(12, 6))
    for id in distribution:
        
        pnl = cal_pnl(10000*distribution[id],merged_df[id].tolist(),type_dict[id])
        pnl2 = cal_pnl(10000,merged_df[id].tolist(),type_dict[id])
        plt.plot(merged_df.index, pnl2, label=id)
        pnl_df[id] = pnl
    pnl_df['total'] = pnl_df.sum(axis=1)
    all_worth = pnl_df["total"].to_list()
    all_dd = []
    for i in range(len(pnl_df)):
        worth = all_worth[:i+1]
        max_worth = max(worth)
        worth_now = all_worth[i]
        dd = (max_worth - worth_now)/max_worth
        all_dd.append(dd)
    pnl_df['drawdown'] = all_dd
    # pnl_df = pnl_df.loc[pnl_df.index > 1.6e12,:]
    print(pnl_df)
    print(max(pnl_df['drawdown']))
    print(len(pnl_df)/365)
    plt.plot(pnl_df.index, pnl_df['total'], label='Total', linewidth=2, color='black')
    plt.legend()
    plt.figure(figsize=(12, 6))
    plt.plot(pnl_df.index, pnl_df['drawdown'], label='drawdown', linewidth=2, color='black')
    plt.show() 

    
    
    # x,y,z2 = fetch_fund_data("000307")

