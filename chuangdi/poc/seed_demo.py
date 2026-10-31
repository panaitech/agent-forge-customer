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
    # 灯珠/模组本体价在规格单价表；铁箱整屏 BOM 里若填演示价会把 1㎡ 辅料撑爆
    if "模组" in t or "灯珠" in t or "发光二极管" in t:
        return None
    if "面罩" in t or "底壳" in t:
        return None
    # 控制箱 BOM 常见件
    if "控制箱" in t and ("裸机" in t or "箱体" in t or "标志" in t):
        return 680.0
    if "多媒体" in t or "播放盒" in t or "控制卡" in t:
        return 420.0
    if "防雷" in t:
        return 85.0
    if "空开" in t or "断路" in t:
        return 28.0
    if "光探" in t:
        return 95.0
    if "开关电源" in t or "LM25" in t:
        return 45.0
    if "波纹管" in t:
        return 12.0
    if "几字连接" in t or "背抱" in t:
        return 38.0
    return 1.5


def seed_ctrl(wb):
    # 控制箱：含税单价空则填演示价；行合计 = 单价×数量；末行总计滚出
    ws = wb["控制箱"]
    total = 0.0
    last = None
    for r in range(2, (ws.max_row or 2) + 1):
        name = ws.cell(r, 3).value
        if not name:
            continue
        title = str(name)
        if "总计" in title:
            last = r
            continue
        price = ws.cell(r, 4).value
        if _empty_or_fx(price):
            p = bom_price(title)
            if p is None:
                p = 1.5
            paint(ws.cell(r, 4), p)
            price = p
        qty = _num(ws.cell(r, 6).value)
        if qty is None:
            qty = 1.0
            paint(ws.cell(r, 6), qty)
        unit = _num(price)
        if unit is None:
            continue
        line = round(unit * qty, 2)
        if _empty_or_fx(ws.cell(r, 5).value):
            paint(ws.cell(r, 5), line)
        total += line
    if last is not None:
        paint(ws.cell(last, 5), round(total, 2))
        note = ws.cell(last, 3).value
        # 原表行名常含「10平方」；演示明确按「每套控制系统」取该合计，不按面积折算
        if note and "演示" not in str(note):
            paint(
                ws.cell(last, 3),
                f"{note}（演示汇总·按每套控制系统取用，不按10㎡折算）",
            )


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
    # 已有行：(点间距, 工艺) → 行号；空行留给补缺
    have = {}
    blank = []
    for r in range(5, (kit.max_row or 5) + 1):
        pitch = kit.cell(r, 1).value
        if pitch in (None, ""):
            blank.append(r)
            continue
        craft = kit.cell(r, 2).value or "贴片"
        if kit.cell(r, 2).value in (None, ""):
            paint(kit.cell(r, 2), "贴片")
            craft = "贴片"
        have[(round(float(pitch), 3), str(craft))] = r

    # 模组表出现的点间距 + KIT 字典：演示稿套件须覆盖，避免下游取模组时套件无对应行
    mod = wb["模组价格"]
    need = set(round(float(k), 3) for k in KIT)
    for r in range(5, (mod.max_row or 5) + 1):
        pitch = mod.cell(r, 2).value
        if pitch in (None, ""):
            continue
        need.add(round(float(pitch), 3))

    def kit_formula(row):
        return f'=IF(A{row}="","",C{row}+D{row}*E{row}+F{row})'

    def fill_kit(row, pitch, craft):
        shell, n, mask, ring = kit_of(pitch, craft)
        paint(kit.cell(row, 1), pitch)
        paint(kit.cell(row, 2), craft)
        paint(kit.cell(row, 3), shell)
        paint(kit.cell(row, 4), n)
        paint(kit.cell(row, 5), mask)
        paint(kit.cell(row, 6), ring)
        kit.cell(row, 7).value = kit_formula(row)
        paint(kit.cell(row, 8), "演示价·套件")

    for key, row in list(have.items()):
        fill_kit(row, key[0], key[1])

    # 缺档补「贴片」；10.416 原表已有直插则保留，其它点间距演示只补贴片一行
    for pitch in sorted(need):
        key = (pitch, "贴片")
        if key in have:
            continue
        if blank:
            row = blank.pop(0)
        else:
            row = (kit.max_row or 4) + 1
        fill_kit(row, pitch, "贴片")
        have[key] = row

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


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def roll_aluminum(ws):
    """演示稿：把压铸铝 BOM 行合计与汇总格滚成可读数值（原表公式无 Excel 缓存时 Agent 读到空）。"""
    for r in range(2, (ws.max_row or 2) + 1):
        d = _num(ws.cell(r, 4).value)
        e = _num(ws.cell(r, 5).value)
        f = ws.cell(r, 6).value
        # 包材两行原表缺实际数量：演示默认 1，否则 F60 滚不出
        if r in (58, 59) and d is not None and e is None:
            paint(ws.cell(r, 5), 1)
            e = 1.0
        if d is None or e is None:
            continue
        if isinstance(f, str) and f.startswith("=") and "SUM" not in f.upper():
            paint(ws.cell(r, 6), round(d * e, 4))
        elif f in (None, ""):
            paint(ws.cell(r, 6), round(d * e, 4))
    paint(ws.cell(56, 6), round(sum(_num(ws.cell(r, 6).value) or 0 for r in range(9, 56)), 4))
    paint(
        ws.cell(60, 6),
        round((_num(ws.cell(58, 6).value) or 0) + (_num(ws.cell(59, 6).value) or 0) + 6, 4),
    )
    # 10㎡ 共用段原表缺用量时 E80=0；有用量则按公式折 1㎡
    s10 = sum(_num(ws.cell(r, 5).value) or 0 for r in range(63, 79))
    paint(ws.cell(79, 5), round(s10, 4))
    paint(ws.cell(80, 5), round(s10 / 10, 4))


