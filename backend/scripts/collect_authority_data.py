"""采集东莞市政务公开的民生设施权威名录，冻结为本地 CSV。

为什么需要这个脚本：
    项目的覆盖率与盲区结论全部建立在百度 POI 检索之上。POI 是商业收录，
    可能漏掉真实存在的设施（漏检会让覆盖率虚低）。要回答「百度检索可不可信」，
    必须拿一份**不依赖百度**的权威名录作基准。政务公开数据正好满足：
    来源可追溯、发布单位是主管机关、且恰好覆盖项目判定的三类设施。

数据源（全部为东莞市主管机关公开发布）：

| 类别 | 发布单位 | 载体 |
|---|---|---|
| 药店 | 东莞市医疗保障局「市内定点药店查询」 | JSON（/postmeta/i/<id>.json） |
| 幼儿园 | 东莞市教育局《公办（集体办）幼儿园基本情况一览表》 | xlsx 附件，标准库解压解析 |
| 小学/中学 | 东莞市教育局《广东省义务教育标准化学校名单》 | HTML 表格 |
| 养老机构 | 东莞市民政局《在运营养老机构信息表》 | HTML 表格 |
| 农贸市场 | 东莞市市场监督管理局《星级农贸市场名单》 | HTML 表格 |

**重要局限（已在文档中如实标注，勿隐藏）**：
    1. 药店只覆盖「医保定点」药店，非定点药店不在此名录中；
    2. 幼儿园只覆盖「公办（集体办）」，不含民办；
    3. 农贸市场只有「星级」评定名单（全市约 451 个市场，星级仅数十个）。
    因此比对方向是**单向的**：只用来检验「百度是否漏检了名录中的机构」（召回），
    不能反过来把「百度有、名录无」判为误检——名录本身就不全。

本脚本需要联网，且政务网站改版后会失效；故采集结果已冻结为
`authority_benchmark/*.csv` 入库，比对脚本（authority_benchmark.py）
直接读 CSV，**不依赖本脚本**。本脚本仅用于「数据来源可追溯 + 可重新采集」。
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "authority_benchmark"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) 15min-life-circle/1.0"}
TARGET_TOWNS = ("松山湖", "莞城", "虎门")

# 数据源登记表：URL 与统计截止时间都写进 manifest，保证可追溯
SOURCES = {
    "pharmacy": {
        "url": "https://www.dg.gov.cn/ylbzj/ddlsydcx.html",
        "publisher": "东莞市医疗保障局",
        "title": "市内定点药店查询",
        "note": "医保定点零售药店；非定点药店不在此名录",
    },
    "kindergarten": {
        "url": "https://edu.dg.gov.cn/gkmlpt/content/4/4448/post_4448311.html",
        "publisher": "东莞市教育局",
        "title": "东莞市公办（集体办）幼儿园基本情况一览表（统计至2025年10月）",
        "note": "仅公办/集体办幼儿园，不含民办",
    },
    "school": {
        "url": "https://edu.dg.gov.cn/gkmlpt/content/3/3964/post_3964562.html",
        "publisher": "东莞市教育局",
        "title": "东莞市“广东省义务教育标准化学校”名单（统计至2023年2月）",
        "note": "原表无地址字段，仅有镇街；定位需按名称地理编码",
    },
    "elderly_care": {
        "url": "https://mzj.dg.gov.cn/gkmlpt/content/4/4226/post_4226032.html",
        "publisher": "东莞市民政局",
        "title": "东莞市在运营养老机构信息表（2024年6月）",
        "note": "",
    },
    "market": {
        "url": "http://dgamr.dg.gov.cn/zfxxgkml/qt/tzgg/content/post_4459335.html",
        "publisher": "东莞市市场监督管理局",
        "title": "关于东莞市五星农贸市场名单的公示（2025-11-14，21家）",
        "note": "仅五星名单；全市约 451 个农贸市场，星级评定覆盖极小",
    },
}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as resp:
        return resp.read()


def fetch_json(cid: int) -> dict:
    base = "https://www.dg.gov.cn/postmeta/i/"
    return json.loads(fetch(f"{base}{cid}.json").decode("utf-8", "ignore"))


def strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def table_rows(html: str) -> list[list[str]]:
    """把 HTML 里所有 <tr> 抽成单元格文本列表。

    注意 `<tr>` 可能带属性（政务网站的原生表格导出常见），因此不能写死 `<tr>`。
    """
    rows = []
    for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html, re.I):
        cells = [
            strip_tags(c) for c in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, re.I)
        ]
        if cells:
            rows.append(cells)
    return rows


def data_rows(html: str) -> list[list[str]]:
    """只保留「首列是序号」的行，滤掉政务页面里的公文头部表格。"""
    return [r for r in table_rows(html) if r[0].strip().rstrip(".").isdigit()]


def write_csv(name: str, header: list[str], rows: list[list[str]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  -> {path.relative_to(OUT_DIR.parent.parent)}  {len(rows)} 行")


# ---------------------------------------------------------------------------
# 1. 药店：医保定点零售药店（JSON，abstract 字段是 _ 拼接的一行记录）
# ---------------------------------------------------------------------------
def collect_pharmacy() -> list[list[str]]:
    tree = fetch_json(15165)
    provinces = r"^P\d{8,}$"
    out = []
    for child in tree.get("children") or []:
        town = str(child.get("name", ""))
        if not any(t in town for t in TARGET_TOWNS):
            continue
        for art in (fetch_json(child["id"]).get("articles") or []):
            parts = [p.strip() for p in str(art.get("abstract", "")).split("_")]
            # 以省平台机构编号为锚点切分，避免地址里含下划线时错位
            anchor = next((i for i, p in enumerate(parts) if re.match(provinces, p)), None)
            name = str(art.get("title") or "").strip()
            if anchor is None or anchor + 1 >= len(parts):
                continue
            name = name or parts[anchor + 1]
            address = parts[anchor + 2] if anchor + 2 < len(parts) else ""
            out.append([town, name, address, art.get("id", "")])
    return out


# ---------------------------------------------------------------------------
# 2. 幼儿园：xlsx 附件（纯标准库解压 + 解析，不引入 openpyxl 依赖）
# ---------------------------------------------------------------------------
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _col_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref).group(1)
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def xlsx_rows(blob: bytes) -> list[list[str]]:
    """解析 xlsx 第一个工作表：xlsx 即 ZIP+XML，标准库足以应付这种规整表格。"""
    with zipfile.ZipFile(BytesIO(blob)) as book:
        shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
        strings = [
            "".join(t.text or "" for t in si.iter(f"{_NS}t"))
            for si in shared_root.findall(f"{_NS}si")
        ]
        sheet = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))

    rows = []
    for row in sheet.iter(f"{_NS}row"):
        cells: dict[int, str] = {}
        for cell in row.findall(f"{_NS}c"):
            kind = cell.get("t")
            if kind == "s":
                node = cell.find(f"{_NS}v")
                value = strings[int(node.text)] if node is not None and node.text else ""
            elif kind == "inlineStr":
                node = cell.find(f"{_NS}is")
                value = "".join(t.text or "" for t in node.iter(f"{_NS}t")) if node is not None else ""
            else:
                node = cell.find(f"{_NS}v")
                value = node.text or "" if node is not None else ""
            cells[_col_index(cell.get("r") or "A1")] = value.strip()
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def collect_kindergarten() -> list[list[str]]:
    rows = xlsx_rows(fetch(SOURCES["kindergarten"]["url"]))
    # 第 2 行是表头（序号/镇街/幼儿园名称/地址/保教费/等级/电话）
    out = []
    for row in rows[2:]:
        if len(row) < 4:
            continue
        town, name, address = row[1], row[2], row[3]
        # 市直属幼儿园的地址落在具体镇街，按地址归属，否则松山湖/莞城会漏掉园区内园所
        if not any(t in town for t in TARGET_TOWNS):
            if not any(t in address for t in TARGET_TOWNS):
                continue
            town = next(t for t in TARGET_TOWNS if t in address)
        if name:
            out.append([town, name, address])
    return out


# ---------------------------------------------------------------------------
# 3. 小学/中学：HTML 表格（无地址，仅有镇街）
# ---------------------------------------------------------------------------
def collect_school() -> list[list[str]]:
    html = fetch(SOURCES["school"]["url"]).decode("utf-8", "ignore")
    out = []
    for row in data_rows(html):
        if len(row) < 4:
            continue
        name, town, kind = row[1], row[2], row[3]
        if not any(t in town for t in TARGET_TOWNS):
            continue
        town = next(t for t in TARGET_TOWNS if t in town)
        # 只取小学（含九年一贯制），中学不是本项目统计口径
        if "小学" not in kind and "一贯制" not in kind:
            continue
        out.append([town, name, kind, ""])
    return out


# ---------------------------------------------------------------------------
# 4. 养老机构：HTML 表格（含地址）
# ---------------------------------------------------------------------------
def collect_elderly_care() -> list[list[str]]:
    html = fetch(SOURCES["elderly_care"]["url"]).decode("utf-8", "ignore")
    out = []
    for row in data_rows(html):
        if len(row) < 8:
            continue
        # 该表没有「镇街」列，归属镇街只能从地址里提取
        name, address = row[1], row[6]
        town = next((t for t in TARGET_TOWNS if t in address), "")
        if town:
            out.append([town, name, address])
    return out


# ---------------------------------------------------------------------------
# 5. 农贸市场：星级名单（含地址）
# ---------------------------------------------------------------------------
def collect_market() -> list[list[str]]:
    html = fetch(SOURCES["market"]["url"]).decode("utf-8", "ignore")
    out = []
    for row in data_rows(html):
        if len(row) < 4:
            continue
        town, name, address = row[1], row[2], row[3]
        if any(t in town for t in TARGET_TOWNS):
            out.append([town, name, address, "五星"])
        elif any(t in address for t in TARGET_TOWNS):
            out.append([next(t for t in TARGET_TOWNS if t in address), name, address, "五星"])
    return out


COLLECTORS = {
    "dongguan_pharmacy": (collect_pharmacy, ["镇街", "名称", "地址", "来源ID"]),
    "dongguan_kindergarten": (collect_kindergarten, ["镇街", "名称", "地址"]),
    "dongguan_school": (collect_school, ["镇街", "名称", "类型", "地址"]),
    "dongguan_elderly_care": (collect_elderly_care, ["镇街", "名称", "地址"]),
    "dongguan_market": (collect_market, ["镇街", "名称", "地址", "星级"]),
}


def main() -> int:
    print(f"采集目标镇街：{'、'.join(TARGET_TOWNS)}")
    collected: dict[str, int] = {}
    for name, (fn, header) in COLLECTORS.items():
        print(f"[{name}]")
        try:
            rows = fn()
        except Exception as exc:  # 政务网站改版 / 网络问题都不应中断整体流程
            print(f"  !! 采集失败：{type(exc).__name__} {exc}")
            continue
        collected[name] = len(rows)
        write_csv(name, header, rows)

    (OUT_DIR / "manifest.json").write_text(
        json.dumps(
            {
                "collected_at": "2026-10-16",
                "target_towns": list(TARGET_TOWNS),
                "row_counts": collected,
                "sources": SOURCES,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("  -> authority_benchmark/manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
