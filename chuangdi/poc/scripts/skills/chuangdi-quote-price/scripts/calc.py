# =============================================================================
# 创迪情报板计价脚本（专用计算器）
# =============================================================================
# 【职责】这是整条报价链上「唯一」的计算权威：
#   大模型（计价员）只负责「选」——从招标书和价目表判断每条屏的形态、尺寸、
#   选哪一行单价、钢构归谁；本脚本只负责「算」——把模型选好的参数算成金额。
#   两者边界：模型不产出任何数字，脚本不读取任何文件、不做任何业务判断。
#
# 【输入来源】stdin 读入一份 lines.json（由计价员从 01-解析 / 02-复核 / 03-读表
#   提炼而成）。不是脚本自己去读 Excel/PDF。
#
# 【粒度约定】lines[] 每一行 = 一套（单套/单块）。
#   面积由本脚本按 长×高×屏数 自行算出，模型「禁止」手填 area，
#   从根上避免「整行面积合计」被下游再乘一次数量导致的重复计价。
#
# 【输出去向】stdout 打印三张 Markdown 表（分项收口 / 综合价链 / 三档总价），
#   计价员原样抄进 04-计价.md，报价单员再原样抄进 报价单.md，全程禁止改数。
#
# 【业务公式来源】创迪《原表公式与经验配量确认.md》+《场景演示建议口径.md》：
#   形态→支架/线材/接收卡/控制系统公式、写死常数 69/750/1.03/0.68/2980 等。
# =============================================================================
"""从 stdin 读 JSON，向 stdout 写计价表。"""

import json
import math
import sys

# -----------------------------------------------------------------------------
# 形态 → 支架算法类别映射。
# 创迪确认稿「安装形态 → 数量写法」把 10 种安装形态归成 4 类：
#   len2   : 数量 = 长 + 2（天棚、门架）
#   box    : 数量 = 长 × 高（悬臂、车道、服务区）
#   tunnel : 数量 = (长 ÷ 2 + 1) × 1（洞内屏）
#   small  : 数量 = 长 + 1（小型情报板）
# 双幅不乘屏数，长和高永远用「单幅」。
# -----------------------------------------------------------------------------
KIND = {
    "天棚屏": "len2",
    "门架1米": "len2",
    "门架1.5-2米": "len2",
    "悬臂": "box",
    "车道屏1米": "box",
    "车道屏1×2米": "box",
    "车道屏2×2米": "box",
    "服务区": "box",
    "洞内屏": "tunnel",
    "小型情报板": "small",
}


def down(n):
    """向下取整。带 1e-9 容差，避免浮点误差把 2.0 算成 1。"""
    return math.floor(n + 1e-9)


def money(n):
    """金额统一保留两位小数。带 1e-9 容差吸收浮点误差。"""
    return round(n + 1e-9, 2)


def bracket(form, length, height):
    """支架数量（每套，按单幅长高代入形态公式）。"""
    kind = KIND[form]
    if kind == "len2":
        return length + 2
    if kind == "box":
        return length * height
    if kind == "tunnel":
        return length / 2 + 1
    return length + 1  # small


def cable(form, length, height):
    """大屏线材费用（每套，整屏费用，非每㎡）。

    只有部分形态有线材经验式，其余返回 None 表示「该形态无线材」。
    经验式出现负值时按 0（短跨没有超长段，不计线材）。
    """
    if form in ("天棚屏", "门架1米"):
        v = (length - 10) * 100
    elif form == "门架1.5-2米":
        v = (length - 10) * 150 * height + (height - 1) * 300
    elif form == "服务区":
        v = length * height * 50
    else:
        return None
    return max(0.0, v)


def cards(form, length, height):
    """接收卡数量（每套，按单幅长高）。"""
    if form in ("天棚屏", "悬臂", "门架1米", "门架1.5-2米", "服务区"):
        return down((length / 2) * height)
    if form == "小型情报板":
        return 1
    return down(height)


