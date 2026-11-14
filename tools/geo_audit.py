#!/usr/bin/env python3
"""SEO / GEO 自检：输出 geo-audit.html（人看）+ data/geo-audit.json（机器读）。

用法：
    python3 tools/geo_audit.py [--root <仓库根目录>] [--site-url <规范域名>]

每轮生成后由 tools/generate.py 调用（失败不中断主流程），也可以单独跑。
只读检查现有文件 + 写两个输出文件，不改其他文件；所有网络检查都有超时，
失败时记为 unknown/fail，不抛异常。

检查项（9 项）：
    1 robots.txt 是否点名放行 AI 爬虫、是否屏蔽 Bytespider、是否声明 Sitemap
    2 sitemap.xml 的 URL 数、lastmod 是否可信（多于 1 个不同日期）、有无漏页
    3 llms.txt 是否存在且提到 MCP 接入点
    4 抽查页面的 canonical / hreflang / robots meta / RSS 发现链接
    5 抽查页面的 JSON-LD 是否存在且可解析
    6 详情页 Article 是否含 dateModified / inLanguage / isBasedOn，作者是否为本站
    7 MCP 端点是否可达
    8 Cloudflare Pages 镜像是否已部署新版 robots.txt
    9 feed.xml 是否可解析、条目数
"""

import argparse
import glob
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

