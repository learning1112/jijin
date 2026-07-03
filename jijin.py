import requests
import re
import json
import matplotlib.pyplot as plt
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

response = requests.get('https://fund.eastmoney.com/pingzhongdata/159934.js', params=params, headers=headers)
text = response.text
content = re.findall("Data_netWorthTrend = (.*?)]", text)
content = eval(content[0] + "]")
x = [int(i["x"]) for i in content]
y = [float(i["y"]) for i in content]
print(x[-1],x[-2])
print(y[-1])
print(len(x),len(y))
# plt.plot(x, y)
plt.boxplot(y)
plt.show()
# print(content[0]["x"])
# print(content)
