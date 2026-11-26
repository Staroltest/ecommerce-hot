#!/usr/bin/env python3
"""中文电商源抓取器：把没有可用 RSS 的中文站首页列表转成 RSS 2.0 文件。

只用 Python 标准库。只取公开列表页的标题 + 链接 + 发布时间，
不进详情页、不取正文、不取摘要、不登录、不绕反爬。
每个站之间至少停 2 秒。输出到 data/feeds/<id>.xml，
sources.json 里用 local:feeds/<id>.xml 引用（generate.py 支持 local: 前缀）。

某站本轮抓到少于 3 条时，不覆盖旧文件（该站首页偶尔返回不完整页面，
例如雨果网有时只返回 55KB 的空壳），保留上一轮的好文件。
例外：Google Trends（gtrends）是日榜快照，过滤后剩 0-2 条是正常情况，
0 条也写文件（表示今天没有产品类热搜）；只有拉取本身失败时才保留旧文件
（见 MIN_KEEP）。

2026-11-15 增 4 个产品热度信号源（用户批准）：Google Trends 美国热搜
（官方 RSS 拉取后否定词过滤）、NicheHunter TikTok Shop 日榜、
JadeShip 1688 七日榜（只取排名上升条目）、卖家精灵博客。
同日再增 Sell The Trend 爆款榜（用户批准）：月榜 Top 10 + 22 类目周榜
各取第 1 名，去重后通常 25 条（见 scrape_sellthetrend）。

用法：python3 tools/scrape_cn.py   （在站点根目录运行）
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import gzip
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
        raw = r.read()
        # 2026-11-25 修：雨果网首页开始回 Content-Encoding: gzip（未请求也
        # 压），urllib 不自动解压，decode 后是乱码、正则 0 命中，cifnews
        # 连续 3 轮 0 条。按 gzip 魔数解压；非 gzip 体原样解码，不影响
        # 其他源。
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="ignore")


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
        # 2026-11-17：国内医药合作签约（如“九州通医药集团与三元基因签署
        #   战略合作协议”）是纯国内商业新闻，与跨境选品无关，且会进入首页
        #   时间线（时间线按时间取前 100 条，不按分数），此前 12:23 轮次已
        #   下架过同类条目。规则：标题同时含“医药”和“签署/战略合作”才拦，
        #   只含“医药”的跨境医药类目/合规新闻不受影响。代价：跨境医药合作
        #   签约类新闻若只经电商报进来也会被拦，可经其余信源进入。
        t_clean = clean(t)
        if "医药" in t_clean and ("签署" in t_clean or "战略合作" in t_clean):
            continue
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


# ---------------------------------------------------------------- 产品热度信号源
# 2026-11-15 接入（用户批准）。只取公开列表页的标题 + 链接 + 时间，
# 不进详情页、不取正文、不取销量以外的任何字段、不登录。

def scrape_nichehunter():
    """NicheHunter TikTok Shop 每日 Top 10。

    页面是 Next.js 服务端渲染，10 条商品在 JSON-LD ItemList 里
    （含商品名、商品页链接、销量/预估收入/评分等描述），直接解析 JSON，
    不依赖 JS。标题取商品名，链接取商品页，时间取榜单日期
    （ItemList 名称里的 YYYY-MM-DD，中午 12:00 CST）。
    销量数字只在写中文简介时用，不进 RSS（RSS 只放标题 + 链接 + 时间）。
    """
    h = fetch("https://nichehunter.com/tools/winning-product-finder/")
    out, seen = [], set()
    pub = None
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", data.get("name", ""))
        if dm:
            try:
                pub = datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)),
                               12, tzinfo=CST)
            except ValueError:
                pub = None
        for el in data.get("itemListElement", []) or []:
            it = el.get("item", {}) if isinstance(el, dict) else {}
            t = clean(it.get("name", ""))
            link = (it.get("url", "") or "").strip()
            if len(t) >= 6 and link and link not in seen:
                seen.add(link)
                out.append((t, link, pub))
        break
    return out[:10]


def scrape_jadeship():
    """JadeShip 1688 七日榜（按 7 日销量排的 Top 50）。

    取数逻辑：本页只有 amount_sold 一种排序，没有单独的“涨幅榜”，
    因此取其中较上一周期排名上升的条目（卡片里 lucide-arrow-up 标记，
    数字为上升位数），按原排名顺序取前 10 条（2026-11-15 用户定：先上线过渡，避免单源刷屏；根本修法是生成器单源上限）。下降（arrow-down）与
    无升降标记的新上榜条目不取。标题取商品名，链接取商品页
    （去掉 ?agent= 推广参数），时间取 Last bought 的 GMT 时间戳。
    """
    h = fetch("https://www.jadeship.com/feed/top/7-days/1688")
    out, seen = [], set()
    for m in re.finditer(r'id="item-1688-(\d+)"', h):
        seg = h[m.start():m.start() + 4000]
        tm = re.search(r'<h3[^>]*title="([^"]+)"', seg)
        if not tm:
            continue
        t = clean(tm.group(1))
        am = re.search(r'lucide-arrow-(up|down)[^>]*>.*?</svg>\s*(\d+)', seg, re.S)
        if not am or am.group(1) != "up":
            continue
        lm = re.search(r'title="([A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2}) GMT"',
                       seg)
        pub = None
        if lm:
            try:
                pub = datetime.strptime(lm.group(1), "%a, %d %b %Y %H:%M:%S") \
                    .replace(tzinfo=timezone.utc).astimezone(CST)
            except ValueError:
                pub = None
        link = "https://www.jadeship.com/item/1688/" + m.group(1)
        if len(t) >= 6 and link not in seen:
            seen.add(link)
            out.append((t, link, pub))
        if len(out) >= 10:
            break
    return out


def scrape_sellersprite():
    """卖家精灵博客列表页。标题与日期都在列表页内。

    注意：裸域名 sellersprite.com 在当前环境 DNS 解析失败，
    必须用 www 子域名。标题取文章标题（已是中文），链接取文章页，
    时间取文章信息区的 YYYY-MM-DD（中午 12:00 CST）。
    """
    h = fetch("https://www.sellersprite.com/cn/blog/")
    out, seen = [], set()
    for m in re.finditer(
            r'<div class="article-title">\s*<a href="(/cn/blog/[^"]+)">([^<]+)</a>', h):
        path, t = m.groups()
        t = clean(t)
        dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", h[m.end():m.end() + 500])
        pub = None
        if dm:
            try:
                pub = datetime(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)),
                               12, tzinfo=CST)
            except ValueError:
                pub = None
        link = "https://www.sellersprite.com" + path
        if len(t) >= 6 and link not in seen:
            seen.add(link)
            out.append((t, link, pub))
    return out


# ---------------------------------------------------------------- Sell The Trend 爆款榜
# 2026-11-15 接入（用户批准）。月榜 Top 10 + 22 个类目周榜各取第 1 名，
# 去重后通常 25 条左右（同一产品常跨多个类目登顶，如 SafeHoot 同时是
# 环保/时尚/健康三个类目的第 1 名，2026-11-15 实测 22 类目只有 15 个
# 不同产品）。只取公开列表页的标题 + 链接 + 时间，不进详情页、不取正文、
# 不登录。周榜只取第 1 名是防刷屏上限（之前 JadeShip 一度占热点 19/20，
# 用户已批过按源截流的做法；根本修法仍是生成器单源上限）。
# 每条产品的数字信息（月榜 Stats 行、周榜类目平均利润率/竞争程度）
# 不进 RSS，只写 sidecar data/feeds/sellthetrend-meta.json，
# 供写中文简介时用；RSS 仍只放标题 + 链接 + 时间。

# 22 个类目 slug（见 https://www.sellthetrend.com/basic-sitemap.xml
# 里的 /niche/<slug>，不含 categories 索引页）。
STT_NICHES = [
    "automotive-accessories", "baby-and-parenting-essentials",
    "beauty-and-personal-care", "cooking-and-kitchen-gadgets",
    "eco-friendly-essentials", "electronics-and-tech-gadgets",
    "fashion-and-apparel", "fitness-and-exercise",
    "garden-and-patio-essentials", "health-wellness-and-recovery",
    "hobby-and-creative-kits", "home-improvement-and-decor",
    "jewelry-and-watches", "office-and-productivity",
    "outdoor-and-survival-gear", "personalized-and-custom-gifts",
    "pet-products", "phone-accessories", "seasonal", "sports",
    "tools-and-diy-hardware", "travel-and-digital-nomad-gear",
]
STT_MONTHS = {n: i + 1 for i, n in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
# 每条产品的数字信息（写中文简介用），按链接做键。
STT_META = {}


def _stt_text(snippet):
    """去标签、解实体后压缩成一行全文（与 clean() 只取第一行不同，
    周榜的日期/利润率/竞争程度在同一段落的不同行里）。"""
    t = html.unescape(re.sub(r"<[^>]+>", " ", snippet or ""))
    return re.sub(r"\s+", " ", t).strip()


def _stt_strip_marks(t):
    """去掉标题里的 ™ / ® / © 与 emoji（周榜标题常带，如 CapKeeper™ 🧢✨）。"""
    t = re.sub(r"[™®©]", "", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+", "", t)
    return re.sub(r"\s+", " ", t).strip(" -–—")


def scrape_sellthetrend():
    """Sell The Trend 月榜 + 类目周榜。

    月榜：主榜页 Monthly Winning Products Archive 标题（h2）之前的
    前 10 条带编号产品 h3（形如 <h3><b>1. <a href="…pid=…">…</a></b></h3>），
    链接取 pid 链接；日期取标题里的 "(Updated for November 2026)"，
    定为当月 1 日 12:00 CST。产品下方的 Stats 行记入 sidecar。
    周榜：每个类目页取 "Top N … (Products) to Dropship This Week" 里的
    第 1 名（h3 形如 <h3>1. <a href="…pid=…">…</a></h3>），链接取 pid 链接；
    日期取页内 "Weekly Intelligence Summary" 里的 "for November 15th, 2026"
    （取不到时用 JSON-LD dateModified 的日期），定为当日 12:00 CST；
    类目平均利润率与竞争程度也记入 sidecar。类目页之间停 1 秒。
    单个类目页拉取失败时跳过该类目，不影响其余类目。
    """
    out, seen = [], set()
    pat = re.compile(
        r'<h3[^>]*>(?:\s*<b>)?\s*(\d+)\.\s*<a\s+href="([^"]*pid=[^"]*)"[^>]*>(.*?)</a>',
        re.S)
    # --- 月榜 ---
    h = fetch("https://www.sellthetrend.com/blog/winning-products")
    pub_m = None
    month_label = ""
    dm = re.search(
        r"Updated for (January|February|March|April|May|June|July|August|"
        r"September|October|November|December) (\d{4})", h)
    if dm:
        month_label = dm.group(0)
        try:
            pub_m = datetime(int(dm.group(2)), STT_MONTHS[dm.group(1)], 1, 12,
                             tzinfo=CST)
        except ValueError:
            pub_m = None
    cut = len(h)
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", h, re.S):
        if "Monthly Winning Products Archive" in clean(m.group(1)):
            cut = m.start()
            break
    n_month = 0
    for m in pat.finditer(h[:cut]):
        rank, link, raw = m.groups()
        if int(rank) < 1 or int(rank) > 10:
            continue
        t = _stt_strip_marks(clean(raw))
        link = html.unescape(link)
        if len(t) < 3 or link in seen:
            continue
        seg = h[m.end():m.end() + 3000]
        sm = re.search(r"Stats:</i></b><i><span[^>]*>(.*?)</span>", seg, re.S)
        stats = clean(sm.group(1)) if sm else ""
        seen.add(link)
        out.append((t, link, pub_m))
        STT_META[link] = {"kind": "monthly", "rank": int(rank),
                          "stats": stats, "month": month_label}
        n_month += 1
        if n_month >= 10:
            break
    # --- 周榜：22 类目各取第 1 名 ---
    for slug in STT_NICHES:
        time.sleep(1)
        p = None
        for attempt in range(2):
            try:
                p = fetch("https://www.sellthetrend.com/niche/" + slug)
                break
            except Exception as e:
                # 类目页偶尔拉取失败（连拉 23 个页时易被限流），隔 3 秒重试一次；
                # 再失败就跳过该类目，不影响其余类目（下轮再试）。
                if attempt == 0:
                    time.sleep(3)
                else:
                    print(f"sellthetrend: {slug} fetch failed ({e}), skipped",
                          flush=True)
        if p is None:
            continue
        niche = slug.replace("-", " ").title()
        hm = re.search(r"<h1[^>]*>(.*?)</h1>", p, re.S)
        if hm:
            nm = re.match(r"Best Trending (.+?) (?:Products )?to Dropship",
                          clean(hm.group(1)))
            if nm:
                niche = nm.group(1)
        pub_w, margin, competition = None, "", ""
        si = p.find("Weekly Intelligence Summary")
        if si >= 0:
            stext = _stt_text(p[si:si + 3000])
            dw = re.search(
                r"for\s+([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th),\s*(\d{4})",
                stext)
            if dw:
                try:
                    pub_w = datetime(int(dw.group(3)), STT_MONTHS[dw.group(1)],
                                     int(dw.group(2)), 12, tzinfo=CST)
                except ValueError:
                    pub_w = None
            mm = re.search(r"average profit margin of\s+([\d.]+%)", stext)
            if mm:
                margin = mm.group(1)
            cm = re.search(r"and\s+(low|medium|high)\s+competition", stext)
            if cm:
                competition = cm.group(1)
        if pub_w is None:
            jm = re.search(r'"dateModified"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', p)
            if jm:
                pub_w = datetime(int(jm.group(1)), int(jm.group(2)),
                                 int(jm.group(3)), 12, tzinfo=CST)
        # 第 1 名：锚定在周榜标题之后（标题有两种写法：
        #   "Top 10 Fitness & Exercise Products to Dropship This Week"
        #   或 "Top 10 Automotive Accessories to Dropship This Week"，
        #   有的带 Products 有的不带，不要锚定 Products）。
        anchor = p.find("to Dropship This Week")
        wm = pat.search(p[anchor:anchor + 20000]) if anchor >= 0 else None
        if not wm or int(wm.group(1)) != 1:
            print(f"sellthetrend: {slug} no #1 product found, skipped",
                  flush=True)
            continue
        link = html.unescape(wm.group(2))
        t = _stt_strip_marks(clean(wm.group(3)))
        if len(t) < 3:
            continue
        if link in seen:
            # 同一产品常在多个类目同时登顶（如 SafeHoot 同时是环保/时尚/
            # 健康三个类目的第 1 名）：feed 里只留一条，但把类目都记进
            # sidecar，写简介时可写“多类目第 1 名”。
            prev = STT_META.get(link)
            if prev and prev.get("kind") == "weekly" \
                    and niche not in prev.get("niches", []):
                prev.setdefault("niches", []).append(niche)
            continue
        seen.add(link)
        out.append((t, link, pub_w))
        STT_META[link] = {"kind": "weekly", "rank": 1, "niche": niche,
                          "niches": [niche],
                          "margin": margin, "competition": competition}
    with open(os.path.join(FEED_DIR, "sellthetrend-meta.json"),
              "w", encoding="utf-8") as f:
        json.dump(STT_META, f, ensure_ascii=False, indent=1)
    return out


# ---------------------------------------------------------------- TokConnect / 蝉妈妈
# 2026-11-18 接入（用户批准“先加最强的两个”）。
# TokConnect：美国 TikTok Shop 数据站，三页同一表格结构，无登录墙。
#   注意：产品行里没有单品链接（只有产品名 + 数字），因此条目链接用榜单页
#   + ?product=<slug>-<rank>（generate.py 的 norm_link 只去 fragment 与
#   utm_*，其余参数保留，去重不塌；链接本身打开就是该产品所在的榜单页）。
#   日期取页面 updated_time（榜单更新日，定为当日 12:00 CST），不用抓取日冒充。
#   上限（防刷屏；用户已批过按源截流的做法，根本修法仍是生成器单源上限）：
#   Rising 只取前 10，Breakout 全取 18 条，搜索榜只取主榜前 10。
#   产品数字（销售额/涨幅/件数/搜索量）不进 RSS，只写 sidecar
#   data/feeds/tokconnect-meta.json，供写中文简介时用（与 STT 同例）。
# 蝉妈妈：运营圈抖音销量周榜文章。发现用 sitemap-yyq.xml（1MB，
#   20 小时内复用本地缓存，不每半小时全量拉）；标题取文章页 <title>
#   （去掉 " - 蝉妈妈运营圈" 后缀；只取标题，不取正文——文章页在这里就是
#   条目本身，与卖家精灵博客同理，用户已点头）；时间取 sitemap lastmod；
#   只收标题含“销量榜/周榜”的文章；标题另存 chanmama-titles.json 缓存，
#   已取过的标题不再重复拉——不缓存会让每轮把 7 天内上百篇文章重拉一遍。

TOK_META = {}


def _tok_slug(name):
    """产品名 -> URL 安全的 slug（ASCII 字母数字，其余变 -）。"""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "product"


def _tok_updated(h):
    """页面 updated_time meta -> 当日 12:00 CST；取不到抛错（走旧文件保护）。"""
    m = re.search(r'updated_time"\s+content="(\d{4})-(\d{2})-(\d{2})', h)
    if not m:
        raise RuntimeError("tokconnect: no updated_time meta")
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12,
                    tzinfo=CST)


def _tok_cells(row):
    """一行 <tr> -> (rank, name, sub, {data-label: 文本}, cells)。
    榜单行：rank 在 <td class="rank">，产品名在 <td class="pk"> 的 <strong>，
    数字列带 data-label 属性。"""
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    if len(cells) < 2:
        return None
    rank_m = re.search(r"(\d+)", clean(cells[0]))
    rank = int(rank_m.group(1)) if rank_m else 0
    nm = re.search(r"<strong>([^<]+)</strong>", cells[1])
    name = _stt_strip_marks(clean(nm.group(1))) if nm else clean(cells[1])
    sm = re.search(r'<span class="sub">([^<]+)</span>', cells[1])
    sub = clean(sm.group(1)) if sm else ""
    labs = {}
    for lm in re.finditer(r'<td[^>]*data-label="([^"]+)"[^>]*>(.*?)</td>', row, re.S):
        labs[lm.group(1)] = clean(lm.group(2))
    return rank, name, sub, labs, cells


def _tok_write_meta():
    with open(os.path.join(FEED_DIR, "tokconnect-meta.json"),
              "w", encoding="utf-8") as f:
        json.dump(TOK_META, f, ensure_ascii=False, indent=1)


def scrape_tokconnect_rising():
    """TokConnect Rising：本周涨最快 50 条，只取前 10。"""
    h = fetch("https://tokconnect.com/trends/tiktok-shop/rising-products/")
    pub = _tok_updated(h)
    out, seen = [], set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        if "<td" not in row:
            continue
        parsed = _tok_cells(row)
        if not parsed:
            continue
        rank, name, sub, labs, _cells = parsed
        if not rank or len(name) < 3:
            continue
        link = ("https://tokconnect.com/trends/tiktok-shop/rising-products/"
                "?product=" + _tok_slug(name) + "-" + str(rank))
        if link in seen:
            continue
        seen.add(link)
        out.append((name, link, pub))
        TOK_META[link] = {"kind": "rising", "rank": rank,
                          "price": labs.get("Price", ""),
                          "revenue7d": labs.get("Revenue, 7 days", ""),
                          "growth": labs.get("Growth, added revenue", ""),
                          "units7d": labs.get("Units, 7 days", ""),
                          "creators": labs.get("Creators", ""),
                          "commission": labs.get("Commission", ""),
                          "category": sub}
        if len(out) >= 10:
            break
    _tok_write_meta()
    return out


def scrape_tokconnect_breakout():
    """TokConnect Breakout：新品爆发榜 18 条，全取。"""
    h = fetch("https://tokconnect.com/trends/tiktok-shop/breakout-products/")
    pub = _tok_updated(h)
    out, seen = [], set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        if "<td" not in row:
            continue
        parsed = _tok_cells(row)
        if not parsed:
            continue
        rank, name, sub, labs, _cells = parsed
        if not rank or len(name) < 3:
            continue
        link = ("https://tokconnect.com/trends/tiktok-shop/breakout-products/"
                "?product=" + _tok_slug(name) + "-" + str(rank))
        if link in seen:
            continue
        seen.add(link)
        out.append((name, link, pub))
        TOK_META[link] = {"kind": "breakout", "rank": rank,
                          "price": labs.get("Price", ""),
                          "units30d": labs.get("Units, 30 days", ""),
                          "reviews": labs.get("Reviews", ""),
                          "reviews_per_1000": labs.get("Reviews per 1,000 units", ""),
                          "creators": labs.get("Creators", ""),
                          "commission": labs.get("Commission", ""),
                          "category": sub}
    _tok_write_meta()
    return out


def scrape_tokconnect_search():
    """TokConnect 搜索榜：取主榜（"Product topics people are searching
    on TikTok this week"，11 条）前 10；"Fastest risers" 与 "TikTok names
    itself" 两表暂不取（同一批词会重复，且后者无涨幅）。"""
    h = fetch("https://tokconnect.com/trends/products/")
    pub = _tok_updated(h)
    out, seen = [], set()
    tables = re.findall(r"<table[^>]*>(.*?)</table>", h, re.S)
    main = None
    for tb in tables:
        ths = [re.sub(r"<[^>]+>", "", x).strip()
               for x in re.findall(r"<th[^>]*>(.*?)</th>", tb, re.S)]
        if ths == ["#", "Search topic", "7-day searches", "7-day trend",
                   "Videos"]:
            main = tb
            break
    if main is None:
        raise RuntimeError("tokconnect-search: main table not found")
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", main, re.S):
        if "<td" not in row:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 5:
            continue
        rank_m = re.search(r"(\d+)", clean(cells[0]))
        rank = int(rank_m.group(1)) if rank_m else 0
        topic = _stt_strip_marks(clean(cells[1]))
        if not rank or len(topic) < 3:
            continue
        link = ("https://tokconnect.com/trends/products/"
                "?topic=" + _tok_slug(topic) + "-" + str(rank))
        if link in seen:
            continue
        seen.add(link)
        out.append((topic, link, pub))
        TOK_META[link] = {"kind": "search", "rank": rank,
                          "searches7d": clean(cells[2]),
                          "trend": clean(cells[3]),
                          "videos": clean(cells[4])}
        if len(out) >= 10:
            break
    _tok_write_meta()
    return out