AI_BOTS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-Web",
           "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended",
           "Applebot-Extended", "Meta-ExternalAgent", "Meta-ExternalFetcher",
           "DuckAssistBot", "YouBot", "CCBot"]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _fetch_text(url, timeout=10):
    """返回 (status, text)；网络异常返回 (None, str(exc))。"""
    req = urllib.request.Request(url, headers={"User-Agent": "HOTBot-geo-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 - 网络失败记 unknown，不中断自检
        return None, str(e)


def _ld_blocks(page_html):
    blocks = []
    for m in re.finditer(
            r'<script type="application/ld\+json">(.*?)</script>',
            page_html, re.S):
        try:
            blocks.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            blocks.append(None)
    return blocks


def _disk_html(root):
    """仓库里全部 HTML（相对路径），排除 404/index。"""
    out = set()
    for p in glob.glob(os.path.join(root, "**", "*.html"), recursive=True):
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        if rel not in ("404.html", "index.html"):
            out.add(rel)
    return out


def run(root, site_url=None):
    """执行全部检查，写 geo-audit.html 与 data/geo-audit.json，返回检查结果 dict。"""
    root = os.path.abspath(root)
    cfg = {}
    cfg_path = os.path.join(root, "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    site = cfg.get("site", {})
    site_url = (site_url or site.get("url") or "").rstrip("/")
    site_name = site.get("name", "")
    mcp_url = site.get("mcp_url", "")
    mirror = mcp_url[:-len("/mcp")] if mcp_url.endswith("/mcp") else ""
    now = datetime.now(timezone.utc)
    checks = []

    def add(cid, name, status, detail):
        checks.append({"id": cid, "name": name, "status": status, "detail": detail})

    # 1. robots.txt
    robots_path = os.path.join(root, "robots.txt")
    if os.path.exists(robots_path):
        robots = _read(robots_path)
        found = [b for b in AI_BOTS if f"User-agent: {b}" in robots]
        blocked = "Bytespider" in robots and "Disallow: /" in robots
        has_sitemap = "Sitemap:" in robots
        missing = [b for b in AI_BOTS if b not in found]
        if len(found) == len(AI_BOTS) and blocked and has_sitemap:
            add("robots", "robots.txt 点名放行 AI 爬虫", "pass",
                f"已点名 {len(found)}/{len(AI_BOTS)} 个 AI 爬虫；Bytespider 已屏蔽；已声明 Sitemap。")
        else:
            parts = []
            if missing:
                parts.append(f"未点名 {','.join(missing)}")
            if not blocked:
                parts.append("Bytespider 未屏蔽")
            if not has_sitemap:
                parts.append("未声明 Sitemap")
            add("robots", "robots.txt 点名放行 AI 爬虫", "fail",
                "缺失：" + "、".join(parts))
    else:
        add("robots", "robots.txt 点名放行 AI 爬虫", "fail", "robots.txt 不存在。")

    # 2. sitemap.xml
    sm_path = os.path.join(root, "sitemap.xml")
    if os.path.exists(sm_path):
        try:
            tree = ET.parse(sm_path)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls, lastmods = [], set()
            for u in tree.getroot().findall("sm:url", ns):
                loc = u.findtext("sm:loc", "", ns)
                urls.append(loc)
                lm = u.findtext("sm:lastmod", "", ns)
                if lm:
                    lastmods.add(lm)
            sm_paths = {u[len(site_url) + 1:] if u.startswith(site_url + "/") else u
                        for u in urls}
            disk = _disk_html(root)
            missing = sorted(disk - sm_paths)
            detail = (f"{len(urls)} 条 URL；lastmod 共 {len(lastmods)} 个不同日期；"
                      f"磁盘 HTML {len(disk)} 页，漏 {len(missing)} 页。")
            if missing:
                detail += "漏页：" + "、".join(missing[:8]) + (" 等" if len(missing) > 8 else "")
            if not missing and len(lastmods) >= 2:
                add("sitemap", "sitemap.xml 完整且 lastmod 可信", "pass", detail)
            else:
                add("sitemap", "sitemap.xml 完整且 lastmod 可信", "fail", detail)
        except ET.ParseError as e:
            add("sitemap", "sitemap.xml 完整且 lastmod 可信", "fail", f"sitemap.xml 解析失败：{e}")
    else:
        add("sitemap", "sitemap.xml 完整且 lastmod 可信", "fail", "sitemap.xml 不存在。")

    # 3. llms.txt
    llms_path = os.path.join(root, "llms.txt")
    if os.path.exists(llms_path):
        llms = _read(llms_path)
        if len(llms) > 200 and ("mcp" in llms.lower()):
            add("llms", "llms.txt 存在", "pass",
                f"llms.txt 存在（{len(llms)} 字符），含 MCP 接入点说明。")
        else:
            add("llms", "llms.txt 存在", "fail", "llms.txt 存在但内容过短或未提 MCP 接入点。")
    else:
        add("llms", "llms.txt 存在", "fail", "llms.txt 不存在。")

    # 抽查页面：首页 + 聚合页 + 日报页 + 最多 3 篇详情页
    samples = ["index.html", "all.html", "daily.html"]
    items = sorted(glob.glob(os.path.join(root, "items", "*.html")))[:3]
    samples += [os.path.relpath(p, root).replace(os.sep, "/") for p in items]
    sample_html = {}
    for rel in samples:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            sample_html[rel] = _read(p)

    # 4. canonical / hreflang / robots meta / RSS
    bad = []
    for rel, h in sample_html.items():
        lacks = []
        if 'rel="canonical"' not in h:
            lacks.append("canonical")
        if 'hreflang="zh-CN"' not in h:
            lacks.append("hreflang zh-CN")
        if 'hreflang="x-default"' not in h:
            lacks.append("hreflang x-default")
        if 'name="robots"' not in h:
            lacks.append("robots meta")
        if "application/rss+xml" not in h:
            lacks.append("RSS 发现链接")
        if lacks:
            bad.append(f"{rel} 缺 {','.join(lacks)}")
    if sample_html and not bad:
        add("head", "抽查页面 canonical / hreflang 齐全", "pass",
            f"抽查 {len(sample_html)} 页（首页/聚合/日报/详情）全部含 canonical、"
            f"hreflang zh-CN + x-default、robots meta、RSS 发现链接。")
    else:
        add("head", "抽查页面 canonical / hreflang 齐全", "fail",
            ("未抽到页面。" if not sample_html else "；".join(bad)))

    # 5. JSON-LD
    bad_ld, types_seen = [], set()
    for rel, h in sample_html.items():
        blocks = _ld_blocks(h)
        if not blocks or any(b is None for b in blocks):
            bad_ld.append(f"{rel} 无有效 JSON-LD")
            continue
        for b in blocks:
            if isinstance(b, dict) and b.get("@type"):
                types_seen.add(b["@type"])
    if sample_html and not bad_ld:
        add("jsonld", "抽查页面结构化数据有效", "pass",
            f"抽查 {len(sample_html)} 页 JSON-LD 均可解析；出现过的类型："
            f"{'、'.join(sorted(types_seen))}。")
    else:
        add("jsonld", "抽查页面结构化数据有效", "fail",
            ("未抽到页面。" if not sample_html else "；".join(bad_ld)))

    # 6. 详情页 Article
    item_rels = [r for r in sample_html if r.startswith("items/")]
    bad_art = []
    for rel in item_rels:
        h = sample_html[rel]
        blocks = [b for b in _ld_blocks(h) if isinstance(b, dict)]
        art = next((b for b in blocks if b.get("@type") == "Article"), None)
        if art is None:
            bad_art.append(f"{rel} 无 Article")
            continue
        lacks = [k for k in ("datePublished", "dateModified", "inLanguage", "isBasedOn")
                 if not art.get(k)]
        author = art.get("author") or {}
        if isinstance(author, dict) and author.get("name") != site_name:
            lacks.append(f"author 不是本站（{author.get('name')}）")
        if 'og:type" content="article"' not in h:
            lacks.append("og:type 不是 article")
        if lacks:
            bad_art.append(f"{rel} 缺 {','.join(lacks)}")
    if item_rels and not bad_art:
        add("article", "详情页 Article 结构化数据完整", "pass",
            f"抽查 {len(item_rels)} 篇详情页，Article 均含 datePublished / dateModified / "
            f"inLanguage / isBasedOn，author 为本站，og:type 为 article。")
    else:
        add("article", "详情页 Article 结构化数据完整", "fail",
            ("未抽到详情页。" if not item_rels else "；".join(bad_art)))

    # 7. MCP 端点可达性
    if mcp_url:
        status, _body = _fetch_text(mcp_url, timeout=10)
        if status is not None and status < 500:
            add("mcp", "MCP 端点可达", "pass", f"GET {mcp_url} 返回 HTTP {status}，端点可达。")
        elif status is not None:
            add("mcp", "MCP 端点可达", "fail", f"GET {mcp_url} 返回 HTTP {status}。")
        else:
            add("mcp", "MCP 端点可达", "unknown", f"无法访问 {mcp_url}（网络异常）。")
    else:
        add("mcp", "MCP 端点可达", "unknown", "config.json 未配 mcp_url。")

    # 8. Cloudflare Pages 镜像是否已部署新版 robots.txt
    if mirror:
        status, body = _fetch_text(mirror + "/robots.txt", timeout=10)
        if status == 200 and "GPTBot" in body:
            add("pages", "Cloudflare Pages 镜像已部署新版", "pass",
                f"{mirror}/robots.txt 已含 AI 爬虫名单，镜像与 GitHub 同步。")
        elif status == 200:
            add("pages", "Cloudflare Pages 镜像已部署新版", "fail",
                f"{mirror}/robots.txt 仍是旧版（无 AI 爬虫名单），镜像需重新部署。")
        elif status is not None:
            add("pages", "Cloudflare Pages 镜像已部署新版", "fail",
                f"{mirror}/robots.txt 返回 HTTP {status}。")
        else:
            add("pages", "Cloudflare Pages 镜像已部署新版", "unknown",
                f"无法访问 {mirror}（网络异常）。")
    else:
        add("pages", "Cloudflare Pages 镜像已部署新版", "unknown", "config.json 未配 mcp_url，无法推导镜像域名。")

    # 9. feed.xml
    feed_path = os.path.join(root, "feed.xml")
    if os.path.exists(feed_path):
        try:
            ftree = ET.parse(feed_path)
            channel = ftree.getroot().find("channel")
            items_n = len(channel.findall("item")) if channel is not None else 0
            lang = channel.findtext("language") if channel is not None else ""
            empty_desc = 0
            if channel is not None:
                for it in channel.findall("item"):
                    d = it.findtext("description")
                    if not (d or "").strip():
                        empty_desc += 1
            detail = f"feed.xml 可解析，{items_n} 条，language={lang or '未标'}。"
            if empty_desc:
                detail += f"其中 {empty_desc} 条 description 为空（建议后续补简介）。"
            add("feed", "feed.xml 可解析", "pass" if items_n > 0 else "fail", detail)
        except ET.ParseError as e:
            add("feed", "feed.xml 可解析", "fail", f"feed.xml 解析失败：{e}")
    else:
        add("feed", "feed.xml 可解析", "fail", "feed.xml 不存在。")

    summary = {"pass": sum(1 for c in checks if c["status"] == "pass"),
               "fail": sum(1 for c in checks if c["status"] == "fail"),
               "unknown": sum(1 for c in checks if c["status"] == "unknown")}
    result = {"generated_at": now.isoformat(),
              "generated_at_cst": now.astimezone().isoformat(),
              "site": site_url, "site_name": site_name,
              "summary": summary, "checks": checks}

    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "geo-audit.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    icon = {"pass": "✅", "fail": "❌", "unknown": "❓"}
    rows = "".join(
        f'<tr><td>{icon[c["status"]]} {html.escape(c["name"])}</td>'
        f'<td>{html.escape(c["detail"])}</td></tr>\n' for c in checks)
    audit_url = site_url + "/geo-audit.html" if site_url else "geo-audit.html"
    page = (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>GEO 自检 · {html.escape(site_name)}</title>\n"
        f"<meta name=\"description\" content=\"{html.escape(site_name)}的 SEO / GEO 自检结果："
        "robots、sitemap、llms.txt、canonical、hreflang、结构化数据、MCP 与镜像部署状态。\">\n"
        f"<link rel=\"canonical\" href=\"{html.escape(audit_url)}\">\n"
        "<meta name=\"robots\" content=\"index, follow\">\n"
        f"<link rel=\"alternate\" hreflang=\"zh-CN\" href=\"{html.escape(audit_url)}\">\n"
        f"<link rel=\"alternate\" hreflang=\"x-default\" href=\"{html.escape(audit_url)}\">\n"
        "<style>body{font-family:system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
        "max-width:860px;margin:40px auto;padding:0 20px;color:#222;line-height:1.7}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px 10px;"
        "text-align:left;vertical-align:top}th{background:#f6f6f6}</style></head>\n<body>\n"
        f"<h1>GEO 自检 · {html.escape(site_name)}</h1>\n"
        f"<p>生成时间：{now.astimezone().strftime('%Y-%m-%d %H:%M %Z')} · "
        f"通过 {summary['pass']} / 失败 {summary['fail']} / 未知 {summary['unknown']} "
        f"（共 {len(checks)} 项）</p>\n"
        "<table><tr><th>检查项</th><th>结果</th></tr>\n" + rows + "</table>\n"
        "<p>机器可读结果：<a href=\"data/geo-audit.json\">data/geo-audit.json</a> · "
        f"<a href=\"{html.escape(site_url)}/robots.txt\">robots.txt</a> · "
        f"<a href=\"{html.escape(site_url)}/sitemap.xml\">sitemap.xml</a> · "
        f"<a href=\"{html.escape(site_url)}/llms.txt\">llms.txt</a> · "
        f"<a href=\"{html.escape(site_url)}/\">返回首页</a></p>\n"
        "<p>本页由 tools/geo_audit.py 在每轮生成时自动更新。</p>\n"
        "</body></html>\n")
    with open(os.path.join(root, "geo-audit.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"geo-audit: pass {summary['pass']}, fail {summary['fail']}, "
          f"unknown {summary['unknown']}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--site-url", default="")
    args = ap.parse_args()
    run(args.root, args.site_url or None)
