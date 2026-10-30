# 从正式整理稿生成演示价工作簿（非客户成本）。
# 规格单价表-演示 ← 规格单价表-原表整理；核算口径表-演示 ← 核算口径表。
# 模拟单价参考公开市场大致量级推演，仅供 POC。

import re
import shutil
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "数据"
SRC_UNIT = OUT / "规格单价表-原表整理.xlsx"
SRC_COST = OUT / "核算口径表.xlsx"
DST_UNIT = OUT / "规格单价表-演示.xlsx"
DST_COST = OUT / "核算口径表-演示.xlsx"

_FONT = Font(name="微软雅黑", size=10, color="0000FF")
_DEMO = PatternFill("solid", fgColor="FFF2CC")
_EDGE = Border(
    left=Side(style="thin", color="B0B0B0"),
    right=Side(style="thin", color="B0B0B0"),
    top=Side(style="thin", color="B0B0B0"),
    bottom=Side(style="thin", color="B0B0B0"),
)


def paint(cell, value):
    cell.value = value
    cell.font = _FONT
    cell.fill = _DEMO
    cell.border = _EDGE


# 灯珠：户外/交通屏批量量级约 0.02–0.15 元/颗（商城公开价区间推演）
LAMP = {
    "批次-510": {"R": 0.048, "G": 0.098, "B": 0.125},
    "批次-310": {"R": 0.045, "G": 0.092, "B": 0.118},
}

# 套件：底壳+面罩+胶圈；点间距越小结构件通常略贵
KIT = {
    10.416: (18.0, 1, 8.0, 3.0),
    15.625: (16.0, 1, 7.0, 2.5),
    20.833: (14.5, 1, 6.5, 2.5),
    25.0: (13.0, 1, 6.0, 2.2),
    31.25: (12.0, 1, 5.5, 2.0),
    33.33: (11.0, 1, 5.0, 2.0),
    10.0: (17.5, 1, 7.5, 2.8),
    16.0: (15.5, 1, 6.8, 2.5),
    20.0: (14.0, 1, 6.2, 2.4),
}


def kit_of(pitch, craft):
    base = KIT.get(round(float(pitch), 3)) or KIT.get(float(pitch))
    if not base:
        # 邻近点间距
        keys = sorted(KIT)
        near = min(keys, key=lambda k: abs(k - float(pitch)))
        base = KIT[near]
    shell, n, mask, ring = base
    if craft == "直插":
        shell += 1.5
        mask += 0.5
    return shell, n, mask, ring


def fee_of(pitch, chip, ratio):
    # 已有真实加工费的行不覆盖；空行按点间距与驱动粗估
    p = float(pitch)
    chip = str(chip or "")
    base = 55 + max(0, (33 - p)) * 2.2
    if "16289" in chip:
        base += 40
    elif "5124" in chip:
        base += 12
    elif "5034" in chip:
        base += 5
    if ratio and "B" in str(ratio):
        base += 6
    return round(base, 2)


def glue_of(pitch):
    p = float(pitch)
    if p <= 12:
        return 5.0
    if p <= 20:
        return 3.5
    if p <= 28:
        return 3.0
    return 2.5


def box_price(row):
    # 箱体：公开报价有「压铸铝箱约数百元/箱」「户外成品屏数千元/㎡」；此处只估箱体本体
    mat = str(row.get("材料") or "")
    place = str(row.get("安装位置") or "")
    seal = str(row.get("密封") or "")
    edge = str(row.get("包边") or "")
    w = float(row.get("宽_mm") or 1000) / 1000
    h = float(row.get("高_mm") or 1000) / 1000
    area = max(w * h, 0.5)
    unit = 780.0
    if "压铸铝" in mat:
        unit = 920.0
    elif "铁" in mat:
        unit = 680.0
    if place == "洞内":
        unit += 80
    if place == "门架":
        unit += 40
    if place == "悬臂":
        unit += 30
    if seal == "后开放":
        unit -= 40
    if edge == "含":
        unit += 110
    return round(unit * area, 2)


