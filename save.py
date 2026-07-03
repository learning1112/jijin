import pandas as pd
import numpy as np
data_path = r"scores.xlsx"
name_path = r"name.txt"
with open(name_path,"r",encoding="utf-8") as f:
    names = [i.strip("\n") for i in f.readlines()]
data = pd.read_excel(data_path, sheet_name = "Sheet0")
# print(data.head())
data = data[data['姓名'].isin(names)]
# print(data)
data_clean = data.dropna(subset=['导师姓名'])

data_clean = data_clean[pd.to_numeric(data_clean['总成绩'], errors='coerce').notna()]
print(data_clean)
result = {}
for name in names:
    student = data_clean[data_clean['姓名'] == name]
    
    scores = (np.dot(student["学分"].to_numpy().astype(np.float64),student["总成绩"].to_numpy().astype(np.float64)) * 0.5)/ sum(student["学分"].to_numpy().astype(np.float64))
    result[name] = scores
sorted_result = dict(sorted(result.items(), key=lambda item: item[1], reverse=True))
with open("sort_result.txt","w",encoding="utf-8") as f:
    for k,v in sorted_result.items():
        f.write(f"{k}\t{v}\n")

    