def roll_iron(ws):
    """演示稿：铁箱先填价税合计=含税单价×实际数量，再滚 1㎡ 辅料/包材。"""
    for r in range(2, (ws.max_row or 2) + 1):
        cur = ws.cell(r, 5).value
        if isinstance(cur, str) and cur.startswith("="):
            continue
        d = _num(ws.cell(r, 4).value)
        qty = _num(ws.cell(r, 7).value)
        if qty is None:
            qty = _num(ws.cell(r, 6).value)
        if d is None or qty is None:
            continue
        paint(ws.cell(r, 5), round(d * qty, 4))
    paint(ws.cell(57, 5), round(sum(_num(ws.cell(r, 5).value) or 0 for r in range(7, 57)), 4))
    paint(ws.cell(58, 5), round((_num(ws.cell(57, 5).value) or 0) / 10, 4))
    paint(ws.cell(62, 5), round(sum(_num(ws.cell(r, 5).value) or 0 for r in range(60, 62)), 4))
    paint(ws.cell(63, 5), round((_num(ws.cell(62, 5).value) or 0) / 10 + 2, 4))
    if _num(ws.cell(4, 5).value) is not None:
        paint(ws.cell(5, 5), round((_num(ws.cell(4, 5).value) or 0) / 10, 4))
    paint(ws.cell(73, 5), round(sum(_num(ws.cell(r, 5).value) or 0 for r in range(65, 73)), 4))
    paint(ws.cell(74, 5), round((_num(ws.cell(73, 5).value) or 0) / 10 + 5, 4))


def roll_sqm(ws, al, fe):
    """把每平米收口里引用 BOM 的辅材/包材公式写成滚出数值，便于 Agent 直接读。"""
    al_pack = _num(al["F60"].value) or 0
    al_aux = (_num(al["F56"].value) or 0) + (_num(al["E80"].value) or 0) + 20
    fe_pack = _num(fe["E63"].value) or 0
    fe_aux = (_num(fe["E58"].value) or 0) + 20
    for r in range(2, (ws.max_row or 2) + 1):
        n = ws.cell(r, 14).value
        o = ws.cell(r, 15).value
        if not (isinstance(n, str) and n.startswith("=")):
            continue
        if "压铸铝" in n or "压铸铝" in str(o or ""):
            paint(ws.cell(r, 14), round(al_pack, 4))
            paint(ws.cell(r, 15), round(al_aux, 4))
        elif "铁箱" in n or "铁箱" in str(o or ""):
            paint(ws.cell(r, 14), round(fe_pack, 4))
            paint(ws.cell(r, 15), round(fe_aux, 4))


