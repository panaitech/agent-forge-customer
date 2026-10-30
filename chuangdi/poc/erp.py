# 模拟金蝶云星空的只读单据查询。
# 只提供物料 BD_MATERIAL 和物料清单 ENG_BOM，不含供应商和采购单价。
# 入参形态接近 ExecuteBillQuery：FormId、FieldKeys、FilterString。

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import book as pricebook


def seed(book):
    # 大件来自当前价格表和核算模板的名称、规格，不带单价。
    mats = []
    boms = []
    n = 0
    for row in book["mod"]:
        # 一行规格覆盖单面/双面两价，物料主数据按面别各留一条，便于核对。
        for glue in ("单面", "双面"):
            n += 1
            mats.append({
                "FNumber": f"MOD-{n:03d}",
                "FName": "模组",
                "FSpecification": pricebook.mod_spec(row, glue),
                "FForbidStatus": "A",
            })
    for i, row in enumerate(book["box"], start=1):
        mats.append({
            "FNumber": f"BOX-{i:03d}",
            "FName": row.get("箱体名称") or "箱体",
            "FSpecification": f"{pricebook.box_spec(row)} {row.get('密封') or ''}".strip(),
            "FForbidStatus": "A",
        })
    for row in book["tpl"]:
        parent = row.get("安装形态") or "屏"
        kids = []
        for mat in mats:
            spec = mat["FSpecification"]
            if mat["FName"] == "模组" and f"P{row.get('点间距_mm')}" in spec:
                kids.append(mat["FNumber"])
            if mat["FName"] == row.get("箱体名称"):
                kids.append(mat["FNumber"])
        boms.append({"FNumber": f"BOM-{parent}", "FName": parent, "FMaterialId": parent, "children": kids})
    return {"BD_MATERIAL": mats, "ENG_BOM": boms}


def _clauses(text):
    # 只认 POC 会发出的等号条件，用 AND 连接。
    parts = [p.strip() for p in text.split("AND")] if text else []
    cond = []
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        cond.append((key.strip(), val.strip().strip("'\"")))
    return cond


def query(data, form, keys, filt):
    rows = data.get(form) or []
    cond = _clauses(filt or "")
    hit = []
    for row in rows:
        ok = True
        for key, val in cond:
            if str(row.get(key, "")) != val:
                ok = False
                break
        if ok:
            hit.append(row)
    fields = [k.strip() for k in (keys or "").split(",") if k.strip()]
    if not fields:
        fields = list(hit[0].keys()) if hit else []
    # 子件列表不作为单元格返回，避免把整张 BOM 塞进一行字符串以外的结构。
    out = []
    for row in hit:
        line = []
        for field in fields:
            val = row.get(field, "")
            if isinstance(val, list):
                val = ",".join(val)
            line.append(val)
        out.append(line)
    return out


def _snap(row):
    # 给销售核对用的物料快照：编码/名称/规格/禁用，不含单价与供应商。
    return {
        "FNumber": row.get("FNumber"),
        "FName": row.get("FName"),
        "FSpecification": row.get("FSpecification"),
        "FForbidStatus": row.get("FForbidStatus"),
    }


def _pitch_token(spec):
    found = re.search(r"P([\d.]+)", str(spec or ""))
    return f"P{found.group(1)}" if found else None


def check_part(data, name, spec, limit=12):
    # 核对结果四种：一致、不一致、禁用、无此料。
    # 不一致/禁用时附带主数据候选行，便于销售对照报价规格与账套物料。
    mats = data["BD_MATERIAL"]
    query = {"FName": name, "FSpecification": spec}
    same = [m for m in mats if m["FName"] == name and spec in m["FSpecification"]]
    if not same:
        loose = [m for m in mats if m["FName"] == name]
        if not loose:
            return {"status": "无此料", "query": query, "hits": [], "hit_total": 0}
        # 有点间距时优先同 P 值候选，避免把全部模组甩给销售
        token = _pitch_token(spec)
        narrow = [m for m in loose if token and token in str(m.get("FSpecification"))] if token else []
        pool = narrow or loose
        hits = [_snap(m) for m in pool[:limit]]
        out = {
            "status": "不一致",
            "query": query,
            "hits": hits,
            "hit_total": len(pool),
        }
        if narrow:
            out["filter"] = f"同点间距 {token}"
        elif len(pool) > limit:
            out["note"] = f"同名候选共 {len(pool)} 条，这里列出前 {limit} 条"
        return out
    hits = [_snap(m) for m in same]
    if any(m["FForbidStatus"] != "A" for m in same):
        return {"status": "禁用", "query": query, "hits": hits, "hit_total": len(hits)}
    return {"status": "一致", "query": query, "hits": hits, "hit_total": len(hits)}


class Handler(BaseHTTPRequestHandler):
    data = {}

    def log_message(self, fmt, *args):
        return

    def _json(self, code, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if path.endswith("AuthService.ValidateUser.common.kdsvc") or path.endswith("LoginByAppSecret.common.kdsvc"):
            self._json(200, {"LoginResultType": 1, "Message": "模拟登录，未连接金蝶"})
            return
        if path.endswith("ExecuteBillQuery.common.kdsvc"):
            params = payload.get("parameters") or [{}]
            q = params[0] if params else {}
            rows = query(self.data, q.get("FormId"), q.get("FieldKeys"), q.get("FilterString"))
            self._json(200, rows)
            return
        self._json(404, {"Message": "未知接口"})


def serve(data, port):
    Handler.data = data
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"模拟查询 http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    # 可选：本机 HTTP 对照。Forge 协作请用 demos/chuangdi-quote MCP。
    from pathlib import Path

    import book

    demo = Path(__file__).resolve().parent.parent / "数据" / "规格单价表-演示.xlsx"
    if not demo.exists():
        import seed_demo

        seed_demo.main()
    serve(seed(book.load(demo)), 8765)
