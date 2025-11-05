# module/utils.py
import re
import datetime
import shutil
from pathlib import Path
from collections.abc import Sequence

import pandas as pd
from cn2an import cn2an

def is_sequence(obj):
    return isinstance(obj, Sequence) and not isinstance(obj, (str, bytes))

def to_list(obj):
    return list(obj) if is_sequence(obj) else [obj]

def convert_to_number(x, fail_return=None):
    try:
        if x == '' or pd.isna(x):
            return fail_return
        x = cn2an(re.sub(r'[_\s]', '', str(x)), mode='smart')   # 中文数字转阿拉伯
    except Exception:
        return fail_return
    return int(x) if x == int(x) else x

def convert_to_date(x, fail_return=None):
    if x == '' or pd.isna(x):
        return fail_return
    x = re.sub(r'[_\s]', '', str(x))

    # YYYY-MM-DD
    if re.search(r'^\d{4}-\d{1,2}-\d{1,2}$', x.strip()):
        try:
            d = datetime.datetime.strptime(x, '%Y-%m-%d')
            return d.strftime('%Y-%m-%d')
        except Exception:
            return fail_return

    # YYYY年MM月DD日
    if '年' in x and '月' in x and '日' in x:
        try:
            d = datetime.datetime.strptime(x, '%Y年%m月%d日')
            return d.strftime('%Y-%m-%d')
        except Exception:
            return fail_return

    # YYYY年MM月
    if '年' in x and '月' in x:
        try:
            d = datetime.datetime.strptime(x, '%Y年%m月')
            return d.strftime('%Y-%m')
        except Exception:
            return fail_return

    return fail_return

def extract_valid_id_numbers(all_text: str):
    """
    提取并验证合法的18位身份证号（含末位X）。
    返回 dict: {id: "1"}
    """
    id_pattern = r'\b([1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx])\b'
    raw_ids = re.findall(id_pattern, all_text or "")
    id_numbers = list({g[0].upper() for g in raw_ids})

    def check_id_valid(id_num: str) -> bool:
        if len(id_num) != 18:
            return False
        weights = [7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2]
        check_map = ['1','0','X','9','8','7','6','5','4','3','2']
        try:
            s = sum(int(n) * w for n, w in zip(id_num[:-1], weights))
        except ValueError:
            return False
        return id_num[-1] == check_map[s % 11]

    return {i: "1" for i in id_numbers if check_id_valid(i)}

def delete_path(path: Path):
    try:
        if path.exists():
            shutil.rmtree(path)
    except Exception:
        pass