CHANMAMA_SITEMAP = "https://www.chanmama.com/open/sitemap-yyq.xml"
CHANMAMA_SITEMAP_CACHE = os.path.join(FEED_DIR, "chanmama-sitemap.xml")
CHANMAMA_TITLES_CACHE = os.path.join(FEED_DIR, "chanmama-titles.json")
CHANMAMA_CACHE_SECONDS = 20 * 3600


def scrape_chanmama():
    """蝉妈妈运营圈抖音销量周榜文章。

    发现用 sitemap-yyq.xml（1MB，20 小时内复用本地缓存，不每半小时
    全量拉）；标题取文章页 <title>（去掉 " - 蝉妈妈运营圈" 后缀；
    只取标题，不取正文——文章页在这里就是条目本身，与卖家精灵博客
    同理，用户已点头）；时间取 sitemap lastmod；只收标题含“销量榜/
    周榜”的文章。标题另存 chanmama-titles.json 缓存（{链接：[标题，
    lastmod]}，超 8 天的清理），已取过的标题不再重复拉——不缓存会
    导致每轮把 7 天内上百篇文章重拉一遍。
    """
    xml = None
    if os.path.exists(CHANMAMA_SITEMAP_CACHE):
        age = time.time() - os.path.getmtime(CHANMAMA_SITEMAP_CACHE)
        if age < CHANMAMA_CACHE_SECONDS:
            with open(CHANMAMA_SITEMAP_CACHE, encoding="utf-8") as f:
                xml = f.read()
    if xml is None:
        xml = fetch(CHANMAMA_SITEMAP)
        with open(CHANMAMA_SITEMAP_CACHE, "w", encoding="utf-8") as f:
            f.write(xml)
    now = datetime.now(CST)
    arts = []
    for m in re.finditer(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", xml):
        loc, lm = m.groups()
        if "/yunyingquan/article/" not in loc:
            continue
        try:
            pub = datetime.fromisoformat(lm).astimezone(CST)
        except ValueError:
            continue
        if (now - pub).days > 7:
            continue
        arts.append((loc, pub))
    titles = {}
    if os.path.exists(CHANMAMA_TITLES_CACHE):
        try:
            titles = json.load(open(CHANMAMA_TITLES_CACHE, encoding="utf-8"))
        except (json.JSONDecodeError, AttributeError):
            titles = {}
    # 清掉超 8 天的缓存标题（按缓存时记的 lastmod）
    fresh = {}
    for l, v in titles.items():
        try:
            if isinstance(v, list) and len(v) == 2 \
                    and (now - datetime.fromisoformat(v[1])).days <= 8:
                fresh[l] = v
        except (ValueError, TypeError):
            continue
    titles = fresh
    out = []
    dirty = False
    for link, pub in sorted(arts, key=lambda x: x[1], reverse=True):
        ent = titles.get(link)
        t = ent[0] if ent else None
        if t is None:
            try:
                h = fetch(link)
            except Exception as e:
                print(f"chanmama: {link} fetch failed ({e}), skipped", flush=True)
                continue
            tm = re.search(r"<title>([^<]+)</title>", h)
            if not tm:
                continue
            t = re.sub(r"\s*-\s*蝉妈妈运营圈\s*$", "", clean(tm.group(1)))
            titles[link] = [t, pub.isoformat()]
            dirty = True
            time.sleep(1)
        if len(t) < 6:
            continue
        if "销量榜" not in t and "周榜" not in t:
            continue
        out.append((t, link, pub))
    if dirty:
        with open(CHANMAMA_TITLES_CACHE, "w", encoding="utf-8") as f:
            json.dump(titles, f, ensure_ascii=False, indent=1)
    return out


# Google Trends 泛热搜否定词：体育、娱乐、政治类标记词（词边界匹配）。
# 榜单是英文热搜词，人名本身无法枚举，所以同时看标题、首条新闻标题、
# 新闻来源三处；命中即丢弃。注意：故意没放 game / series / season /
# coach / trial / player 这些词——它们常出现在真实商品趋势里
# （游戏机、产品系列、季节性商品、Coach 品牌、free trial、
# 播放器），放进来会误杀产品信号。残留的人名类热搜（如纯人名，无任何
# 体育/娱乐标记词）曾靠打分沉底，但 2026-11-15 证实该假设不成立；
# 现由 GTRENDS_GATE_RE 商业词门槛兜底。
# 美式球队昵称、trade、stadium、troops 也在列：球队人名类热搜常以
# 交易流言（"XXX trade-or-keep"）或球队名形式出现，只靠联赛词拦不住。
GTRENDS_DENY = re.compile(
    r"\b(?:nfl|nba|wnba|mlb|nhl|ncaa|fifa|uefa|mls|pga|lpga|atp|wta|ufc|wwe|aew|espn"
    # --- 2026-11-24 补：第 40 次漏网（未遂，重抓时发现：本轮 "lexie hull"，
    #   首条新闻是 Observer "The Essentials With Lexie Hull: Throne of
    #   Glass, Cabo and Makeup Put to the WNBA Test"，WNBA 球员的明星生活方式
    #   专栏，新闻标题里的 "Makeup" 既救回了人名规则、又通过了 gate（makeup
    #   在 gate 词表里）。人名热搜不是选品信号。只加联赛词 "wnba"——旧规则
    #   的 \bnba\b 匹配不到 WNBA（词界问题）；gate 里的 makeup 保留，真实美妆
    #   爆款热搜不受影响。---
    r"|football|basketball|baseball|hockey|soccer|tennis|golf|boxing|wrestling"
    r"|quarterback|qbs?|tds?|touchdown|mvp|playoffs?|super\s+bowl|world\s+cup|champions\s+league"
    r"|premier\s+league|la\s+liga|serie\s+a|europa\s+league|all-star|all\s+star"
    r"|draft|injury|trade|stadium|arena|troops|military"
    r"|nuggets|sixers?|lakers|celtics|yankees|dodgers|cowboys|patriots|chiefs|eagles"
    r"|warriors|knicks|bulls|heat|bucks|suns|mavericks|raiders|broncos|packers"
    r"|steelers|ravens|bengals|browns|texans|colts|jaguars|titans|vikings|lions"
    r"|bears|falcons|saints|buccaneers|panthers|cardinals|rams|seahawks|49ers"
    r"|chargers|jets|giants|dolphins|bills"
    r"|movie|films?|tv\s+show|episode|album|concert|tour|grammy|oscar|emmy"
    r"|golden\s+globe|actor|actress|singer|rapper|celebrity|snl|saturday\s+night\s+live"
    r"|netflix|disney|marvel|starz|paramount|hulu|peacock|hbo|showtime|trailer|president|white\s+house|senate|congress|election"
    r"|minister|prime\s+minister|lobbyist|summit|protest|war|sports?|athlete"
    r"|nfl\.com|nhl\.com|nbcsports|yahoo\s+sports|fox\s+sports|cbs\s+sports"
    r"|the\s+athletic|bleacher\s+report|sporting\s+news|sports\s+illustrated|sky\s+sports"
    r"|variety|deadline|hollywood\s+reporter|tmz|billboard|rolling\s+stone|imdb"
    r"|pitchfork|nme|stereogum|consequence"
    # --- 2026-11-15 补：音乐节名（14:15 轮次 "camp flog gnaw 2026 lineup"
    #   漏网冲进热点第 3：4 词标题不触发人名规则，新闻源 Pitchfork、
    #   新闻标题含 Amazon Music 亦无否定词命中）---
    r"|flog\s+gnaw|coachella|lollapalooza|bonnaroo|stagecoach|rolling\s+loud|governors\s+ball"
    r"|politico|the\s+hill"
    # --- 2026-11-15 补：体育/天气/事故/娱乐/政治类通用词（之前只列了
    # 联赛与球队名，拦不住 game/vs/风暴/枪击这类热搜）---
    r"|game|games|match|matches|score|scores|scoring|vs|versus|win|wins|won|winning|loss|losses|beat|beats|beaten|championship|champions|tournament|tournaments|league|leagues|semifinal|quarterfinal|fixture|fixtures|race|racing|fight|fights|bout|knockout|upset|shutout|touchdown|homer|home\s+run|penalty|penalties|referee"
    r"|storm|storms|hurricane|hurricanes|tornado|tornadoes|earthquake|earthquakes|flood|floods|flooding|waves|tsunami|eruption|eruptions|blizzard|wildfire|wildfires|rain|rains|snow|snowfall|heatwave|heat\s+wave|cold\s+snap|drought|tormenta|lluvia|terremoto|huracán|inundación|sequía|sismo|nevada|volcano|volcanic|avalanche|landslide|typhoon|cyclone|monsoon"
    r"|shooting|shootings|crash|crashes|collision|death|deaths|died|dies|killed|killing|murder|murders|arrested|arrest|arrests|police|explosive|explosives|lawsuit|lawsuits|sued|explosion|blast|attack|attacks|attacked|hostage|missing|funeral|obituary|passed\s+away|stabbing|robbery|burglary|hijack|kidnap"
    # --- 2026-11-24 补：第 39 次漏网（本轮 "union nj fire"，首条新闻是 CBS
    #   "Union, New Jersey fire burns through row of stores"，新泽西州联合市
    #   商铺火灾新闻，新闻标题里的 "row of stores"（stores）既救回了人名规则
    #   （3 词标题 "union nj fire" 命中 GTRENDS_NAME_RE）、又通过了 gate，
    #   进了首页时间线。火灾事故新闻不是选品信号。只加火灾动词短语
    #   "fire burns/rips/tears/destroys/guts/engulfs/breaks out/damages"——
    #   裸词 fire 不加，Amazon Fire / Fire TV 等真实产品热搜不受影响；gate
    #   里的 store/stores 保留，真实零售店热搜不受影响。---
    r"|fire\s+(?:burns?|rips?|tears?|destroys?|guts?|engulfs?|breaks?\s+out|damages?|sparks?|erupts?|claims?|kills?|injures?)"
    # --- 2026-11-15 补：西语事故/娱乐词（12:15 轮次两条漏网均为西语标题：
    #   "la mansion vip" 是西语真人秀，"aeropuerto internacional de miami"
    #   是西语空难新闻，事故/娱乐词只有英文版拦不住）---
    r"|aeropuerto|colisi[oó]n|choque|accidente|avi[oó]n|heridos?|muertos?|fallecid[oa]s?|tiroteo|incendio|explosi[oó]n|desaparecid[oa]s?|secuestro"
    r"|mansi[oó]n|espect[aá]culos|telenovela|famoso|famosa|cantante|actriz|pel[ií]cula|estreno|concurso|gran hermano"
    r"|premiere|premieres|finale|finales|cast|director|producers?|novel|memoir|documentary|podcast|podcasts|chart|charts|song|songs|lyrics|hollywood"
    r"|vote|votes|voter|voters|ballot|ballots|poll|polls|polling|vice\s+president|senator|senators|congressman|congresswoman|governor|governors|mayor|mayors|parliament|cabinet|democrat|democrats|republican|republicans|liberal|liberals|conservative|conservatives|campaign|campaigns|rally|rallies|debate|debates|impeachment|court|judge|judges|supreme\s+court|verdict|indictment|subpoena|sanction|sanctions"
    # --- 2026-11-15 补：游戏名与航天新闻（14:45 轮次两条漏网冲进热点第 3、4：
    #   "when does gta 6 online come out"（Forbes，含 release 被商业词救回）、
    #   "spacex starship rocket launch"（CNN，含 launch 被商业词救回）。
    #   只加具体游戏名与航天专名，不加 xbox/playstation/nintendo——
    #   主机类热搜可能是真实选品信号（配件需求），靠打分沉底而非硬拦。---
    # --- 2026-11-16 补：金融类股票抛售（第 7 次漏网："greg abel berkshire
    #   hathaway stock sales"（Yahoo Finance），靠 gate 里的 sales 一词放行。
    #   只加 "stock sale(s)" 短语：裸词 stock 不能加，"in stock" 是产品信号；
    #   gate 里的 sales 保留，"holiday sales" 类购物热搜仍可通过。---
    # --- 2026-11-18 补：流媒体订阅类热搜（第 10 次漏网：本轮 "starz"，首条新闻
    #   是 Mashable 的 Paramount+ 黑五流媒体订阅折扣，新闻标题里的 black friday
    #   既救回了单字标题规则、又通过了 gate，冲进热点第 3。流媒体订阅折扣不是
    #   选品信号。只加品牌名（starz/paramount/hulu/peacock/hbo/showtime，与已
    #   有的 netflix/disney 同类）；裸词 streaming 不加——直播电商新闻里也会出
    #   现 streaming（如 TikTok live streaming sales），加了会误杀真实选品信号。
    #   代价：未列入的流媒体品牌（如 Crunchyroll）仍可能漏网，届时再补。---
    # --- 2026-11-18 补：名人穿搭导购类热搜（第 11 次漏网：本轮 "cox"，首条新闻
    #   是 People 的 Courteney Cox 穿搭文，标题尾 "Shop Similar Pieces" 里的
    #   shop 既救回了单字标题规则、又通过了 gate，冲进首页时间线。名人穿搭
    #   导购不是选品信号。只加 "shop similar / shop the look / shop the style"
    #   这类导购固定短语；裸词 shop 保留，真实购物热搜不受影响。---
    r"|shop\s+similar|shop\s+the\s+look|shop\s+the\s+style"
    r"|gta|grand\s+theft\s+auto|fortnite|minecraft|roblox|call\s+of\s+duty|zelda|elden\s+ring|genshin|honkai|overwatch|valorant|apex\s+legends|league\s+of\s+legends|world\s+of\s+warcraft|baldur'?s\s+gate"
    # --- 2026-11-18 补：应用商店类热搜（第 12 次漏网：本轮 "play store"，首条新闻
    #   是 Mercari 安卓应用从 Google Play Store 下架，标题/新闻里的 "store"
    #   一词通过了 gate。应用商店本身不是可售商品，相关热搜不是选品信号。
    #   只加 "play store / google play / app store" 三个短语；裸词 store 保留，
    #   真实零售店热搜不受影响。---
    r"|play\s+store|google\s+play|app\s+store"
    # --- 2026-11-18 补：召回类热搜（第 13 次漏网：本轮 "product recall"，首条新闻
    #   是 Fox Business 的降压药全国召回（疑似金属污染），标题里的 "product"
    #   一词通过了 gate，冲进热点第 11 位。召回是安全新闻，不是商品走红，
    #   更不是需求激增的选品信号。只加 recall/recalls/recalled；gate 里的
    #   product 保留，真实产品热搜不受影响。---
    r"|recall|recalls|recalled"
    # --- 2026-11-18 补：健康/环保榜单类热搜（第 14 次漏网：本轮 "toxic hall
    #   of shame"，首条新闻是 CNN 的年度有毒化学品 "Hall of Shame" 榜单，
    #   新闻标题里的 "Black Friday"（榜单赶在黑五前发布）通过了 gate，
    #   冲进热点第 11 位。健康环保榜单是倡导新闻，不是商品走红，更不是
    #   需求激增的选品信号。只加 "hall of shame" 固定短语；gate 里的
    #   black friday 保留，真实黑五购物热搜不受影响。---
    r"|hall\s+of\s+shame"
    # --- 2026-11-20 补：美妆颁奖榜单变体（第 19 次漏网：本轮 "jennifer
    #   lawrence"，首条新闻是 IMDb 的 "Jennifer Lawrence Rocks the Wet Hair
    #   Trend for Wwd's Beauty Inc Awards"，新闻标题里的 beauty 既救回了
    #   人名规则、又通过了 gate；"Beauty Inc Awards" 不含 "beauty awards"
    #   短语，旧规则拦不住。两处修：(1) "beauty award(s)" 扩展为
    #   "beauty (inc )award(s)"，覆盖 WWD Beauty Inc Awards；(2) 娱乐
    #   资讯源加 imdb——IMDb 是纯娱乐站，首条新闻出自 IMDb 的热搜基本是
    #   名人新闻，不是选品信号。gate 里的 beauty 保留，真实美妆爆款热搜
    #   不受影响。---
    r"|beauty\s+(?:inc\s+)?awards?"
    # --- 2026-11-19 补：宝可梦卡牌资讯站名类热搜（第 16 次漏网：本轮 "pokebeach"，
    #   首条新闻是 PokeBeach 的 "Gold & Silver TCG Products to Release Alongside
    #   Pokemon ex…"，新闻标题里的 "products" 既救回了单字标题规则、又通过了 gate，
    #   冲进热点第 2 位。热搜词本身是宝可梦卡牌资讯站名，不是商品名；资讯站名
    #   热搜不是选品信号。只加站名 "pokebeach"；gate 里的 products 保留，
    #   真实产品热搜不受影响。---
    r"|pokebeach"
    # --- 2026-11-19 补：房地产类热搜（第 17 次漏网：本轮 "housing"，首条新闻
    #   是 CNBC 的 "Two new housing reports point to bleak winter ahead, with
    #   record low sales"，新闻标题里的 "sales"（指房屋销量）既救回了单字标题
    #   规则、又通过了 gate，冲进首页时间线。房地产新闻不是选品信号。只加
    #   "housing"；gate 里的 sales 保留，真实购物热搜不受影响。---
    r"|housing"
    # --- 2026-11-19 补：外汇汇率类热搜（第 18 次漏网：本轮 "dolar hoje"，
    #   巴西雷亚尔兑美元汇率查询，首条新闻 UOL "Dólar fecha a R$ 5,87,
    #   maior valor em 19 meses; Ibovespa cai mais de 1%" 里的 "R$ 5,87"
    #   被 gate 的 $+数字规则当成价格信号放行。只加汇率市场专名
    #   （dolar/dólar/ibovespa/cotação）；裸词 euro 不加——另在 $ 规则上
    #   加前置字母否定（见 GTRENDS_GATE_RE / GTRENDS_COMMERCE_RE），
    #   让 R$/US$/A$ 这类货币符号报价不再算价格信号。---
    r"|dolar|dólar|ibovespa|cotaç[aã]o|cotacao|euro\s+hoje"
    # --- 2026-11-20 补：第 20、21 次漏网（本轮两条同进首页时间线）：
    #   \"regions\"——Reuters 首条新闻 \"More Russian regions limit fuel
    #   sales as Ukrainian drone strikes hit refinery\"，新闻标题里的
    #   \"sales\"（燃油限售）既救回了单字标题规则、又通过了 gate；通用名词
    #   regions 本身不是商品信号，与第 17 次漏网 \"housing\"（房屋销量新闻
    #   里的 sales）同一模式，只加 \"regions\"。
    #   \"warren buffett\"——CNBC 首条新闻 \"Warren Buffett donates $5.5
    #   billion…\"，捐款金额里的 \"$5.5\" 被 $+数字规则当成价格信号，既救回
    #   了人名规则、又通过了 gate。两处修：(1) 加人名 \"warren buffett\"
    #   （巴菲特/伯克希尔/捐款新闻，不是选品信号）；(2) 加捐款类词
    #   donat(e/es/ed/ing/ion/ions)——捐款新闻里的金额不是商品价格，今后
    #   \"X donates $Y\" 类热搜直接拦住。gate 里的 $+数字与 sales 保留，
    #   真实价格/销量热搜不受影响。---
    r"|regions|warren\s+buffett|donat(?:e|es|ed|ing|ion|ions)"
    # --- 2026-11-20 补：第 22 次漏网（本轮 "elise stefanik"，首条新闻是
    #   华盛顿邮报 "Stefanik family's DC home sells to mystery buyer for
    #   $900K over list price"，房屋售价里的 "$900K" 被 $+数字规则当成商品
    #   价格信号，既救回了人名规则、又通过了 gate，冲进热点第 3 位。政客
    #   人名热搜不是选品信号。只加姓氏 "stefanik"；gate 里的 $+数字保留，
    #   真实价格热搜不受影响。---
    r"|stefanik"
    # --- 2026-11-21 补：第 23、24 次漏网（本轮 "soxx"、"btc price"，同进
    #   热点第 6、7 位，均由 2026-11-21 00:48 轮次入库、05:45 轮次发现）：
    #   "soxx"——Benzinga "1000 Invested iShares PHLX SOX Semiconductor
    #   Sector Index Fund 15 Years Ago…"，投资回顾文，新闻标题里的 "$1,000"
    #   被 $+数字规则当成价格信号，既救回了单字标题规则、又通过了 gate；
    #   "btc price"——Motley Fool "Crypto Market Today: Bitcoin Approaches
    #   $60,000 as ETF Outflows Surpass $2.5 Billion"，新闻标题里的 "$60,000"
    #   同样被 $+数字规则放行。半导体 ETF 回顾与比特币行情都是金融新闻，
    #   不是选品信号。只加专名 soxx / bitcoin / btc 与通用词 etf（ETF
    #   本身是金融产品，不会是可售商品信号）；gate 里的 $+数字保留，真实
    #   价格热搜不受影响。---
    r"|soxx|bitcoin|btc|etf"
    # --- 2026-11-21 补：第 25 次漏网（本轮 "colin farrell"，首条新闻是
    #   PR Newswire "…Help Raise Over $3 Million For EB Research Partnership
    #   At New York Gala"，慈善晚会筹款新闻，标题里的 "$3 Million" 被 $+数字
    #   规则当成价格信号，既救回了人名规则、又通过了 gate，冲进热点第 5 位。
    #   与第 20、21 次漏网（warren buffett 捐款 $5.5 billion）同一模式，
    #   只是动词是 raise 不是 donate，donat 拦不住。只加人名 "colin farrell"
    #   与筹款类词 gala / fundrais… / "raise(s/d) (over) $数字"（晚会筹款、
    #   众筹募资新闻里的金额不是商品价格；"raises prices by $5" 这类中间隔
    #   了词的不命中）；gate 里的 $+数字保留，真实价格热搜不受影响。---
    r"|colin\s+farrell|gala|fundrais(?:e|es|ed|ing|er|ers)?|rais(?:e|es|ed|ing)\s+(?:over\s+)?\$"
    # --- 2026-11-21 补：第 26 次漏网（本轮 "kevin durant"，首条新闻是
    #   WSJ "Exclusive | Kevin Durant Lists U-Shaped Arizona House for $13.9
    #   Million"，豪宅挂牌价里的 "$13.9" 被 $+数字规则当成商品价格信号，
    #   既救回了人名规则、又通过了 gate，冲进热点第 5 位。与第 22 次漏网
    #   "elise stefanik"（政客住宅以高于挂牌价 $900K 售出）同一模式：名人
    #   豪宅挂牌/售出新闻不是选品信号。只加人名 "kevin durant"；gate 里的
    #   $+数字保留，真实价格热搜不受影响。---
    r"|kevin\s+durant"
    # --- 2026-11-21 补：第 27 次漏网（本轮 "ken griffin"，首条新闻是
    #   Pittsburgh Post-Gazette "Carnegie museum receives $5M gift and 3
    #   rare dinosaurs from Ken Griffin"，捐赠金额 "$5M" 被 $+数字规则当成
    #   商品价格信号，既救回了人名规则（新闻标题里的 gift 也在救援词表
    #   里）又通过了 gate，冲进热点第 3 位。与第 20、21 次 "warren buffett"
    #   （捐款 $5.5 billion）与第 25 次 "colin farrell"（筹款 $3 Million）
    #   同一模式：名人捐赠新闻里的金额不是商品价格。只加人名
    #   "ken griffin"；gate 里的 $+数字保留，真实价格热搜不受影响。---
    r"|ken\s+griffin"
    # --- 2026-11-21 补：第 28 次漏网（本轮 5 条黑五 deals 查询同进热点 20：
    #   "best tech black friday deals" 第 3、"apple black friday deals 2026"
    #   第 5、"nintendo switch 2 black friday deals" 第 7、"black friday sale
    #   deals" 第 10、"biggest black friday deals" 第 15，另有 11-15 入库的
    #   同题旧条。均为无具体商品的通用导购榜单查询（Wirecutter/CNN/NBC 等
    #   deals 汇总），靠 gate 里的 black friday 一词放行；黑五季 Trends 日榜
    #   本来就以这类查询为主。只加 "black friday (sale )deals" 固定模式：
    #   品牌/零售商专指查询（apple black friday、lego black friday、
    #   target/home depot black friday 2026）不含 deals，不受影响；裸词
    #   black friday 仍可通过 gate，购物季信号保留。---
    r"|black\s+friday(?:\s+\w+)?\s+deals"
    # --- 2026-11-21 补：第 29 次漏网（本轮 "costco thanksgiving holiday
    #   store closures"，首条新闻是 TheStreet "Costco Makes a Tough Store
    #   Closure Decision"，靠 gate 里的 costco 与 store 两词放行，冲进热点
    #   第 2 位。零售商节假日闭店/关店是门店运营新闻，没有商品、没有折扣、
    #   没有需求信号，不是选品信号。只加 "store closure(s)" 固定短语；
    #   gate 里的 costco 与裸词 store 保留，真实零售购物热搜不受影响。---
    r"|store\s+closures?"
    # --- 2026-11-22 补：第 30、31 次漏网（本轮 "unemployment"、"nordvpn"
    #   同进热点第 10、11 位，均由 2026-11-22 17:35 轮次入库）：
    #   "unemployment"——KTLA 首条新闻 "Southern California duo stole
    #   $2.1 million in unemployment benefits"，失业救济金诈骗案涉案金额
    #   "$2.1" 被 $+数字规则当成价格信号，既救回了单字标题规则、又通过了
    #   gate。只加 "unemployment"；gate 里的 $+数字保留，真实价格热搜不
    #   受影响。
    #   "nordvpn"——Gizmodo 首条新闻 "NordVPN at $2.99 a Month Costs Less
    #   Than Your Airport Coffee This Thanksgiving"，黑五 VPN 订阅折扣文，
    #   "$2.99" 同样被 $+数字规则放行。VPN 是数字订阅服务，不是跨境实物
    #   商品，订阅折扣不是选品信号。加裸词 vpn 与四大品牌名
    #   nordvpn/expressvpn/surfshark/protonvpn；gate 里的 $+数字保留。
    #   代价：极小众的 "vpn router" 这类硬件热搜也会被拦，接受这点损失。---
    r"|unemployment|vpn|nordvpn|expressvpn|surfshark|protonvpn"
    # --- 2026-11-23 补：第 32 次漏网（本轮 "cnbc make it"，首条新闻是 CNBC
    #   Make It "Google worker earns $323,000 a year but he lives on minimum
    #   wage"，薪资/个人理财故事，新闻标题里的 "$323,000" 被 $+数字规则当成
    #   价格信号放行，冲进热点第 9 位。同 #30（"$2.1 million" 失业救济金
    #   诈骗案）、#31（"$2.99 a month" VPN 折扣）一样是 $+数字误放。
    #   只加薪资故事固定模式 "earns $X a year" 与 "minimum wage"；
    #   gate 里的 $+数字保留，真实价格热搜不受影响。---
    r"|earns?\s+\$?[\d,]+\s+a\s+year|minimum\s+wage"
    # --- 2026-11-23 补：第 33 次漏网（本轮 "bill hader"，首条新闻是 Digg
    #   "The Cat in the Hat's latest trick is a reported $70 million
    #   worldwide"，电影票房新闻，票房金额 "$70 million" 被 $+数字规则当成
    #   商品价格信号，既救回了人名规则、又通过了 gate，冲进热点第 8 位。
    #   同 #20/21（warren buffett 捐款 $5.5 billion）、#22（stefanik 豪宅
    #   $900K）、#25（colin farrell 筹款 $3 Million）一样是新闻标题里的
    #   $ 金额误放。只加人名 "bill hader"；gate 里的 $+数字保留，真实价格
    #   热搜不受影响。---
    r"|bill\s+hader"
    # --- 2026-11-23 补：第 34 次漏网（本轮 "copper price"，首条新闻是
    #   Bloomberg "Copper Wavers Near $12,000 a Ton After Meltdown on AI
    #   Jitters"，大宗商品铜价新闻，标题里的 "$12,000" 被 $+数字规则当成
    #   商品价格信号放行，进了首页时间线。同 #30（失业救济金 "$2.1
    #   million"）、#31（VPN "$2.99"）、#32（年薪 "$323,000"）、#33
    #   （票房 "$70 million"）一样是新闻标题里的 $ 金额误放。只加
    #   "X price" 形式的大宗商品价格短语（金属、能源、农产品），gate 里
    #   的 $+数字保留，真实商品价格热搜不受影响。---
    r"|(?:copper|gold|silver|platinum|palladium|alumin[iu]m|nickel|zinc|tin|lead|iron\s+ore|crude\s+oil|brent|natural\s+gas|wheat|corn|soybean|soybeans|coffee|cocoa|lithium|cobalt)\s+prices?"
    # --- 2026-11-23 补：第 35 次漏网（未遂，本轮第二遍抓取时 feed 里出现
    #   "musk foundation"，首条新闻是 Fortune "Elon Musk's $16 billion
    #   foundation gave away $400 million in 2025, mostly to another Musk
    #   nonprofit"，基金会捐款新闻，标题里的 "$16 billion / $400 million"
    #   被 $+数字规则当成商品价格信号放行。与 #20/21（warren buffett 捐款
    #   $5.5 billion）同一模式，只是动词是 "gave away" 而非 "donates"，
    #   donat 拦不住。在入库前于 feed 阶段拦下，未进 store。只加
    #   "musk foundation" 与 "gave away $数字" 模式；gate 里的 $+数字保留，
    #   真实价格热搜不受影响。---
    r"|musk\s+foundation|gav(?:e|ing)\s+away\s+\$"
    # --- 2026-11-24 补：第 36 次漏网（本轮 "accountant"，首条新闻是 KTLA
    #   "Los Angeles accountant sentenced for stealing more than $1.7M from
    #   indie films"，影业会计挪用公款被判刑的犯罪新闻，新闻标题里的 "$1.7M"
    #   被 $+数字规则当成商品价格信号，既救回了单字标题规则、又通过了 gate，
    #   进了首页时间线。同 #30（失业救济金诈骗 "$2.1 million"）、#32（年薪
    #   "$323,000"）、#33（票房 "$70 million"）一样是新闻标题里的 $ 金额误放。
    #   两处修：(1) 加职业词 "accountant"（会计职业热搜不是选品信号）与犯罪
    #   判决类词 sentenced/embezzle/steal/stole/fraud/convicted——犯罪新闻里
    #   的涉案金额不是商品价格；(2) 顺手把娱乐行的 film 扩展为 films?，复数
    #   "indie films" 之前从 \bfilm\b 的词界漏过。gate 里的 $+数字保留，
    #   真实价格热搜不受影响。---
    r"|accountant|sentenced|embezzl\w*|stea(?:l|ls|ling)|stol(?:e|en)|fraud|convict(?:ed|ion|ions)?"
    # --- 2026-11-24 补：第 37 次漏网（本轮 "student loans news"，首条新闻是
    #   SILive "NY offers up to $50k in student loan forgiveness — here's who
    #   can apply"，纽约州助学贷款减免新闻，新闻标题里的 "$50k" 被 $+数字规则
    #   当成商品价格信号放行，进了首页时间线。同 #30（失业救济金 "$2.1
    #   million"）、#32（年薪 "$323,000"）一样是新闻标题里的 $ 金额误放。
    #   只加 "student loan(s)" 与 "loan forgiveness"（助学贷款减免新闻不是
    #   选品信号）；gate 里的 $+数字保留，真实价格热搜不受影响。---
    # --- 2026-11-24 补：第 38 次漏网（本轮 "ticket"，首条新闻是 NY Post
    #   "LIRR riders sharing phone location get $8 ticket warnings — despite
    #   claims of no tracking"，长岛铁路乘客因分享位置收 $8 罚单提醒的交通
    #   执法新闻，新闻标题里的 "$8" 被 $+数字规则当成商品价格信号，既救回
    #   了单字标题规则、又通过了 gate，进了首页时间线。同 #30（失业救济金
    #   "$2.1 million"）、#32（年薪 "$323,000"）、#33（票房 "$70
    #   million"）一样是新闻标题里的 $ 金额误放。只加裸词 "ticket"（活动/
    #   交通票务热搜不是选品信号——演唱会票、机票、火车票都不是跨境卖家可
    #   售的实物商品）；gate 里的 $+数字保留，真实价格热搜不受影响。---
    r"|ticket"
    r"|student\s+loans?|loan\s+forgiveness"
    # --- 2026-11-24 补：第 41 次漏网（本轮 "natalie portman"，首条新闻是
    #   InStyle 的 Natalie Portman 冬季 loungewear 穿搭文（Oprah 推荐款），
    #   新闻标题里的导购词（shop/fashion/gift guide 类）既救回了人名规则、
    #   又通过了 gate，冲进热点第 7 位。同 #33（bill hader 电影票房新闻）、
    #   #40（lexie hull WNBA 球员生活方式专栏）一样是名人热搜：名人穿搭
    #   导购不是选品信号。只加人名 "natalie portman"；gate 里的导购词保留，
    #   真实产品热搜不受影响。---
    r"|natalie\s+portman"
    # --- 2026-11-25 补：第 42 次漏网（本轮 "dell earnings"，首条新闻是
    #   Trefis "Over Half of Dell's $95 Billion Backlog Waits…"，财报新闻，
    #   新闻标题里的 "$95" 被 $+数字规则当成商品价格信号，既救回了人名规则
    #   （2 词标题 "dell earnings" 命中 GTRENDS_NAME_RE）、又通过了 gate，
    #   冲进热点第 7 位、进了首页时间线。同 #30（失业救济金 "$2.1
    #   million"）、#32（年薪 "$323,000"）、#33（票房 "$70 million"）、
    #   #34（铜价 "$12,000"）、#36（会计挪用 "$1.7M"）一样是新闻标题里的
    #   $ 金额误放。只加裸词 "earnings"——公司财报新闻（Dell/HP/英伟达等
    #   季度财报）是金融新闻，不是选品信号；gate 里的 $+数字保留，真实
    #   商品价格热搜不受影响。代价：极少数以财报新闻为主的产品商热搜
    #   （如 Pop Mart 财报）也会被拦，接受这点损失。---
    r"|earnings"
    # --- 2026-11-25 补：第 43 次漏网（本轮 "boeing 737 max"，首条新闻是
    #   Reuters "China Southern Airlines unit buy 50 Boeing 737-8 aircraft"，
    #   南航子公司订购 50 架波音 737-8 客机的航空业新闻，新闻标题里的商业词
    #   既救回了人名规则、又通过了 gate，冲进热点第 3 位。同 #30（失业救济金
    #   "$2.1 million"）、#32（年薪 "$323,000"）、#33（票房 "$70
    #   million"）、#34（铜价 "$12,000"）、#36（会计挪用 "$1.7M"）一样是
    #   新闻标题里的商业词误放。只加裸词 "boeing"——波音客机是航空器，不
    #   是跨境卖家可售的实物商品；gate 里的商业词保留，真实商品热搜不受
    #   影响。---
    r"|boeing"
    # --- 2026-11-25 补：第 44 次漏网（本轮 "fatima bosch"，首条新闻是
    #   Yahoo "Fátima Bosch embraces romantic pink eyeshadow for an elegant
    #   Miss Universe 2026 beauty look"，环球小姐 2026 冠军的妆容新闻，新闻
    #   标题里的 "beauty" 既救回了人名规则、又通过了 gate，冲进热点第 4 位。
    #   同 #19（jennifer lawrence，Beauty Inc Awards）、#41（natalie
    #   portman，名人穿搭导购）一样是名人热搜：选美冠军妆容新闻不是选品
    #   信号。只加人名 "fatima bosch"；gate 里的 beauty 保留，真实美妆爆款
    #   热搜不受影响。---
    r"|fatima\s+bosch"
    # --- 2026-11-25 补：第 45 次漏网（本轮 "when is thanksgiving 2026"，首条新闻是
    #   WRAL "stores open on thanksgiving"，新闻标题里的 "stores" 通过了 gate，
    #   冲进热点。感恩节日期查询 + 本地门店营业时间新闻，没有商品、没有折扣、
    #   没有需求信号，不是选品信号。同 #29（"costco thanksgiving holiday store
    #   closures"，当时只加了 "store closures" 短语）一样是感恩节门店营业类
    #   热搜的变体。只加 "when is thanksgiving" 固定短语；gate 里的 stores 与
    #   black friday 保留，真实购物季热搜不受影响。---
    r"|when\s+is\s+thanksgiving"
    # --- 2026-11-25 补：第 46 次漏网（本轮 "hailey bieber nyt interview"，首条新闻是
    #   BoF "Hailey Bieber, Rhode, DealBook…"，名人访谈/美妆品牌创始人专访，新闻标题
    #   里的 "dealbook" 含 "deal" 子串，被当成商业信号，既救回了人名规则、又通过
    #   了 gate，冲进热点第 15 位、进了首页时间线。同 #19（jennifer lawrence，
    #   Beauty Inc Awards）、#41（natalie portman，名人穿搭导购）、#44
    #   （fatima bosch，选美冠军妆容）一样是名人热搜：名人访谈不是选品信号。
    #   只加人名 "hailey bieber"；gate 里的 deal 保留，真实折扣/交易热搜不受
    #   影响。---
    r"|hailey\s+bieber"
    # --- 2026-11-25 补：第 47 次漏网（本轮 "vix"，首条新闻是 TradingView
    #   "MKTS: VIX 31.64, +18.6%; NASDAQ -3.47%; S&P -2.4%; DJIA -1.5%; …
    #   WTI $83.50, +1.6%; NVDA -7.18%/$144"，美股市场综述，新闻标题里的
    #   "WTI $83.50"（原油报价）被 $+数字规则当成商品价格信号，既救回了
    #   单字标题规则、又通过了 gate，冲进热点第 15 位、进了首页时间线。
    #   同 #30（失业救济金 "$2.1 million"）、#32（年薪 "$323,000"）、
    #   #33（票房 "$70 million"）、#34（铜价 "$12,000"）、#36（会计
    #   挪用 "$1.7M"）、#42（戴尔财报 "$95 Billion"）一样是新闻标题里
    #   的 $ 金额误放。只加这条市场综述里出现的股指/原油专名
    #   vix / nasdaq / djia / wti——波动率指数、股指与原油基准都是金融
    #   行情，不是选品信号；gate 里的 $+数字保留，真实价格热搜不受影响。---
    r"|vix|nasdaq|djia|wti"
    # --- 2026-11-26 补：第 48 次漏网（本轮 "is cvs open on thanksgiving"，首条新闻是
    #   KHOU "Texas stores open on Thanksgiving 2026"，感恩节当天门店营业时间新闻，
    #   新闻标题里的 "stores" 通过了 gate，冲进热点第 20 位。同 #45（"when is
    #   thanksgiving 2026"，WRAL "stores open on thanksgiving"）与 #29（"costco
    #   thanksgiving holiday store closures"）一样是感恩节门店营业类热搜的变体：
    #   节假日门店开门/闭店时间查询没有商品、没有折扣、没有需求信号，不是选品信号。
    #   只加 "open on thanksgiving" 固定短语——"is X open on thanksgiving"、
    #   "stores open on thanksgiving" 等变体一并拦住；gate 里的 stores 与
    #   "thanksgiving sale" 保留，真实购物季热搜不受影响。---
    r"|open\s+on\s+thanksgiving"
    # --- 2026-11-26 补：第 49 次漏网（本轮 "oregon coast"，首条新闻是 KGW
    #   "Cannon Beach man, dog swept by king tide sneaker wave"，海滩突发新闻，
    #   新闻标题里的 "sneaker wave"（一种海岸大浪现象）误触 gate 里的 sneaker
    #   商业词而放行，冲进热点第 16 位。地名热搜没有商品、没有需求信号，不是
    #   选品信号。只加 "oregon coast" 与 "sneaker wave" 两个固定短语；gate
    #   里的 sneaker 保留，真实运动鞋热搜不受影响。---
    r"|oregon\s+coast|sneaker\s+wave"
    # --- 2026-11-26 补：第 50 次漏网（本轮 "trump account for kids"，首条新闻是
    #   Independent Record "Tech billionaire couple gives a total of $22M to
    #   thousands of Montana children"，富豪夫妇向蒙大拿州儿童的"特朗普账户"
    #   （政府儿童储蓄账户计划）捐款 $22M，新闻标题里的 "$22M" 被 $+数字规则当成
    #   商品价格信号，既救回了人名规则（3 词标题命中 GTRENDS_NAME_RE）、又通过
    #   了 gate，进了首页时间线。同 #35（musk foundation gave away $400
    #   million）、#20/21（warren buffett 捐款 $5.5 billion）一样是捐款新闻里
    #   的 $ 金额误放。两处修：(1) 加专名 "trump account"（政府儿童储蓄账户
    #   计划，不是可售商品）；(2) 加捐款固定短语 "gives a total of $"，覆盖
    #   "X gives a total of $Y to …" 式捐款句式；gate 里的 $+数字保留，真实
    #   价格热搜不受影响。---
    r"|trump\s+account|gives?\s+a\s+total\s+of\s+\$"
    r"|spacex|starship|nasa|astronaut|astronauts|rocket\s+launch|space\s+launch|spacecraft|falcon\s+9|falcon\s+heavy|blue\s+origin|stock\s+sales?)\b",
    re.I)

# 2026-11-15 修复：否定词拦不住纯人名/地名/单字姓氏（mel gibson、
# michael j fox、serbia、lindstrom 等 15 条全部漏网，占据热点 60%）。
# 补三条只看标题的规则（新闻正文只用来救产品名）：
#   GTRENDS_NAME_RE：2–3 个单词的人名/片名类标题（如 Mel Gibson、
#     Michael J Fox、Dallas Love Field），且新闻里没有商业信号词 -> 否定；
#     新闻里有 price/launch/sale 等商业词时放行（Apple Watch Ultra、
#     Galaxy Z Fold 这类产品名靠新闻救回来）。Trends 标题常为小写，故 re.I。
#   GTRENDS_PLACE_RE：整个标题就是一个国家/地区名 -> 否定。
#   单词标题：新闻里没有商业信号词 -> 否定（lindstrom 这类单姓；
#     Labubu、Skims 这类单字产品名新闻里通常有 sold out/launch，不会误伤）。
#   GTRENDS_SHOPPING：购物节例外（Black Friday、Cyber Monday、Prime Day…），
#     不受人名规则影响。
GTRENDS_NAME_RE = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.?| [A-Z][a-z]+){1,2}$", re.I)
GTRENDS_PLACE_RE = re.compile(r"^(?:afghanistan|albania|algeria|argentina|armenia|australia|austria|azerbaijan|bangladesh|belarus|belgium|bolivia|bosnia|brazil|bulgaria|cambodia|canada|chile|china|colombia|croatia|cuba|cyprus|denmark|ecuador|egypt|estonia|ethiopia|finland|france|georgia|germany|ghana|greece|greenland|guatemala|haiti|honduras|hong kong|hungary|iceland|india|indonesia|iran|iraq|ireland|israel|italy|jamaica|japan|jordan|kazakhstan|kenya|kuwait|kyrgyzstan|latvia|lebanon|libya|lithuania|luxembourg|madagascar|malaysia|mali|malta|mexico|moldova|mongolia|morocco|myanmar|nepal|netherlands|nicaragua|niger|nigeria|norway|oman|pakistan|palestine|panama|paraguay|peru|philippines|poland|portugal|qatar|romania|russia|rwanda|senegal|serbia|singapore|slovakia|slovenia|somalia|south africa|south korea|spain|sri lanka|sudan|sweden|switzerland|syria|taiwan|tajikistan|tanzania|thailand|togo|tunisia|turkey|turkmenistan|uganda|ukraine|uruguay|uzbekistan|venezuela|vietnam|yemen|zambia|zimbabwe|gaza|kashmir|north korea|puerto rico)$", re.I)
# 2026-11-19 修复：$+数字规则原来写在 \b(?:...) 组里，\b 要求 $ 前是
# 词字符，于是 "costs $5" 这类真价格永远匹配不上，反而只有 "R$ 5,87"
# 这类货币符号报价能匹配（第 18 次漏网 dolar hoje 的根因）。现把
# $ 分支移出 \b 组，并加前置字母否定：独立 $+数字算价格信号，
# R$/US$/A$/C$ 等货币符号报价不算（A$AP Rocky 的旧修复仍成立）。
GTRENDS_COMMERCE_RE = re.compile(r"(?:(?<![A-Za-z])\$\s*\d|\b(?:price|prices|pricing|sale|sales|deal|deals|discount|discounts|coupon|coupons|launch|launches|launched|release|releases|released|preorder|pre-order|buy|buys|buying|shop|shopping|store|stores|restock|restocked|sold\s+out|review|reviews|unboxing|viral|goes\s+viral|craze|frenzy|tiktok|instagram|influencer|influencers|amazon|walmart|target|costco|shein|temu|ebay|etsy|shopify|brand|brands|product|products|gadget|gadgets|toy|toys|fashion|beauty|skincare|makeup|sneaker|sneakers|shoes|electronics|gaming|console|gift|gifts|haul|christmas|holiday\s+shopping|black\s+friday|cyber\s+monday|prime\s+day|singles\s+day|small\s+business\s+saturday)\b)", re.I)
GTRENDS_SHOPPING = {"black friday", "cyber monday", "prime day", "prime big deal days", "singles day", "small business saturday"}