def _empty_or_fx(v):
    if v in (None, ""):
        return True
    if isinstance(v, str) and v.startswith("="):
        return True
    if isinstance(v, (int, float)) and v == 0:
        return True
    return False


def seed_price_sheets(wb):
    # 箱体：综合单价列多为公式；填箱体单价/配件后由公式加总。无公式则直接填综合。
    box = wb["箱体"]
    for r in range(3, (box.max_row or 3) + 1):
        name = box.cell(r, 2).value
        if not name:
            continue
        mat = str(name)
        base = 880.0 if "压铸" in mat else 720.0
        if "含包边" in str(box.cell(r, 8).value or ""):
            base += 110
        if _empty_or_fx(box.cell(r, 5).value):
            paint(box.cell(r, 5), base)
        if _empty_or_fx(box.cell(r, 6).value):
            paint(box.cell(r, 6), 40.0)
        # 综合单价：演示写成可读数，避免 Agent 读到未计算的公式
        paint(box.cell(r, 7), round(float(box.cell(r, 5).value) + float(box.cell(r, 6).value), 2))

    psu = wb["电源"]
    # 演示：按功率粗分档
    for r in range(3, (psu.max_row or 3) + 1):
        spec = str(psu.cell(r, 2).value or "")
        if not spec:
            continue
        if not _empty_or_fx(psu.cell(r, 7).value):
            continue
        price = 48.0
        if "300W" in spec:
            price = 95.0
        elif "200W" in spec:
            price = 72.0
        elif "175W" in spec:
            price = 68.0
        elif "110W" in spec:
            price = 55.0
        elif "100W" in spec:
            price = 48.0
        paint(psu.cell(r, 7), price)

    br = wb["支架"]
    for r in range(3, (br.max_row or 3) + 1):
        name = br.cell(r, 2).value
        if not name:
            continue
        e, f = br.cell(r, 5).value, br.cell(r, 6).value
        if _empty_or_fx(e) and not (isinstance(e, str) and e.startswith("=") and "!" not in e):
            # 无支架本体价时给示意；已有非零价保留
            if not isinstance(e, (int, float)) or e == 0:
                paint(br.cell(r, 5), 200.0)
                e = 200.0
        if isinstance(f, str) and f.startswith("="):
            # 螺钉配件引用抱箍表：演示填示意数便于加总
            paint(br.cell(r, 6), 30.0)
            f = 30.0
        elif _empty_or_fx(f):
            paint(br.cell(r, 6), 30.0)
            f = 30.0
        if isinstance(e, (int, float)) and isinstance(f, (int, float)):
            paint(br.cell(r, 7), round(e + f, 2))

    hoop = wb["安装抱箍和螺钉"]
    for r in range(3, (hoop.max_row or 3) + 1):
        if not hoop.cell(r, 2).value:
            continue
        # 单价列 D=4, G=7, J=10；空则填示意
        for c, p in ((4, 25.0), (7, 35.0), (10, 8.0)):
            if _empty_or_fx(hoop.cell(r, c).value):
                paint(hoop.cell(r, c), p)
        # 合计列示意滚出，便于读
        c_qty = _num(hoop.cell(r, 3).value) or 1
        f_qty = _num(hoop.cell(r, 6).value) or 1
        i_qty = _num(hoop.cell(r, 9).value) or 1
        paint(hoop.cell(r, 5), round(c_qty * float(hoop.cell(r, 4).value), 2))
        paint(hoop.cell(r, 8), round(f_qty * float(hoop.cell(r, 7).value), 2))
        paint(hoop.cell(r, 11), round(i_qty * float(hoop.cell(r, 10).value), 2))
        paint(
            hoop.cell(r, 12),
            round(
                float(hoop.cell(r, 5).value)
                + float(hoop.cell(r, 8).value)
                + float(hoop.cell(r, 11).value),
                2,
            ),
        )


