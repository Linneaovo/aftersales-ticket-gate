"""Product naming SSOT — UI、OpenAPI 与文档口径统一。

本地/历史目录名 ``aftersales-dispatch-copilot`` 含 ``dispatch`` 字样，仅为路径标识。
GitHub：https://github.com/Linneaovo/aftersales-ticket-gate

对外产品名是「报修开单门禁」，不是 ERP 派工系统。
意图枚举 ``fault_dispatch`` 同为内部历史名，UI/文档一律写「报修开单」。
"""

# —— 本仓（行动层 / 开单门禁）——
APP_TITLE = "报修开单门禁 Copilot"
APP_TITLE_FULL = "工程机械售后 · 报修开单门禁 Copilot"
APP_TITLE_EN = "After-Sales Ticket Gate Copilot"
SUBTITLE = "可插拔知识源 · POL 门禁 · 站长确认 · 决策快照"
PRODUCT_ONE_LINER = (
    "售后报修开单前的门禁编排：意图路由、POL-* 策略、配件预核、站长确认与决策快照；"
    "默认 Fixture 知识源即可闭环，Live 时可接姊妹仓知识层。"
)
# 本地路径标识（勿轻易改，联调脚本依赖）
REPO_SLUG = "aftersales-dispatch-copilot"
# 对外 GitHub
GITHUB_OWNER = "Linneaovo"
GITHUB_REPO = "aftersales-ticket-gate"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"

# —— 姊妹仓（知识层）——
SIBLING_REPO_SLUG = "enterprise-rag"  # 本地目录名 / API service
SIBLING_GITHUB_REPO = "aftersales-knowledge-copilot"
SIBLING_APP_TITLE = "售后知识治理 Copilot"
SIBLING_APP_TITLE_FULL = "工程机械售后知识治理 Copilot"
SIBLING_APP_TITLE_EN = "After-Sales Knowledge Copilot"