def bom_price(name):
    # 辅材：按名称关键词估批量含税价（元），螺钉参考电子商城批量量级
    t = str(name or "")
    if "总计" in t or "合计" in t or "平方" in t and "辅料" in t:
        return None
    if "包材总计" in t or "安装件总计" in t:
        return None
    if "接收卡" in t and "安装板" not in t:
        return 280.0
    if "点检" in t:
        return 95.0
    if "电源" in t and ("MRV" in t or "安装板" in t):
        return 18.0
    if "安装板" in t or "侧封" in t or "连接板" in t:
        return 22.0
    if "箱体" in t and ("压铸" in t or "钣金" in t or "CDKXB" in t):
        return 880.0
    if "木箱" in t:
        return 185.0
    if "纸箱" in t:
        return 28.0
    if "珍珠棉" in t:
        return 16.0
    if "铭牌" in t or "不干胶" in t or "标签" in t or "说明书" in t or "示意图" in t:
        return 1.2
    if "网线" in t:
        return 4.5 if "室外" in t or "屏蔽" in t else 2.8
    if "RVV" in t or "护套" in t or "电缆" in t or "软线" in t or "电线" in t:
        if "2.5" in t:
            return 6.5
        if "1.5" in t:
            return 4.2
        return 2.5
    if "电源线" in t or "排线" in t or "插座" in t:
        return 3.8
    if "接线排" in t:
        return 2.5
    if "端子" in t:
        return 0.28
    if "热缩" in t:
        return 0.35
    if "扎带" in t:
        return 0.08
    if "钥匙圈" in t or "吊环" in t:
        return 1.6
    if "过线圈" in t:
        return 1.1
    if "平垫" in t or "弹垫" in t:
        return 0.12
    if "螺母" in t:
        return 0.18
    if "螺钉" in t or "螺丝" in t or "螺栓" in t:
        if "M8" in t or "M12" in t:
            return 0.55
        if "M6" in t:
            return 0.32
        if "M4" in t:
            return 0.12
        if "M3" in t:
            return 0.08
        return 0.15
    if "模组" in t or "灯珠" in t:
        return None
    return 1.5


def mod_unit(pitch, ratio, fee, glue_face="单面"):
    # 收口表示意：单块模组含税价 ≈ 灯珠粗估 + 加工费 + 套件；贴近公开户外模组百元级
    p = float(pitch)
    shell, n, mask, ring = kit_of(p, "贴片")
    kit = shell + n * mask + ring
    bead = 25 + max(0, (33 - p)) * 1.8
    if ratio and "B" in str(ratio):
        bead += 8
    unit = bead + float(fee or fee_of(p, "", ratio)) + kit
    if glue_face == "双面":
        unit += glue_of(p)
    return round(unit, 2)


def seed_unit():
    if not SRC_UNIT.exists():
        raise SystemExit(f"缺少 {SRC_UNIT}")
    shutil.copy(SRC_UNIT, DST_UNIT)
    wb = load_workbook(DST_UNIT)
    tip = wb["说明"]
    tip["A15"] = (
        "【演示副本】本文件由规格单价表-原表整理复制并填入模拟单价，仅供 POC。"
        "灯珠/套件/加工费/箱体参考公开市场大致量级推演，不是创迪采购价。黄色单元格为演示填入。"
    )

    lamp = wb["灯珠单价"]
    for r in range(5, (lamp.max_row or 5) + 1):
        batch = lamp.cell(r, 1).value
        if batch not in LAMP:
            continue
        prices = LAMP[batch]
        paint(lamp.cell(r, 2), prices["R"])
        paint(lamp.cell(r, 3), prices["G"])
        paint(lamp.cell(r, 4), prices["B"])
        paint(lamp.cell(r, 5), "演示价·灯珠")

    kit = wb["套件单价"]
    for r in range(5, (kit.max_row or 5) + 1):
        pitch = kit.cell(r, 1).value
        if pitch in (None, ""):
            continue
        craft = kit.cell(r, 2).value or "贴片"
        if kit.cell(r, 2).value in (None, ""):
            paint(kit.cell(r, 2), "贴片")
            craft = "贴片"
        shell, n, mask, ring = kit_of(pitch, craft)
        paint(kit.cell(r, 3), shell)
        paint(kit.cell(r, 4), n)
        paint(kit.cell(r, 5), mask)
        paint(kit.cell(r, 6), ring)
        paint(kit.cell(r, 8), "演示价·套件")

    mod = wb["模组价格"]
    heads = [c.value for c in next(mod.iter_rows(min_row=4, max_row=4))]
    fee_i = heads.index("加工费") + 1
    glue_i = heads.index("灌胶加价") + 1
    # 原表前段行把 R/G/B 单价列设成了「0;-0;""」，0.048 会被显示成整数 0；统一用三位小数
    price_cols = [
        heads.index(h) + 1
        for h in ("R单价", "G单价", "B单价", "灯珠合计", "加工费", "套件单价", "灌胶加价", "含税单价_单面", "含税单价_双面")
        if h in heads
    ]
    for r in range(5, (mod.max_row or 5) + 1):
        pitch = mod.cell(r, 2).value
        if pitch in (None, ""):
            continue
        for c in price_cols:
            cell = mod.cell(r, c)
            if type(cell).__name__ != "MergedCell":
                cell.number_format = "0.000"
        ratio = mod.cell(r, 3).value
        chip = mod.cell(r, 5).value
        fee_cell = mod.cell(r, fee_i)
        glue_cell = mod.cell(r, glue_i)
        # 合并单元格不可写；跳过
        if type(fee_cell).__name__ == "MergedCell":
            continue
        if fee_cell.value in (None, ""):
            paint(fee_cell, fee_of(pitch, chip, ratio))
        if type(glue_cell).__name__ != "MergedCell" and glue_cell.value in (None, ""):
            paint(glue_cell, glue_of(pitch))

    box = wb["箱体单价"]
    for r in range(5, (box.max_row or 5) + 1):
        name = box.cell(r, 1).value
        if not name:
            continue
        row = {
            "材料": box.cell(r, 2).value,
            "安装位置": box.cell(r, 3).value,
            "宽_mm": box.cell(r, 4).value,
            "高_mm": box.cell(r, 5).value,
            "密封": box.cell(r, 6).value,
            "包边": box.cell(r, 7).value,
        }
        paint(box.cell(r, 8), box_price(row))
        paint(box.cell(r, 9), "演示价·箱体")

    tpl = wb["核算模板"]
    # 两行默认选型，覆盖样例招标常见点间距
    demos = [
        ("悬臂式", 25.0, 250, 250, "2R1G", "5034B", "双面", "批次-310", "贴片", "悬臂铁箱体-全密封-含", 1, 1, None, "是", "否", "否", "否"),
        ("门架式", 31.25, 250, 250, "2R1G", "5034B", "双面", "批次-310", "贴片", "门架铁箱体-全密封-含", 1, 1, None, "是", "否", "否", "否"),
    ]
    for i, vals in enumerate(demos):
        r = 5 + i
        for c, v in enumerate(vals, start=1):
            if v is None:
                continue
            paint(tpl.cell(r, c), v)
        # 每平方米辅料：演示占位，正式应以 BOM 汇总为准；这里填示意 35 元/㎡ 量级
        paint(tpl.cell(r, 13), 35)
        paint(tpl.cell(r, 20), "演示选型·辅料示意须与 BOM 核对")

    wb.save(DST_UNIT)
    return DST_UNIT


