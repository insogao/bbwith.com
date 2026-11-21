# bbwith.com · 比比价

每天对比 AI 会员（ChatGPT、Claude、Google AI、Grok、X、Perplexity、Cursor）在约 174 个 App Store 地区的月付标价，按当日汇率换算成人民币和美元，生成静态网站。

## 结构

```
scraper/
  plans.py         追踪的 App 和会员档位
  crawl.py         抓取各地区 App Store 的「App 内购买项目」→ data/raw/（不提交）
  parse_iap.py     从页面里解析内购名称和价格
  normalize.py     解析各地区的价格写法和币种
  build_data.py    只保留月付价，写入 data/daily/<日期>.json（紧凑格式，提交）
  storefronts.json 有效的 App Store 地区列表
site_src/
  generate.py      用 data/daily/*.json 生成 dist/（只用 Python 标准库）
  countries.json   地区中英文名
  static/          样式、脚本、favicon、_headers、404
.github/workflows/daily.yml  每天北京时间 07:37 抓取并提交数据
```

## 本地运行

```bash
python scraper/crawl.py          # 约 6 分钟
python scraper/build_data.py
python site_src/generate.py      # 输出到 dist/
cd dist && python -m http.server 8000
```

## Cloudflare Pages 设置

- 连接本仓库，生产分支 `main`
- 构建命令：`python3 site_src/generate.py`
- 构建输出目录：`dist`
- 自定义域名：`bbwith.com`（`www.bbwith.com` 在 Cloudflare 里用重定向规则跳转到 `bbwith.com`）

每天的数据提交会自动触发一次 Pages 部署（免费版每月 500 次）。

## 国内代充价（channels.yml）

每 4 小时从 16688 货源广场抓取代充报价，只把汇总结果写入 `data/channels/<日期>.json`。需要在仓库 Settings → Secrets and variables → Actions 里添加：

| Secret | 取值（登录 16688 后在浏览器开发者工具 → Application → Local Storage 里找） |
|---|---|
| `S16688_TOKEN` | `merchant-token` 里 JSON 的 `value` 字段 |
| `S16688_DEVICE_KEY` | `merchant-device-key` |
| `S16688_VISITOR_KEY` | `visitor-id` |

没有设置 `S16688_TOKEN` 时工作流会直接跳过。

## 优惠快讯（data/deals/）

每条优惠一个 JSON 文件（格式见 `data/deals/google-ai-black-friday-2026.json`），**先在官方页面核实再添加**；到 `end` 日期后自动移到「已结束」。
`news.yml` 每天两次扫描 AI/科技资讯 RSS，把疑似优惠/价格新闻开成带 `deal-candidate` 标签的 Issue，核实后再写成快讯文件。

## 数据口径

见网站的 /about/ 页面：只统计月付；大多数地区的标价含税，美国、加拿大等不含税；App Store 每个 App 只展示约 10 个内购项目，部分档位在部分地区抓不到。