# 2026-11-15 商业词门槛（gate，用户在 Trends 第 4 次漏网后拍板）：
# 否定词是"黑名单"，gate 是"白名单"——走到这一步还没被拦的条目，
# 只有标题/新闻/来源里带强商业词才放行。gate 词表故意比救援词表
# GTRENDS_COMMERCE_RE 严得多，后者只做人名规则的救援，本来就该宽松，
# 保持原样不动。
# 明确没放进 gate 的词：launch、release、review、viral、deal、price、
# 2026-11-15 第 5 次漏网："people magazine"（Rihanna 之子登封面娱乐新闻）
#   靠新闻标题里的 "A$AP Rocky" 漏进来——\$ 被当成价格信号，救回了人名规则
#   又通过了 gate。修复：\$ 只有后跟数字时才算价格信号（$99），"A$AP"
#   这类艺名拼写不再触发。
# pricing、amazon（裸词）、target（裸词）、brand、christmas、
# tiktok（裸词）、instagram、influencer、gaming——这些词会出现在
# 火箭/电影/游戏/政治/物价新闻里：GTA 6 靠 release、SpaceX 靠 launch
# 就是这么漏进来的。代价：Apple Watch Ultra / iPhone 17 Pro /
# Galaxy Z Fold 这类只有 price/release/review 的产品名会被拦，
# 它们本来也会经由其余 32 个源进来，接受这点损失。
# 2026-11-16 第 6 次漏网：\"adam devine\"（Adam Devine 谈“最差节日礼物”
# 娱乐新闻）靠新闻标题里的裸词 gift 救回人名规则又通过 gate。
# 修复：裸词 gift/gifts 移出 gate（GTRENDS_COMMERCE_RE 救援词表里保留，
# 人名规则仍可被救回，但最后的 gate 会拦住——deny-gate）。
# 但 gift guide / gift ideas / gift set / gift box / best gift 这类
# 明确的购物短语留在 gate 里，礼物指南类选品信号不至于全灭。
# 代价：新闻里只有裸词 gift 的纯礼物话题会被拦，接受这点损失，
# 礼物类选品信号仍可经其余 32 个源进来。
# 2026-11-17 第 9 次漏网："tara harding ford bronco purchase"（CBS：女子买下
# Ford Bronco、航班停飞后开车 27 小时回家的人情味新闻）靠新闻标题里的
# buys 通过 gate，冲进热点第 4 位。买/卖车的一次性个人消费故事不是选品
# 信号。修复：buy/buys/buying 移出 gate（GTRENDS_COMMERCE_RE 救援词表里
# 保留，人名规则仍可被救回，但最后的 gate 会拦住——deny-gate）。
# 代价：新闻里只有 buy/buys 的纯购买话题会被拦（如 "everyone is buying
# the Stanley Cup"），接受这点损失，购物类信号仍可经其余 32 个源进来；
# 真正的爆款通常还带 sale / sold out / restock / viral / tiktok shop 等
# 更强的词，不受影响。
# 2026-11-19 修复（同 GTRENDS_COMMERCE_RE）：$+数字原来在 \b 组里，
# 真价格 "costs $5" 匹配不上，只有 "R$ 5,87" 货币报价能过（第 18 次
# 漏网 dolar hoje 根因）。$ 分支移出 \b 组 + 前置字母否定。
GTRENDS_GATE_RE = re.compile(
    r"(?:(?<![A-Za-z])\$\s*\d|\b(?:sale|sales|discount|discounts|coupon|coupons|preorder|pre-order"
    r"|shop|shopping|store|stores|restock|restocked|sold\s+out"
    r"|unboxing|haul|walmart|costco|shein|temu|ebay|etsy|shopify|tiktok\s+shop"
    r"|sneaker|sneakers|gadget|gadgets|toy|toys|fashion|beauty|skincare|makeup"
    r"|shoe|shoes|electronics|console|product|products"
    r"|gift\s+ideas|gift\s+guide|gift\s+set|gift\s+box|best\s+gifts?"
    r"|holiday\s+shopping|black\s+friday|cyber\s+monday|prime\s+day"
    r"|prime\s+big\s+deal\s+days|singles\s+day|small\s+business\s+saturday"
    r"|in\s+stock|clearance|bestseller|best\s+seller)\b)",
    re.I)


