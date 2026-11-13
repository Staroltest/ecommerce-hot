#!/usr/bin/env python3
"""中文电商源抓取器：把没有可用 RSS 的中文站首页列表转成 RSS 2.0 文件。

只用 Python 标准库。只取公开列表页的标题 + 链接 + 发布时间，
不进详情页、不取正文、不取摘要、不登录、不绕反爬。
每个站之间至少停 2 秒。输出到 data/feeds/<id>.xml，
sources.json 里用 local:feeds/<id>.xml 引用（generate.py 支持 local: 前缀）。

某站本轮抓到少于 3 条时，不覆盖旧文件（该站首页偶尔返回不完整页面，
例如雨果网有时只返回 55KB 的空壳），保留上一轮的好文件。

用法：python3 tools/scrape_cn.py   （在站点根目录运行）
"""
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_DIR = os.path.join(ROOT, "data", "feeds")
UA = {"User-Agent": "ecommerce-hotBot/1.0 (+https://github.com/Staroltest/ecommerce-hot)"}
from datetime import timedelta
CST = timezone(timedelta(hours=8))


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def clean(text):
    """去标签、解实体后只取第一行非空文本并压缩空白。

    有些站的 <a> 里嵌套了摘要块（例如卖家之家），直接取全文会把摘要
    混进标题，必须只取第一行。
    """
    t = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    first = lines[0] if lines else ""
    return re.sub(r"\s+", " ", first).strip()


def rfc822(dt):
    return format_datetime(dt.astimezone(CST))


def write_rss(path, title, link, items):
    """items: list of (title, link, datetime|None)."""
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = title
    ET.SubElement(ch, "link").text = link
    ET.SubElement(ch, "description").text = title + "（首页抓取，仅标题与链接）"
    for t, l, pub in items:
        it = ET.SubElement(ch, "item")
        ET.SubElement(it, "title").text = t
        ET.SubElement(it, "link").text = l
        if pub:
            ET.SubElement(it, "pubDate").text = rfc822(pub)
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)


def scrape_ebrun_fixed():
    h = fetch("https://www.ebrun.com/")
    out, seen = [], set()
    for m in re.finditer(
        r'<a[^>]+href="(https://www\.ebrun\.com/(\d{4})(\d{2})(\d{2})/\d+\.shtml)"[^>]*>(.*?)</a>',
        h, re.S):
        link, y, mo, d, raw = m.groups()
        t = clean(raw)
        if len(t) >= 6 and link not in seen:
            seen.add(link)
            out.append((t, link, datetime(int(y), int(mo), int(d), 12, tzinfo=CST)))
    return out


def scrape_cifnews():
    h = fetch("https://www.cifnews.com/")
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]*href="(https://www\.cifnews\.com/article/\d+)"[^>]*data-fetch-title="([^"]+)"', h):
        link, t = m.groups()
        t = clean(t)
        if len(t) >= 6 and link not in seen:
            seen.add(link)
            out.append((t, link, None))
    if len(out) < 3:  # 备用：标题与链接顺序相反的写法
        for m in re.finditer(r'<a[^>]*data-fetch-title="([^"]+)"[^>]*href="(https://www\.cifnews\.com/article/\d+)"', h):
            t, link = m.groups()
            t = clean(t)
            if len(t) >= 6 and link not in seen:
                seen.add(link)
                out.append((t, link, None))
    return out


def scrape_dsb():
    h = fetch("https://www.dsb.cn/")
    out, seen = [], set()
    for m in re.finditer(r'"title":"([^"]{6,80})","slug":"([a-z0-9]+)"', h):
        t, slug = m.groups()
        link = "https://www.dsb.cn/p/" + slug
        if link in seen:
            continue
        seen.add(link)
        # 在该条目附近找 published_at
        window = h[max(0, m.start() - 600):m.end() + 1200]
        dm = re.search(r'"published_at":"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"', window)
        pub = None
        if dm:
            try:
                pub = datetime.strptime(dm.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CST)
            except ValueError:
                pub = None
        out.append((clean(t), link, pub))
    return out


def scrape_mjzj():
    h = fetch("https://www.mjzj.com/")
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="(https?://mjzj\.com/article/[a-z0-9]+|//mjzj\.com/article/[a-z0-9]+)"[^>]*>(.*?)</a>', h, re.S):
        link, raw = m.groups()
        link = "https:" + link if link.startswith("//") else link
        t = clean(raw)
        if len(t) >= 6 and link not in seen:
            seen.add(link)
            out.append((t, link, None))
    return out


SITES = [
    ("ebrun", "亿邦动力", "https://www.ebrun.com/", scrape_ebrun_fixed),
    ("cifnews", "雨果网", "https://www.cifnews.com/", scrape_cifnews),
    ("dsb", "电商报", "https://www.dsb.cn/", scrape_dsb),
    ("mjzj", "卖家之家", "https://www.mjzj.com/", scrape_mjzj),
]


def main():
    os.makedirs(FEED_DIR, exist_ok=True)
    results = {}
    for sid, name, link, fn in SITES:
        try:
            items = fn()
        except Exception as e:
            print(f"{sid}: ERR {e}", flush=True)
            results[sid] = 0
            continue
        if len(items) < 3:
            print(f"{sid}: only {len(items)} items, keeping old file", flush=True)
            results[sid] = len(items)
            continue
        write_rss(os.path.join(FEED_DIR, sid + ".xml"), name, link, items)
        print(f"{sid}: {len(items)} items -> data/feeds/{sid}.xml", flush=True)
        results[sid] = len(items)
        time.sleep(2)
    print("done:", results)
    return 0 if all(v >= 3 for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
