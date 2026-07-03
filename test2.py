import re

# 原始字符串（含多个变量，仅提取 Data_millionCopiesIncome 对应数组）
raw_str = '''
var Data_millionCopiesIncome = [[1364140800000, 21.2775], [1364227200000, 0.9561], [1364313600000, 0.3729], [1364400000000, 0.7068], [1364486400000, 0.6744]];
var Other_Data = [[123456, 78.9], [456789, 12.3]];  // 其他变量，不匹配
var Data_otherIncome = [[987654, 34.5], [654321, 56.7]];  // 类似名称，不匹配
'''

# 修复后的正则：宽松匹配数组格式，允许空格、整数/小数、末尾可选逗号
pattern = r'var Data_millionCopiesIncome = (\[\[.*?\]\]);'
# 解释：
# var Data_millionCopiesIncome = ：精准锁定目标变量名
# (\[\[.*?\]\]) ：捕获组，非贪婪匹配从 [[ 到 ]] 的所有内容（兼容任意子项格式）
# ; ：匹配变量结尾的分号

# 查找匹配（re.DOTALL 确保 . 能匹配换行，避免数组跨换行时失败）
match = re.search(pattern, raw_str, re.DOTALL)
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
    print(result)
else:
    print("未找到 Data_millionCopiesIncome 变量的数组")