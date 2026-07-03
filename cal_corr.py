import requests
import re
import matplotlib.pyplot as plt
import pandas as pd
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
data_df = pd.DataFrame()
with open("result3.txt", "r") as f:
    lines = [i.strip("\n") for i in f.readlines()]
for line in lines:
    print(line)
    response = requests.get(f'https://fund.eastmoney.com/pingzhongdata/{line}.js', headers=headers)
    text = response.text
    ac = text.split('Data_ACWorthTrend = ')[1] 
    ac = ac.replace('null', 'None')
    acworth = eval(ac.split(';')[0])

    # print(acworth)
    x = []
    y = []
    for item in acworth:
        x.append(item[0])
        y.append(item[1])
    if len(y) > 1000:
        data_df.loc[:,line] = y[-1000:]
print(data_df.index)
print(data_df.head())
data_df.corr().to_csv("corr3.csv")
# content = re.findall("Data_ACWorthTrend = (.*?)", text)
# print(content)
