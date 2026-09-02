"""演示台样式：色板与布局对齐姊妹仓 enterprise-rag（售后知识治理 Copilot）。"""

BRAND_TOKENS = """
:root {
  --color-primary: #567357;
  --color-primary-hover: #4a634b;
  --color-bg: #F9F0ED;
  --color-accent: #E58889;
  --color-surface: #FFFFFF;
  --color-text: #2C332C;
  --color-muted: #8A8F8A;
  --color-line: #C5C0BD;
  --color-sidebar: #F6F2EF;
  --radius-card: 10px;
  --shadow-card: 0 8px 32px rgba(86, 115, 55, 0.08);
}
"""

PAGE_STYLE = f"""
<style>
{BRAND_TOKENS}
.stApp {{ background: var(--color-bg) !important; color: var(--color-text); }}
[data-testid="stHeader"] {{
  background: transparent !important;
  height: 2.5rem;
}}
[data-testid="stMainBlockContainer"],
section.main > div.block-container {{
  max-width: 1080px !important;
  padding-top: 1rem !important;
  padding-bottom: 2rem !important;
}}

.page-header {{
  max-width: 920px;
  margin: 0 auto 0.75rem auto;
}}
.page-title {{
  font-family: "Noto Serif SC", "Source Han Serif SC", Georgia, "Times New Roman", serif !important;
  font-size: 1.65rem !important;
  font-weight: 600 !important;
  color: var(--color-primary) !important;
  margin: 0 0 0.35rem 0 !important;
  letter-spacing: 0.02em;
  line-height: 1.3;
}}
.meta {{ color: var(--color-muted); font-size: 0.85rem; margin: 0 0 0.25rem 0; }}
.meta-subtle {{ color: var(--color-muted); font-size: 0.8rem; margin: 0 0 0.65rem 0; }}

[data-testid="stSidebar"] {{
  background: var(--color-sidebar) !important;
  border-right: 1px solid rgba(86, 115, 55, 0.1) !important;
}}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {{
  font-size: 0.8rem !important;
  font-weight: 600 !important;
  color: var(--color-primary) !important;
  letter-spacing: 0.04em;
  margin-bottom: 0.35rem !important;
}}
[data-testid="stSidebar"] .stButton > button {{
  background: var(--color-surface) !important;
  color: var(--color-text) !important;
  border: 1px solid rgba(86, 115, 55, 0.2) !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
  border-color: var(--color-primary) !important;
  color: var(--color-primary) !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-primary"] {{
  background: var(--color-primary) !important;
  color: #fff !important;
  border: none !important;
}}

.stButton > button,
.stDownloadButton > button {{
  border-radius: 6px !important;
}}
button[kind="primary"],
button[data-testid="baseButton-primary"] {{
  background-color: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
  color: #fff !important;
}}
button[kind="primary"]:hover,
button[data-testid="baseButton-primary"]:hover {{
  background-color: var(--color-primary-hover) !important;
  border-color: var(--color-primary-hover) !important;
}}

.portfolio-warn {{
  background: rgba(229, 136, 137, 0.12);
  border: 1px solid rgba(229, 136, 137, 0.45);
  border-left: 4px solid var(--color-accent);
  border-radius: var(--radius-card);
  padding: 0.65rem 0.9rem;
  margin: 0 0 0.85rem 0;
  font-size: 0.86rem;
  line-height: 1.45;
  color: var(--color-text);
}}
.portfolio-warn.standalone {{
  background: rgba(86, 115, 55, 0.08);
  border-color: rgba(86, 115, 55, 0.28);
  border-left-color: var(--color-primary);
}}
.portfolio-warn.joint {{
  background: rgba(229, 136, 137, 0.1);
}}
.portfolio-warn strong {{ color: var(--color-accent); }}
.portfolio-warn.standalone strong {{ color: var(--color-primary); }}
.portfolio-warn .tier {{
  display: block;
  margin-top: 0.25rem;
  color: var(--color-muted);
  font-size: 0.8rem;
}}
.intent-warn {{
  background: rgba(217, 119, 6, 0.1);
  border-left: 3px solid #D97706;
  border-radius: 6px;
  padding: 0.45rem 0.65rem;
  font-size: 0.86rem;
  color: var(--color-text);
  margin: 0 0 0.5rem 0;
}}
.linkage-line {{
  color: var(--color-muted);
  font-size: 0.84rem;
  margin: 0.15rem 0 0.65rem 0;
}}
.record-highlight {{
  color: var(--color-primary);
  font-size: 0.86rem;
  font-weight: 600;
  margin: 0 0 0.45rem 0;
}}
.mode-link {{
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}}
.mode-link:hover {{
  text-decoration: underline;
}}
.cert-summary {{
  background: var(--color-surface);
  border: 1px solid rgba(86, 115, 55, 0.14);
  border-radius: var(--radius-card);
  padding: 0.65rem 0.85rem;
  font-size: 0.86rem;
  line-height: 1.5;
  margin: 0.5rem 0 0.75rem 0;
}}

.status-banner {{
  background: var(--color-surface);
  border: 1px solid rgba(86, 115, 55, 0.14);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 1rem 1.15rem;
  margin: 0 0 1rem 0;
}}
.status-banner.warn {{ border-left-color: #D97706; }}
.status-banner.ok {{ border-left-color: var(--color-primary); }}
.status-banner.idle {{ border-left-color: var(--color-line); }}
.status-banner.err {{ border-left-color: var(--color-accent); }}
.status-banner .label {{
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin: 0 0 0.25rem 0;
}}
.status-banner .title {{
  font-family: "Noto Serif SC", "Source Han Serif SC", Georgia, serif;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--color-text);
  margin: 0 0 0.35rem 0;
}}
.status-banner .reason,
.status-banner .next {{
  font-size: 0.9rem;
  color: var(--color-muted);
  margin: 0.15rem 0;
}}
.status-banner .next strong {{ color: var(--color-primary); }}

.step-row {{
  display: flex;
  gap: 0.5rem;
  margin: 0 0 1rem 0;
  flex-wrap: wrap;
}}
.step-chip {{
  background: var(--color-surface);
  border: 1px solid rgba(86, 115, 55, 0.12);
  border-radius: 999px;
  padding: 0.35rem 0.85rem;
  font-size: 0.82rem;
  color: var(--color-muted);
}}
.step-chip.active {{
  background: rgba(86, 115, 55, 0.1);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}}
.step-chip.done {{
  color: var(--color-primary);
  border-color: rgba(86, 115, 55, 0.25);
}}

.result-card {{
  background: var(--color-surface);
  border: 1px solid rgba(86, 115, 55, 0.12);
  border-radius: var(--radius-card);
  box-shadow: 0 4px 16px rgba(86, 115, 55, 0.06);
  padding: 12px 14px;
  margin: 0 0 0.5rem 0;
}}
.result-card h4 {{
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--color-primary);
  margin: 0 0 0.4rem 0;
}}
.result-card .card-body {{
  font-size: 0.86rem;
  line-height: 1.45;
  color: var(--color-text);
}}
.result-card.accent {{ border-left: 3px solid var(--color-accent); }}
.result-card.primary {{ border-left: 3px solid var(--color-primary); }}

.hitl-panel {{
  background: var(--color-surface);
  border: 1px solid rgba(229, 136, 137, 0.35);
  border-left: 4px solid var(--color-accent);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: 1rem 1.15rem;
  margin: 0.75rem 0 1rem 0;
}}
.section-label {{
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-primary);
  margin: 0.55rem 0 0.35rem 0;
}}
.demo-path {{
  color: var(--color-muted);
  font-size: 0.88rem;
  margin: 0 0 0.75rem 0;
}}
.results-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.65rem;
  margin: 0.35rem 0 0.75rem 0;
}}
@media (min-width: 900px) {{
  .results-grid {{ grid-template-columns: 1fr 1fr 1fr 1fr; gap: 0.55rem; }}
}}
div[data-testid="stVerticalBlockBorderWrapper"] {{
  margin-top: 0 !important;
}}
div[data-testid="stTextArea"] {{
  margin-bottom: 0.35rem !important;
}}
div[data-testid="stTextArea"] textarea {{
  min-height: 5.5rem !important;
}}
div[data-testid="column"] > div {{
  gap: 0.35rem !important;
}}
</style>
"""