def control(form, length, height, base):
    """控制系统金额（每套）。

    多数形态直接用控制箱汇总作底数；仅门架1.5-2米、服务区两种形态
    按米数加价（加价是「每套底数上加减」，不是按面积折算）。
    """
    extra = 0
    if form == "门架1.5-2米":
        extra = (height - 1) * 100 + (length - 5) * 100
    elif form == "服务区":
        extra = (height - 1) * 300 + (length - 5) * 200
    return base + extra


def per_sq(ready, rows, div, plus):
    """辅材/包材「元/㎡」汇总。

    有现成汇总格（ready 非空）就直接用；为空才按明细滚：
      元/㎡ = Σ(明细 单价×数量) ÷ div + 常数
    """
    if ready is not None:
        return float(ready)
    raw = sum(float(row["price"]) * float(row["qty"]) for row in rows)
    return raw / div + plus


def num(row, key):
    """读取可空数字字段。None 返回 None，用于「待确认 / 无价目」。"""
    v = row.get(key)
    return None if v is None else float(v)


def one(row, base, chain):
    """算一条屏（单套）。所有数量与金额均为「单套」口径。

    处理顺序（对应创迪收口七项 + 形态/钢构/价链前置项）：
      1. 校验形态 → 拆形状 → 面积 = 长×高×屏数
      2. 模组块数 = 面积 ÷ 单块面积（向下取整）
      3. 箱体 / 电源 / 辅材 / 包材（每㎡类成本 × 面积）
      4. 支架（只有交安已供整套钢构才为 0，否则按形态公式）
      5. 抱箍（每套 1 只，交安已供/清单写含抱箍钢构/无价目为 0）
      6. 线材、接收卡（永远按形态公式，不随钢构清零）
      7. 控制系统（每套底数 + 形态加价）
      8. 屏体合计 = 模组+箱体+电源+辅材+包材（每㎡项）+ 线材（整屏项）
    """
    form = row["form"]
    if form not in KIND:
        raise SystemExit(f"形态不在表内：{form}")
    length = float(row["length"])
    height = float(row["height"])
    panels = float(row.get("panels") or 1)
    qty = int(row["qty"])
    area = length * height * panels  # 面积由脚本算，杜绝整行/单套歧义
    side = row.get("side") or "单面"

    # 电源：无维护值按 2 只/㎡（创迪演示默认口径）
    power_each = row.get("power_per_m2")
    power_note = "03维护值"
    if power_each is None:
        power_each = 2
        power_note = "该点距无维护值，按2只/㎡"

    # 模组：块数按 面积÷单块面积 向下取整；单价空则金额留「待确认」
    block_area = (float(row["module_w_mm"]) / 1000) * (float(row["module_h_mm"]) / 1000)
    blocks = down(area / block_area) if block_area else 0
    module_price = num(row, "module_price")
    module_amt = blocks * module_price if module_price is not None else None

    box_amt = float(row["box_per_m2"]) * area
    power_n = down(float(power_each) * area)
    power_amt = power_n * float(row["power_price"])
    aux = per_sq(row.get("aux_per_m2"), row.get("aux_lines") or [], float(row.get("aux_div") or 1), float(row.get("aux_plus") or 0))
    pack = per_sq(row.get("pack_per_m2"), row.get("pack_lines") or [], float(row.get("pack_div") or 1), float(row.get("pack_plus") or 0))
    aux_amt = aux * area
    pack_amt = pack * area

    # 支架：交安已供整套钢构（steel=provided）才为 0；否则按形态公式算数量。
    #       含立柱/含支座/附着既有（body 字段）只进「未计入钢构」备注，不清支架。
    #       单价空则数量照算、金额留「待确认」。
    steel = row.get("steel") or "self"
    bracket_price = num(row, "bracket_price")
    if steel == "provided":
        brackets = 0
        bracket_amt = 0.0
    elif bracket_price is None:
        brackets = down(bracket(form, length, height))
        bracket_amt = None
    else:
        brackets = down(bracket(form, length, height))
        bracket_amt = brackets * bracket_price

    # 抱箍：每套 1 只（不乘块数、不乘面积）。
    #       交安已供或清单写「含连接抱箍钢结构」（hoop=provided）或无价目 → 0。
    hoop = row.get("hoop") or "self"
    hoop_price = num(row, "hoop_price")
    if steel == "provided" or hoop == "provided" or hoop_price is None:
        hoops = 0
        hoop_amt = 0.0
    else:
        hoops = 1
        hoop_amt = hoops * hoop_price

    # 线材、接收卡永远按形态公式算，不随钢构归属清零（这是上次修的核心点之一）
    wire = cable(form, length, height)
    card_n = cards(form, length, height)

    ctrl = control(form, length, height, base)

    # 组装备注（写到 04，供下游与主管审计）
    notes = []
    if panels > 1:
        notes.append("屏数已计入面积，数量按单幅公式")
    if side == "单面" and not row.get("side_given"):
        notes.append("清单未写面别，按单面")
    notes.append(power_note)
    if steel == "provided":
        notes.append("交安已供钢构，支架与抱箍未计")
    elif row.get("body"):
        notes.append(f"未计入钢构：{row['body']}")
    if module_price is None:
        notes.append("模组单价待确认")

    # 屏体小计 = 模组+箱体+电源+辅材+包材（每㎡类成本 × 面积）
    screen = (module_amt if module_amt is not None else 0) + box_amt + power_amt + aux_amt + pack_amt
    # 平方单价 = 屏体小计 ÷ 面积
    sq_price = screen / area if area else 0
    # 屏体合计 = 屏体小计 + 大屏线材费用（线材是整屏费用，非每㎡）
    screen_total = screen + (wire or 0)

    return {
        "seq": row["seq"],
        "name": row.get("name") or row["seq"],
        "qty": qty,
        "unit": row.get("unit") or "套",
        "length": length,
        "height": height,
        "area": area,
        "blocks": blocks,
        "module_amt": None if module_amt is None else money(module_amt),
        "box_amt": money(box_amt),
        "power_n": power_n,
        "power_amt": money(power_amt),
        "aux": money(aux),
        "aux_amt": money(aux_amt),
        "pack": money(pack),
        "pack_amt": money(pack_amt),
        "sq_price": money(sq_price),
        "wire": None if wire is None else (None if wire == 0 else money(wire)),
        "screen_total": money(screen_total),
        "brackets": brackets,
        "bracket_price": bracket_price,
        "bracket_amt": None if bracket_amt is None else money(bracket_amt),
        "hoops": hoops,
        "hoop_price": hoop_price,
        "hoop_amt": money(hoop_amt),
        "cards": card_n,
        "ctrl": money(ctrl),
        "notes": "；".join(notes),
    }


