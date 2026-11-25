# SEO 改动记录

每周 SEO 托管任务每做一处改动，就在最上面加一条。改回去的也记一条。

格式：
## YYYY-MM-DD
- 页面：/path/
  - 改了什么：标题 / 描述 / 内链 / 新页面 / 技术修复（写清改前 → 改后）
  - 为什么：依据的数据（曝光、点击率、排名、索引状态，取自 data/seo/<date>.json）
  - 改前基线：28 天点击 X、曝光 Y、平均排名 Z

## 2026-11-25
- 页面：全站（sitemap 里 74 个网址）
  - 改了什么：技术修复。`site_src/generate.py` 的 `_content_hash` 不再把每页 `<head>` 里的 `window.FX` 当日汇率脚本算进正文哈希（改前：汇率一变，全站哈希都变 → 改后：只有正文文字变了才变）
  - 为什么：`data/lastmod.json` 里 78 条的哈希全部是 2026-11-25，sitemap 74 条里 70 条 lastmod 是当天。`real_lastmod` 本来是「正文真变才动 lastmod」，被每天浮动的汇率打穿了；lastmod 天天等于今天，Google 会直接不用它
  - 改前基线：/about/ 28 天点击 0、曝光 0、平均排名 —（该页无曝光，但 lastmod 每天在跳）
- 页面：/ai-pricing/chatgpt/、/ai-pricing/claude/、/ai-pricing/gemini/、/ai-pricing/grok/、/ai-pricing/perplexity/、/ai-pricing/cursor/
  - 改了什么：内链。价格表后新增「同一产品的 App Store 各地区价格」区块 → 链到 /{产品}/ 和该产品各档位页（共 6 个产品、22 个档位页；其余 15 个 pid 没有对应地区页，不生成空链接）
  - 为什么：/ai-pricing/claude/ 是「URL is unknown to Google」、入链只有 1 条；/ai-pricing/cursor/ 是「已抓取 - 尚未编入」、入链 1 条。这些页此前只有页脚一条入链，而对应的地区页（/claude/ 已编入 9 条入链、/claude/pro/ 16 条）根本不知道它们存在
  - 改前基线：/ai-pricing/claude/ 28 天点击 0、曝光 0、平均排名 —（未被 Google 发现）
- 页面：/chatgpt/{go,plus,pro-100,pro-200,pro-500}/、/claude/{pro,max,ultra}/、/google-ai/{pro,ultra}/、/grok/{supergrok,supergrok-lite,supergrok-plus,supergrok-heavy}/、/perplexity/{pro,max}/、/cursor/{pro,pro-plus,ultra}/
  - 改了什么：内链。在「官网和 App Store 哪个便宜」表后加一句，指向对应官网价格页 /ai-pricing/<pid>/（x 没有官网价格页，不加）
  - 为什么：两套页面回答同一条「X 会员多少钱」，原本只通过页脚互通；这些档位页已编入（16 条入链）且有曝光（/claude/pro/ 曝光 1、排名 9），可以把权重和抓取带过去
  - 改前基线：/claude/pro/ 28 天点击 0、曝光 1、平均排名 9
- 页面：/ai-pricing/
  - 改了什么：描述 23 字 → 88 字（改前「每天自动更新的 AI 会员官网价格和限时优惠。」→ 改后写明覆盖的产品、按年付折扣，以及和 App Store 地区价的关系）
  - 为什么：23 字的描述在结果里约等于没有；同族页面（/ai-pricing/chatgpt/ 等）都已编入，唯独总入口是「已发现 - 尚未编入」
  - 改前基线：/ai-pricing/ 28 天点击 0、曝光 0、平均排名 —

## 2026-11-23
- 起点：sitemap 75 个网址，Google 已编入 57 个；28 天曝光 32、点击 0、平均排名 7。（人工搭建托管，非自动改动）
