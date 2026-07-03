import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
headers = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-site',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Microsoft Edge";v="140"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

params = {
    'spm': 'search',
}
result = {}
error = []
with open(r"result3_filter5.txt","r") as f:
    numbers = [i.strip("\n") for i in f.readlines()]
for index, number in enumerate(numbers):
    print(f"{index}/{len(numbers)}")
    response = requests.get(f'https://fund.eastmoney.com/{number}.html', params=params, headers=headers)
    soup = BeautifulSoup(response.content.decode("utf-8"), "html.parser")
    # row = soup.find("div", text="阶段涨幅").find_parent("tr")
    targets = soup.find_all("div", class_="typeName", text="阶段涨幅")
    all_years = []
    for target in targets:
        row = target.find_parent("tr")   # 找到对应的行
        values = [div.text.strip() for div in row.find_all("div", class_="Rdata")]
        if values:
            all_years.append(values)
    if not all_years:
        error.append(number)
        print("error")

        continue
    years_perfor = [float(i[:-1]) for i in all_years[2] if "%" in i]
    avg_perfor = sum(years_perfor) / len(years_perfor)
    
    result[number] = avg_perfor
print(error)
result = dict(sorted(result.items(), key=lambda item: item[1], reverse=True))
with open("result3_filter5_sort.txt", "w") as file:
    for r in result:
        file.write(r + " " + str(result[r]) + "\n")
# # 转成 DataFrame，行就是不同年份，列就是不同季度/区间
# df = pd.DataFrame(all_years)
# print(df)
# 提取这一行所有的百分比
# values = [div.text.strip() for div in row.find_all("div", class_="Rdata")]
# print(values)

