# 电商HOT

电商HOT：每天为电商从业者精选的行业热点（平台动态、运营增长、营销推广、行业数据、政策合规、工具技术），中文标题 + 一句话简介 + 每日日报。

本站由 HOT 流水线模板（Staroltest/hot-site-template）搭建：从公开 RSS 信源采集内容，规则打分精选，生成纯静态站，托管在 GitHub Pages，并附带一个 MCP 接入点。只展示原标题 + 一句自己写的一句话简介 + 原文链接，不转载正文与摘要。

## 一句话开新站

跟 agent 说一句话，例如：

> 用 hot-site-template 给我搭一个电商 HOT，面向电商从业者，信源你来找。

agent 按 [BOOTSTRAP.md](BOOTSTRAP.md) 里的 playbook 全套办完：
建仓库、填配置、找信源、首轮生成、双站部署、定时任务、验收。
你只需要确认站名、主题和受众；信源 agent 会逐个实测后定。

## 模板里有什么

| 文件 | 作用 |
| --- | --- |
| `tools/generate.py` | 生成器：拉 RSS → 去重 → 规则打分 → 生成全站。纯 Python 标准库，零依赖 |
| `config.json` | 全部可调项：站名、受众、分类与关键词、打分权重、关于页、页脚、赞赏码 |
| `sources.json` | 信源清单（示例 2 条，搭建时必换） |
| `_worker.js` | MCP 端点（Cloudflare Pages Advanced Mode，单文件无依赖） |
| `_routes.json` | 只把 `/mcp` 交给 worker，其余路径静态托管 |
| `favicon.svg` | 通用站标 |
| `data/changelog.json` | 更新日志种子（示例 1 条） |
| `docs/cron-half-hourly.md` | 每半小时更新任务的指令模板 |
| `docs/cron-daily-curation.md` | 每日精选把关任务的指令模板 |
| `docs/pipeline-notes.md` | 流水线踩过的坑与铁律 |
| `BOOTSTRAP.md` | **agent 开新站的完整 playbook** |

## 站点长什么样

首页（精选 10 条 + 热点框）、全部动态（30 天全量按天分组）、热点榜、
日报 / 周报 / 月报、主题页、收藏、RSS（`feed.xml`）、MCP（`/mcp`）。
只展示原标题 + 一句自己写的一句话简介 + 原文链接，不转载正文与摘要。

## 成本

免费额度内：GitHub Pages 免费；Cloudflare 直传不消耗每月 500 次构建额度，
静态访问不限量；MCP 调用每天 10 万次免费额度。详见 BOOTSTRAP.md。

## 许可与出处

MIT License，Copyright (c) 2026 Camille。

流水线源自 IndieHOT 的实践；IndieHOT 的信息架构与界面风格参考了卡兹克
（张仁杰）的开源项目 [AIHOT](https://github.com/KKKKhazix/AIHOT)（MIT 协议）。
本站模板按 MIT 协议开源，欢迎取用，署名链请保留。