def seed_cost():
    if not SRC_COST.exists():
        raise SystemExit(f"缺少 {SRC_COST}，请先运行整理原表.py")
    shutil.copy(SRC_COST, DST_COST)
    wb = load_workbook(DST_COST)
    tip = wb["说明"]
    tip["A8"] = (
        "【演示副本】已为辅材 BOM 空单价与每平米收口大件单价列填入模拟数（黄底）。"
        "正式稿大件单价仍应留空、取自规格单价表。本文件不是创迪成本。"
    )

    for sheet, price_col in (("压铸铝辅材", 4), ("铁箱辅材", 4)):
        ws = wb[sheet]
        for r in range(2, (ws.max_row or 2) + 1):
            name = ws.cell(r, 3).value
            if not name:
                continue
            cur = ws.cell(r, price_col).value
            if isinstance(cur, (int, float)):
                continue
            if isinstance(cur, str) and cur.startswith("="):
                continue
            price = bom_price(name)
            if price is None:
                continue
            paint(ws.cell(r, price_col), price)

    sqm = wb["每平米收口"]
    pitch = None
    for r in range(1, (sqm.max_row or 1) + 1):
        a = sqm.cell(r, 1).value
        title = str(a or "")
        found = re.search(r"P([\d.]+)", title)
        if found:
            pitch = float(found.group(1))
            continue
        if not a or not re.match(r"^\d", str(a)):
            continue
        material = str(sqm.cell(r, 2).value or "")
        beads = str(sqm.cell(r, 4).value or "")
        ratio = beads.split("/")[-1].strip() if beads else ""
        # 模组单价
        if sqm.cell(r, 6).value in (None, ""):
            paint(sqm.cell(r, 6), mod_unit(pitch or 25, ratio, None))
        # 箱体单价：压铸铝 / 铁箱
        if sqm.cell(r, 8).value in (None, ""):
            cab = 990.0 if "压铸铝" in material else 760.0 if material else None
            # 同行继承上一材料
            if cab is None:
                # 向上找材料
                for up in range(r - 1, 0, -1):
                    m = str(sqm.cell(up, 2).value or "")
                    if "压铸铝" in m:
                        cab = 990.0
                        break
                    if "镀锌" in m or "铁" in m:
                        cab = 760.0
                        break
            if cab is not None:
                paint(sqm.cell(r, 8), cab)
        # 电源单价：5V200W 公开约 65 元级
        if sqm.cell(r, 10).value in (None, ""):
            paint(sqm.cell(r, 10), 72.0)
        note = sqm.cell(r, 17).value
        mark = "演示价·大件示意"
        paint(sqm.cell(r, 17), f"{note}；{mark}" if note else mark)

    wb.save(DST_COST)
    return DST_COST


def main():
    OUT.mkdir(exist_ok=True)
    u = seed_unit()
    c = seed_cost()
    print(u)
    print(c)


if __name__ == "__main__":
    main()