def fmt(n):
    """None 显示为「待确认」，数字显示为两位小数。"""
    return "待确认" if n is None else f"{n:.2f}"


def chain_row(r, chain):
    """算一条的综合价链（单套）。

    创迪价链：
      基础合计 = 屏体合计 + 支架 + 抱箍 + 控制系统 + 普通接收卡(数量×69)
      普通综合价格   = 基础合计 × 1.03
      含点检综合价格 = (屏体+支架+抱箍+控制+ 点检接收卡 数量×750) × 1.03
      含工控机和点检 = (基础合计 + 工控机 2980) × 1.03
      三档综合报价   = 对应综合价格 ÷ 0.68
    """
    coef = chain["coef"]
    div = chain["div"]
    card_n = chain["card_n"]
    card_d = chain["card_d"]
    ipc = chain["ipc"]
    screen = r["screen_total"]
    bracket = r["bracket_amt"] or 0
    hoop = r["hoop_amt"]
    ctrl = r["ctrl"]
    card = r["cards"]
    normal_card = card * card_n
    check_card = card * card_d
    base = screen + bracket + hoop + ctrl + normal_card
    normal = base * coef
    with_check = (screen + bracket + hoop + ctrl + check_card) * coef
    with_ipc = (base + ipc) * coef
    return {
        "ipc_cost": money(ipc),
        "normal_card": money(normal_card),
        "check_card": money(check_card),
        "base": money(base),
        "normal_price": money(normal),
        "check_price": money(with_check),
        "ipc_price": money(with_ipc),
        "normal": money(normal / div),
        "check": money(with_check / div),
        "ipc": money(with_ipc / div),
    }


