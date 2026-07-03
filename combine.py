from net_worth import *
import pandas as pd

jijin_path = "基金列表.csv"
data_df = pd.read_csv(jijin_path,sep=",", dtype={"基金代码": str})
distribution = {"000307":0.25,"511010":0.25,"000009":0.25,"513110":0.25}
huobi_df = data_df.loc[data_df["基金类型"]=="货币型-普通货币",:]
huobi_etf_df = huobi_df.loc[huobi_df["基金简称"].str.contains("ETF"),:]

zhai_df = data_df.loc[data_df["基金类型"]=="指数型-海外股票",:]
zhai_etf_df = zhai_df.loc[zhai_df["基金简称"].str.contains("ETF"),:]

zhai_etf_df = zhai_etf_df.loc[zhai_etf_df["基金简称"].str.contains("纳斯达克"),:]
index_list= []
dd_list = []
mar_list = []
for i in huobi_etf_df["基金代码"]:
    for j in zhai_etf_df["基金代码"]:
        distribution = {"000307":0.25,i:0.25,"012693":0.25,j:0.25}
        dd, margine = cal_distribution(distribution)
        index_list.append(f"{i}_{j}")
        dd_list.append(dd)
        mar_list.append(margine)
res_df = pd.DataFrame({
    "dd":dd_list,
    "mar":mar_list,
})
res_df.index = index_list
res_df.index.name = "combine"
res_df.to_csv("res.txt",sep="\t",index=True)