def gtrends_verdict(title, news_title="", news_source=""):
    """一条 Trends 热搜的去留（供测试与 scrape_gtrends 共用）。
    返回 None 表示保留，否则返回命中的规则名。"""
    joined = " ".join([title, news_title, news_source])
    if GTRENDS_DENY.search(joined):
        return "deny-word"
    # 2026-11-16 补：股票代码类热搜（第 8 次漏网："walmart stock"，Yahoo Finance
    #   沃尔玛 Q3 财报新闻，靠 gate 里的裸词 walmart 放行；第 7 次是
    #   "greg abel berkshire hathaway stock sales"，只拦了 stock sales。
    #   标题里出现独立单词 stock（如 walmart stock、tesla stock、stock market）
    #   是查股价/股市新闻，不是选品信号；"in stock / out of stock / low stock"
    #   是缺货信号，不拦；restock 不含独立 stock，不受影响。只看标题，不看
    #   新闻标题——新闻里提股价（如 Pop Mart stock）不应连累产品热搜。）
    if (re.search(r"\bstock\b", title, re.I)
            and not re.search(r"\b(?:in|out of|low)\s+stock\b", title, re.I)):
        return "deny-stock"
    # 西语动词 sale（"sale de …" = 离开）会误触英文商业词 sale 而放行
    # 人名/片名（如 La Mansión VIP），救援判断前先去掉 "sale de"。
    # "amazon music" 也去掉：音乐直播不是购物信号，否则
    # "Camp Flog Gnaw … Amazon Music Livestream" 会被 amazon 一词救回。
    joined_rescue = re.sub(r"\bsale\s+de\b", " ", joined, flags=re.I)
    joined_rescue = re.sub(r"\bamazon\s+music\b", " ", joined_rescue, flags=re.I)
    # 2026-11-15 补：标题含 lineup 且新闻无商业词 -> 否定（音乐节阵容类
    # 热搜，如 camp flog gnaw / coachella 阵容公布；产品线阵容如
    # "iPhone 17 lineup" 新闻里通常有 price/launch/release，会被救回）。
    if re.search(r"\blineup\b", title, re.I) and not GTRENDS_COMMERCE_RE.search(joined_rescue):
        return "deny-lineup"
    if (title.lower() not in GTRENDS_SHOPPING
            and GTRENDS_NAME_RE.match(title)
            and not GTRENDS_COMMERCE_RE.search(joined_rescue)):
        return "deny-name"
    if GTRENDS_PLACE_RE.match(title):
        return "deny-place"
    if len(title.split()) == 1 and not GTRENDS_COMMERCE_RE.search(joined_rescue):
        return "deny-single"
    # 2026-11-15 商业词门槛：上面都没拦住的条目，最后看有没有强商业词。
    # 购物节例外（GTRENDS_SHOPPING）不受此限。
    if (title.lower() not in GTRENDS_SHOPPING
            and not GTRENDS_GATE_RE.search(joined_rescue)):
        return "deny-gate"
    return None