def seed_cost():
    if not SRC_COST.exists():
        raise SystemExit(f"缺少 {SRC_COST}，请先运行整理原表.py")
    shutil.copy(SRC_COST, DST_COST)
    wb = load_workbook(DST_COST)
    tip = wb["说明"]
    tip["A8"] = (
        "【演示副本】辅材 BOM、箱体/电源/支架/抱箍/控制箱价目已填模拟单价（黄底）并滚出可读汇总。"
        "「常规电源数量」等为演示维护示意，供 POC 重算本项目收口；不是未确认的正式成本定额。"
        "本文件不是创迪采购价。正式稿单价由成本维护；项目报价按招标+规格重算，非样例×面积。"
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

    seed_price_sheets(wb)
    seed_ctrl(wb)

    al = wb["压铸铝辅材"]
    fe = wb["铁箱辅材"]
    roll_aluminum(al)
    roll_iron(fe)

    box = wb["箱体"]
    # 价目行综合单价：压铸铝 / 镀锌含包边 / 镀锌不含包边
    cab_cast = _num(box.cell(3, 7).value) or 920.0
    cab_fe_edge = _num(box.cell(5, 7).value) or 830.0
    cab_fe = _num(box.cell(4, 7).value) or 760.0
    psu_price = _num(wb["电源"].cell(11, 7).value) or 72.0

    sqm = wb["每平米收口"]
    pitch = None
    last_mat = ""
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
        if material.strip():
            last_mat = material
        beads = str(sqm.cell(r, 4).value or "")
        ratio = beads.split("/")[-1].strip() if beads else ""
        # 模组单价：演示示意（正式取规格表）；Agent 可读
        if _empty_or_fx(sqm.cell(r, 6).value):
            paint(sqm.cell(r, 6), mod_unit(pitch or 25, ratio, None))
        # 箱体单价：写入价目综合单价示意（覆盖未计算的引用公式）
        mat = last_mat
        if "压铸铝" in mat:
            cab = cab_cast
        elif "含包边" in mat:
            cab = cab_fe_edge
        else:
            cab = cab_fe
        if _empty_or_fx(sqm.cell(r, 8).value):
            paint(sqm.cell(r, 8), cab)
        # 电源单价
        if _empty_or_fx(sqm.cell(r, 10).value):
            paint(sqm.cell(r, 10), psu_price)
        # 电源合计 = 单价 × 常规电源数量（演示可读）
        qty = _num(sqm.cell(r, 9).value)
        unit = _num(sqm.cell(r, 10).value)
        if qty is not None and unit is not None and _empty_or_fx(sqm.cell(r, 11).value):
            paint(sqm.cell(r, 11), round(qty * unit, 2))
        # 模组合计
        n_mod = _num(sqm.cell(r, 5).value)
        u_mod = _num(sqm.cell(r, 6).value)
        if n_mod is not None and u_mod is not None and _empty_or_fx(sqm.cell(r, 7).value):
            paint(sqm.cell(r, 7), round(n_mod * u_mod, 2))
        note = sqm.cell(r, 17).value
        mark = "演示价·收口示意（电源只数为演示维护值）"
        paint(sqm.cell(r, 17), f"{note}；{mark}" if note else mark)

    roll_sqm(sqm, al, fe)
    # 总计示意：有分项则相加
    for r in range(2, (sqm.max_row or 2) + 1):
        if not sqm.cell(r, 1).value or not re.match(r"^\d", str(sqm.cell(r, 1).value)):
            continue
        parts = [_num(sqm.cell(r, c).value) for c in (7, 8, 11, 12, 13, 14, 15)]
        if any(p is not None for p in parts) and _empty_or_fx(sqm.cell(r, 16).value):
            paint(sqm.cell(r, 16), round(sum(p or 0 for p in parts), 2))

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