def main():
    """入口：读 stdin JSON → 逐条算 → 打印三张 Markdown 表。"""
    data = json.load(sys.stdin)
    base = float(data["control_base"])
    # 写死常数默认值；lines.json 里带 chain 则覆盖
    chain = data.get("chain") or {"coef": 1.03, "div": 0.68, "card_n": 69, "card_d": 750, "ipc": 2980}
    rows = [one(row, base, chain) for row in data["lines"]]

    # 表一：分项收口（单套）
    print("## 一、分项收口（单套）")
    print()
    print("| 序号 | 数量 | 长 | 高 | 面积 | 模组块数 | 模组金额 | 箱体金额 | 电源只数 | 电源金额 | 辅材元/㎡ | 辅材金额 | 包材元/㎡ | 包材金额 | 平方单价 | 大屏线材费用 | 屏体合计 | 支架数量 | 支架单价 | 支架合计 | 抱箍数量 | 抱箍单价 | 抱箍合计 | 控制系统 | 接收卡数量 | 备注 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        wire = "" if r["wire"] is None else r["wire"]
        bracket_price = fmt(r["bracket_price"])
        hoop_price = "" if r["hoop_price"] is None else f"{r['hoop_price']:.2f}"
        print(f"| {r['seq']} | {r['qty']} | {r['length']} | {r['height']} | {r['area']:.4f} | {r['blocks']} | {fmt(r['module_amt'])} | {r['box_amt']:.2f} | {r['power_n']} | {r['power_amt']:.2f} | {r['aux']:.2f} | {r['aux_amt']:.2f} | {r['pack']:.2f} | {r['pack_amt']:.2f} | {r['sq_price']:.2f} | {wire} | {r['screen_total']:.2f} | {r['brackets']} | {bracket_price} | {fmt(r['bracket_amt'])} | {r['hoops']} | {hoop_price} | {r['hoop_amt']:.2f} | {r['ctrl']:.2f} | {r['cards']} | {r['notes']} |")
    print()

    # 表二：综合价链与三档报价（单套）
    print("## 二、综合价链与三档报价（单套）")
    print()
    print("| 序号 | 数量 | 工控机 | 普通接收卡合计 | 点检接收卡合计 | 基础合计 | 普通综合价格 | 含点检综合价格 | 含工控机和点检综合价格 | 普通综合报价 | 含点检综合报价 | 含工控机和点检综合报价 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    totals = [0.0, 0.0, 0.0]
    for r in rows:
        c = chain_row(r, chain)
        row_t = [c["normal"] * r["qty"], c["check"] * r["qty"], c["ipc"] * r["qty"]]
        for i in range(3):
            totals[i] += row_t[i]
        print(f"| {r['seq']} | {r['qty']} | {c['ipc_cost']:.2f} | {c['normal_card']:.2f} | {c['check_card']:.2f} | {c['base']:.2f} | {c['normal_price']:.2f} | {c['check_price']:.2f} | {c['ipc_price']:.2f} | {c['normal']:.2f} | {c['check']:.2f} | {c['ipc']:.2f} |")
    print()

    # 表三：三档总价 = Σ(综合报价 × 数量)
    print("## 三、三档总价（Σ 综合报价 × 数量）")
    print()
    print(f"- 普通综合报价总价：**{money(totals[0]):.2f}** 元")
    print(f"- 含点检综合报价总价：**{money(totals[1]):.2f}** 元")
    print(f"- 含工控机和点检综合报价总价：**{money(totals[2]):.2f}** 元")


if __name__ == "__main__":
    main()