def scrape_gtrends():
    """Google Trends 美国日榜 RSS，拉官方 RSS 后否定词过滤。

    为什么不在 sources.json 里直接挂 RSS：官方 RSS 所有条目共用同一个
    link（https://trends.google.com/trending/rss?geo=US），而 generate.py
    按链接去重，直接入库 10 条会塌成 1 条；且泛热搜（体育/名人/影视）
    占大多数，必须按源过滤——generate.py 没有按源过滤机制（noise 词是
    全局的，只扣分不排除）。所以在这里拉 RSS、过滤、重写成本地 feed：
    标题取热搜词，链接取首条新闻链接（每条唯一），时间取 pubDate。
    只有首条新闻链接缺失的条目才跳过。
    """
    raw = fetch("https://trends.google.com/trending/rss?geo=US")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    ns = {"ht": "https://trends.google.com/trending/rss"}
    raw_items = list(root.iter("item"))
    if not raw_items:
        # RSS 本身一条都没有：说明源结构变了或返回空壳，抛错走旧文件保护，
        # 不要把空文件写出去。
        raise RuntimeError("trends RSS has no items")
    out, seen = [], set()
    for el in raw_items:
        title = (el.findtext("title") or "").strip()
        if len(title) < 2:
            continue
        link = ""
        news_title = ""
        news_source = ""
        for ni in el.findall("ht:news_item", ns):
            u = ni.findtext("ht:news_item_url", namespaces=ns) or ""
            if u.strip():
                link = u.strip()
                news_title = ni.findtext("ht:news_item_title", namespaces=ns) or ""
                news_source = ni.findtext("ht:news_item_source", namespaces=ns) or ""
                break
        if not link or link in seen:
            continue
        if gtrends_verdict(title, news_title, news_source):
            continue
        pub = None
        pd = (el.findtext("pubDate") or "").strip()
        if pd:
            try:
                pub = datetime.strptime(pd, "%a, %d %b %Y %H:%M:%S %z").astimezone(CST)
            except ValueError:
                pub = None
        seen.add(link)
        out.append((title, link, pub))
    return out


