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

用法：python3 tools/scrape_cn.py   （在站点根目录运行）
"""
import html
import json
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


# Google Trends 泛热搜否定词：体育、娱乐、政治类标记词（词边界匹配）。
# 榜单是英文热搜词，人名本身无法枚举，所以同时看标题、首条新闻标题、
# 新闻来源三处；命中即丢弃。注意：故意没放 game / series / season /
# coach / trial / player 这些词——它们常出现在真实商品趋势里
# （游戏机、产品系列、季节性商品、Coach 品牌、free trial、
# 播放器），放进来会误杀产品信号。残留的人名类热搜（如纯人名，无任何
# 体育/娱乐标记词）仍可能漏进来，需在精选环节靠打分自然沉底。
# 美式球队昵称、trade、stadium、troops 也在列：球队人名类热搜常以
# 交易流言（"XXX trade-or-keep"）或球队名形式出现，只靠联赛词拦不住。
GTRENDS_DENY = re.compile(
    r"\b(?:nfl|nba|mlb|nhl|ncaa|fifa|uefa|mls|pga|lpga|atp|wta|ufc|wwe|aew|espn"
    r"|football|basketball|baseball|hockey|soccer|tennis|golf|boxing|wrestling"
    r"|quarterback|qbs?|tds?|touchdown|mvp|playoffs?|super\s+bowl|world\s+cup|champions\s+league"
    r"|premier\s+league|la\s+liga|serie\s+a|europa\s+league|all-star|all\s+star"
    r"|draft|injury|trade|stadium|arena|troops|military"
    r"|nuggets|sixers?|lakers|celtics|yankees|dodgers|cowboys|patriots|chiefs|eagles"
    r"|warriors|knicks|bulls|heat|bucks|suns|mavericks|raiders|broncos|packers"
    r"|steelers|ravens|bengals|browns|texans|colts|jaguars|titans|vikings|lions"
    r"|bears|falcons|saints|buccaneers|panthers|cardinals|rams|seahawks|49ers"
    r"|chargers|jets|giants|dolphins|bills"
    r"|movie|film|tv\s+show|episode|album|concert|tour|grammy|oscar|emmy"
    r"|golden\s+globe|actor|actress|singer|rapper|celebrity|snl|saturday\s+night\s+live"
    r"|netflix|disney|marvel|trailer|president|white\s+house|senate|congress|election"
    r"|minister|prime\s+minister|lobbyist|summit|protest|war|sports?|athlete"
    r"|nfl\.com|nhl\.com|nbcsports|yahoo\s+sports|fox\s+sports|cbs\s+sports"
    r"|the\s+athletic|bleacher\s+report|sporting\s+news|sports\s+illustrated|sky\s+sports"
    r"|variety|deadline|hollywood\s+reporter|tmz|billboard|rolling\s+stone"
    r"|politico|the\s+hill"
    # --- 2026-11-15 补：体育/天气/事故/娱乐/政治类通用词（之前只列了
    # 联赛与球队名，拦不住 game/vs/风暴/枪击这类热搜）---
    r"|game|games|match|matches|score|scores|scoring|vs|versus|win|wins|won|winning|loss|losses|beat|beats|beaten|championship|champions|tournament|tournaments|league|leagues|semifinal|quarterfinal|fixture|fixtures|race|racing|fight|fights|bout|knockout|upset|shutout|touchdown|homer|home\s+run|penalty|penalties|referee"
    r"|storm|storms|hurricane|hurricanes|tornado|tornadoes|earthquake|earthquakes|flood|floods|flooding|waves|tsunami|eruption|eruptions|blizzard|wildfire|wildfires|rain|rains|snow|snowfall|heatwave|heat\s+wave|cold\s+snap|drought|tormenta|lluvia|terremoto|huracán|inundación|sequía|sismo|nevada|volcano|volcanic|avalanche|landslide|typhoon|cyclone|monsoon"
    r"|shooting|shootings|crash|crashes|collision|death|deaths|died|dies|killed|killing|murder|murders|arrested|arrest|arrests|police|explosive|explosives|lawsuit|lawsuits|sued|explosion|blast|attack|attacks|attacked|hostage|missing|funeral|obituary|passed\s+away|stabbing|robbery|burglary|hijack|kidnap"
    # --- 2026-11-15 补：西语事故/娱乐词（12:15 轮次两条漏网均为西语标题：
    #   "la mansion vip" 是西语真人秀，"aeropuerto internacional de miami"
    #   是西语空难新闻，事故/娱乐词只有英文版拦不住）---
    r"|aeropuerto|colisi[oó]n|choque|accidente|avi[oó]n|heridos?|muertos?|fallecid[oa]s?|tiroteo|incendio|explosi[oó]n|desaparecid[oa]s?|secuestro"
    r"|mansi[oó]n|espect[aá]culos|telenovela|famoso|famosa|cantante|actriz|pel[ií]cula|estreno|concurso|gran hermano"
    r"|premiere|premieres|finale|finales|cast|director|producers?|novel|memoir|documentary|podcast|podcasts|chart|charts|song|songs|lyrics|hollywood"
    r"|vote|votes|voter|voters|ballot|ballots|poll|polls|polling|vice\s+president|senator|senators|congressman|congresswoman|governor|governors|mayor|mayors|parliament|cabinet|democrat|democrats|republican|republicans|liberal|liberals|conservative|conservatives|campaign|campaigns|rally|rallies|debate|debates|impeachment|court|judge|judges|supreme\s+court|verdict|indictment|subpoena|sanction|sanctions)\b",
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
GTRENDS_COMMERCE_RE = re.compile(r"\b(?:price|prices|pricing|\$|sale|sales|deal|deals|discount|discounts|coupon|coupons|launch|launches|launched|release|releases|released|preorder|pre-order|buy|buys|buying|shop|shopping|store|stores|restock|restocked|sold\s+out|review|reviews|unboxing|viral|goes\s+viral|craze|frenzy|tiktok|instagram|influencer|influencers|amazon|walmart|target|costco|shein|temu|ebay|etsy|shopify|brand|brands|product|products|gadget|gadgets|toy|toys|fashion|beauty|skincare|makeup|sneaker|sneakers|shoes|electronics|gaming|console|gift|gifts|haul|christmas|holiday\s+shopping|black\s+friday|cyber\s+monday|prime\s+day|singles\s+day|small\s+business\s+saturday)\b", re.I)
GTRENDS_SHOPPING = {"black friday", "cyber monday", "prime day", "prime big deal days", "singles day", "small business saturday"}


def gtrends_verdict(title, news_title="", news_source=""):
    """一条 Trends 热搜的去留（供测试与 scrape_gtrends 共用）。
    返回 None 表示保留，否则返回命中的规则名。"""
    joined = " ".join([title, news_title, news_source])
    if GTRENDS_DENY.search(joined):
        return "deny-word"
    # 西语动词 sale（"sale de …" = 离开）会误触英文商业词 sale 而放行
    # 人名/片名（如 La Mansión VIP），救援判断前先去掉 "sale de"。
    joined_rescue = re.sub(r"\bsale\s+de\b", " ", joined, flags=re.I)
    if (title.lower() not in GTRENDS_SHOPPING
            and GTRENDS_NAME_RE.match(title)
            and not GTRENDS_COMMERCE_RE.search(joined_rescue)):
        return "deny-name"
    if GTRENDS_PLACE_RE.match(title):
        return "deny-place"
    if len(title.split()) == 1 and not GTRENDS_COMMERCE_RE.search(joined_rescue):
        return "deny-single"
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
