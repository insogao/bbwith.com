"""Apps and plans tracked on bbwith.com.

Each plan maps to one or more (app key, regex on the English IAP name).
Only monthly prices are kept; see build_data.py for how annual prices are dropped.
"""

APPS = {
    "chatgpt": 6448311069,
    "claude": 6473753684,
    "gemini": 6477489729,
    "googleone": 1451784328,
    "grok": 6670324846,
    "x": 333903271,
    "perplexity": 1668000334,
    "cursor": 6767085653,
}

# product slug -> display info
PRODUCTS = {
    "chatgpt": {"name": "ChatGPT", "vendor": "OpenAI", "app": "ChatGPT", "note": "Codex 包含在 ChatGPT 套餐内，没有单独的 iOS App。"},
    "claude": {"name": "Claude", "vendor": "Anthropic", "app": "Claude by Anthropic", "note": ""},
    "google-ai": {"name": "Google AI（Gemini）", "vendor": "Google", "app": "Google Gemini / Google One", "note": "Google AI Pro / Ultra 可以在 Gemini 或 Google One App 内订阅，本站取两者中能抓到的标准档（Pro 5 TB、Ultra 30 TB）。"},
    "grok": {"name": "Grok", "vendor": "SpaceX AI（xAI）", "app": "Grok", "note": ""},
    "x": {"name": "X", "vendor": "X Corp.", "app": "X", "note": ""},
    "perplexity": {"name": "Perplexity", "vendor": "Perplexity AI", "app": "Perplexity", "note": ""},
    "cursor": {"name": "Cursor", "vendor": "SpaceX（Anysphere）", "app": "Cursor", "note": "Cursor 已被 SpaceX 收购，iOS App 的开发者显示为 X Corp.。"},
}

# (product slug, plan slug, plan label, rules)
PLANS = [
    ("chatgpt", "go", "Go", [("chatgpt", r"^ChatGPT Go$")]),
    ("chatgpt", "plus", "Plus", [("chatgpt", r"^ChatGPT Plus$")]),
    ("chatgpt", "pro-100", "Pro 100", [("chatgpt", r"^ChatGPT Pro 100$")]),
    ("chatgpt", "pro-200", "Pro 200", [("chatgpt", r"^ChatGPT Pro 200$")]),
    ("chatgpt", "pro-500", "Pro 500", [("chatgpt", r"^ChatGPT Pro 500$")]),
    ("claude", "pro", "Pro", [("claude", r"^Claude Pro - Monthly$")]),
    ("claude", "max", "Max", [("claude", r"^Claude Max - Monthly$")]),
    ("claude", "ultra", "Ultra", [("claude", r"^Claude Ultra - Monthly$")]),
    ("google-ai", "pro", "Pro（5 TB）", [("gemini", r"^Google AI Pro \(5 TB\)$"), ("googleone", r"^Google AI Pro \(5 TB\)$")]),
    ("google-ai", "ultra", "Ultra（30 TB）", [("gemini", r"^Google AI Ultra \(30 TB\)$"), ("googleone", r"^Google AI Ultra \(30 TB\)$")]),
    ("grok", "supergrok-lite", "SuperGrok Lite", [("grok", r"^SuperGrok Lite$")]),
    ("grok", "supergrok", "SuperGrok", [("grok", r"^SuperGrok$")]),
    ("grok", "supergrok-plus", "SuperGrok Plus", [("grok", r"^SuperGrok Plus$")]),
    ("grok", "supergrok-heavy", "SuperGrok Heavy", [("grok", r"^SuperGrok Heavy$")]),
    ("x", "premium-basic", "Premium Basic", [("x", r"^X Premium Basic \(Monthly\)$")]),
    ("x", "premium", "Premium", [("x", r"^X Premium \(Monthly\)$")]),
    ("x", "premium-plus", "Premium Plus", [("x", r"^X Premium Plus \(Monthly\)$")]),
    ("perplexity", "pro", "Pro", [("perplexity", r"^Perplexity Pro$")]),
    ("perplexity", "max", "Max", [("perplexity", r"^Perplexity Max$")]),
    ("cursor", "pro", "Pro", [("cursor", r"^Pro$")]),
    ("cursor", "pro-plus", "Pro+", [("cursor", r"^Pro\+$")]),
    ("cursor", "ultra", "Ultra", [("cursor", r"^Ultra$")]),
]