SITES = [
    ("ebrun", "亿邦动力", "https://www.ebrun.com/", scrape_ebrun_fixed),
    ("cifnews", "雨果网", "https://www.cifnews.com/", scrape_cifnews),
    ("dsb", "电商报", "https://www.dsb.cn/", scrape_dsb),
    ("mjzj", "卖家之家", "https://www.mjzj.com/", scrape_mjzj),
    ("gtrends", "Google Trends 美国热搜", "https://trends.google.com/trending/rss?geo=US", scrape_gtrends),
    ("nichehunter", "NicheHunter TikTok 热销", "https://nichehunter.com/tools/winning-product-finder/", scrape_nichehunter),
    ("jadeship", "JadeShip 1688 七日榜", "https://www.jadeship.com/feed/top/7-days/1688", scrape_jadeship),
    ("sellersprite", "卖家精灵博客", "https://www.sellersprite.com/cn/blog/", scrape_sellersprite),
    ("sellthetrend", "Sell The Trend 爆款榜", "https://www.sellthetrend.com/blog/winning-products", scrape_sellthetrend),
    ("tokconnect-rising", "TokConnect TikTok Shop 涨幅榜", "https://tokconnect.com/trends/tiktok-shop/rising-products/", scrape_tokconnect_rising),
    ("tokconnect-breakout", "TokConnect TikTok Shop 新品爆发榜", "https://tokconnect.com/trends/tiktok-shop/breakout-products/", scrape_tokconnect_breakout),
    ("tokconnect-search", "TokConnect TikTok 搜索榜", "https://tokconnect.com/trends/products/", scrape_tokconnect_search),
    ("chanmama-yyq", "蝉妈妈抖音销量周榜", "https://www.chanmama.com/yunyingquan/", scrape_chanmama),
]

# 本轮抓到少于多少条时保留旧文件（默认 3；gtrends 是日榜快照，
# 过滤后剩 0-2 条是正常情况（美国日榜常被体育/名人占满），0 条也写文件，
# 表示“今天没有产品类热搜”，不让旧榜单多留一天；只有拉取本身失败时才保旧文件）。
MIN_KEEP = {"gtrends": 0}


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
        need = MIN_KEEP.get(sid, 3)
        if len(items) < need:
            print(f"{sid}: only {len(items)} items, keeping old file", flush=True)
            results[sid] = len(items)
            continue
        write_rss(os.path.join(FEED_DIR, sid + ".xml"), name, link, items)
        print(f"{sid}: {len(items)} items -> data/feeds/{sid}.xml", flush=True)
        results[sid] = len(items)
        time.sleep(2)
    print("done:", results)
    return 0 if all(v >= MIN_KEEP.get(k, 3) for k, v in results.items()) else 1


if __name__ == "__main__":
    sys.exit(main())
