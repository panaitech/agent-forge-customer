# 按解析指令从 PDF 文本取出情报板行。
# 程序不预设某一份招标文件的章节；页码、查找式和参数条款都在指令里。

import json
import re
import subprocess
from pathlib import Path


def load(path):
    # 解析指令：产品范围、印页、排除项、参数条款、每一行怎么找到
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pages(pdf):
    # 按印在页脚的页码取文本。PDF 物理页序和印页经常不一致。
    info = subprocess.check_output(["pdfinfo", str(pdf)], text=True, errors="replace")
    count = 0
    for line in info.splitlines():
        if line.startswith("Pages:"):
            count = int(line.split()[1])
    found = {}
    for n in range(1, count + 1):
        text = subprocess.check_output(
            ["pdftotext", "-layout", "-f", str(n), "-l", str(n), str(pdf), "-"],
            text=True,
            errors="replace",
        )
        footer = ""
        for raw in reversed(text.splitlines()):
            raw = raw.strip()
            if raw.isdigit():
                footer = raw
                break
        if footer:
            found[int(footer)] = text
    return found


def _around(text, match, before=360, after=220):
    # 版面是分栏的，面积和数量经常写在名称的上方或右侧，不在名称后面。
    start = max(0, match.start() - before)
    chunk = text[start : match.end() + after]
    return chunk, match.start() - start, match.end() - start


def _pick(hits, span_start, span_end):
    # 优先用落在名称匹配范围内的数字，避免把上一行或下一行的数量算进来。
    if not hits:
        return None
    inside = [h for h in hits if span_start <= h.start() <= span_end]
    if inside:
        return inside[0]

    def dist(h):
        if h.end() < span_start:
            return span_start - h.end()
        if h.start() > span_end:
            return h.start() - span_end
        return 0

    return min(hits, key=dist)


def _size(chunk, span_start, span_end):
    # 显示面积。米、m 都认。「10×1 米×2 块」里的块数是屏数，不是第三维。
    # 没有米或 m 的外形（如 2190×2460×3）不当成显示面积。
    pat = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:米|m)?\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:米|m)(?:\s*[×xX*]\s*(\d+)\s*块)?",
        re.I,
    )
    hit = _pick(list(pat.finditer(chunk)), span_start, span_end)
    if not hit:
        return None, None, None
    panels = int(hit.group(3)) if hit.group(3) else 1
    return float(hit.group(1)), float(hit.group(2)), panels


def _qty(chunk, span_start, span_end):
    hit = _pick(list(re.finditer(r"(套|块)\s+(\d+)", chunk)), span_start, span_end)
    if not hit:
        return None, None
    return hit.group(1), int(hit.group(2))


def _flags(chunk):
    return {
        "column": "含立柱" in chunk or "含情报板立柱" in chunk,
        "base": "不含基础" in chunk,
        "hoop": "抱箍" in chunk,
        "bracket": "支架" in chunk,
        "box": "控制箱" in chunk,
        "steel_by_other": "钢结构由交安提供" in chunk,
        "ratio": (re.search(r"(\d+R\d+G(?:\d+B)?)", chunk) or [None, None])[1],
    }


def _seen(spec, needle):
    # 点间距必须能在指令指定的评分页正文里找到。31.25 里的 25 不算单独出现。
    if needle is None:
        return False
    text = spec.replace(" ", "")
    if isinstance(needle, float) and needle != int(needle):
        return f"{needle:g}" in text
    token = str(int(needle)) if isinstance(needle, (int, float)) else str(needle)
    return re.search(rf"(?<![\d.]){re.escape(token)}(?![\d.])", text) is not None


def parse(list_text, spec_text, cfg):
    rows = []
    for item in cfg["lines"]:
        hit = re.search(item["find"], list_text)
        if not hit:
            rows.append({
                "name": item["name"],
                "found": False,
                "reason": ["清单页未找到该行"],
                "auto": False,
            })
            continue
        if item.get("kind") == "skip":
            rows.append({"name": item["name"], "found": True, "skip": True, "auto": False})
            continue
        chunk, span_start, span_end = _around(list_text, hit)
        w, h, panels = _size(chunk, span_start, span_end)
        unit, qty = _qty(chunk, span_start, span_end)
        if item.get("kind") in ("bracket", "unmatched"):
            w, h, panels = None, None, 1
        flags = _flags(hit.group(0))
        if item.get("drop_steel"):
            flags["steel_by_other"] = True
        binding = cfg.get("bindings", {}).get(item.get("binding") or "", {})
        pitch = binding.get("pitch_mm")
        pitch_ok = pitch is not None and _seen(spec_text, pitch)
        bright = binding.get("brightness")
        bright_ok = bright is None or _seen(spec_text, bright)
        pixels = binding.get("pixels_per_m2")
        row = {
            "name": item["name"],
            "found": True,
            "skip": False,
            "kind": item.get("kind") or "screen",
            "merged": bool(item.get("merged")),
            "w": w,
            "h": h,
            "panels": panels or 1,
            "unit": unit,
            "qty": qty,
            "flags": flags,
            "pitch": pitch if pitch_ok else None,
            "pitch_claimed": pitch,
            "pitch_source": binding.get("source") if pitch_ok else None,
            "brightness": bright if bright_ok else None,
            "pixels_per_m2": pixels if pixels and _seen(spec_text, pixels) else None,
            "ratio": flags["ratio"] or binding.get("ratio"),
            "ratio_from_list": bool(flags["ratio"]),
            "install": binding.get("install"),
            "ip": binding.get("ip"),
            "source": binding.get("source"),
            "reason": [],
            "auto": False,
        }
        if item.get("kind") == "bracket":
            row["reason"].append("这是支架，不是屏，不查模组价格")
        elif item.get("kind") == "unmatched":
            row["reason"].append("指令没有同名参数条款，不套用其他行的点间距")
        elif pitch is not None and not pitch_ok:
            row["reason"].append("指令写了点间距，但评分页正文里没有这个数")
        elif pitch is None and item.get("kind") != "bracket":
            row["reason"].append("评分页没有写成毫米的点间距")
        if row["merged"]:
            row["reason"].append("名称是归并，不是评分条款的逐字名称")
        if flags["steel_by_other"] or item.get("drop_steel"):
            row["reason"].append("交安已提供的钢结构不计入")
        rows.append(row)
    # 指令里点名排除的物资：清单里出现过就记一笔，不报价。
    for item in cfg.get("exclude", cfg.get("exclude_find", [])):
        pat = item["find"] if isinstance(item, dict) else item
        name = item.get("name", pat) if isinstance(item, dict) else pat
        if re.search(pat, list_text):
            rows.append({
                "name": name,
                "found": True,
                "skip": True,
                "auto": False,
                "reason": ["不在情报板范围内，不报价"],
            })
    return rows
