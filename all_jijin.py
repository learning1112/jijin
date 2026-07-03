import requests
import pandas as pd
headers = {
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://fund.eastmoney.com/ZQ_jzzzl.html',
    'Sec-Fetch-Dest': 'script',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Microsoft Edge";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

response = requests.get('https://fund.eastmoney.com/js/fundcode_search.js', headers=headers)
text = response.text[8:-1]
text = eval(text)
data_df = pd.DataFrame(text)
data_df.columns = ["基金代码","基金缩写","基金简称","基金类型","基金拼音"]
print(data_df.head())
data_df.to_csv("基金列表.csv",index=False,encoding="utf-8-sig")
# print(text[:1000])
# print(text[-1000:])
