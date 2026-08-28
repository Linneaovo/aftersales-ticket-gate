# 演示词（约 6～8 分钟）— 固定顺序，勿临场乱点

> **定位**：开单协同 / 门禁编排 — **不替代 ERP 派工调度**；mock 提交仅入 RAG 收件箱。

## 答辩前 checklist（5 分钟）

```bash
copy .env.demo .env
python scripts\reset_demo_state.py
python scripts\demo_preflight.py --require-rag
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/persistence/audit
```

确认 `/health`：`rag_mode=live` · `demo_mode_warning=false` · `persistence_ok=true`。

### 反证彩排（P0-7，约 2 分钟）

```bash
python scripts\rehearse_rag_failure.py
# 现场：停 RAG → health degraded → POST /runs 503 → 启 RAG → 同剧本成功 + rag_linkage
```

---

## Step 0 · 开场 + health（40s）

1. `start_all.cmd` 或分别启动 RAG :8001 / Copilot :8002 / UI :8502
2. **终端先跑**：`curl http://127.0.0.1:8002/health` — 向评委展示 `rag_mode=live`
3. 口述：RAG=知识层；Copilot=Policy-as-Code 门禁 + 站长人确

## Step 1 · P1 主路径（2min）

- 剧本 **p1_xingsha_h103**（星沙 H103 液压无力）
- Trace 顺序：`supervisor → rag → quality → work_order → parts → hitl`
- 强调：**技师不能自批**（POL-ROLE-01）

### P1 业务背景（30s，减 AI 味）

> 3 月 12 日 14:20，星沙站客户来电：SY215C 动臂抬升缓慢，屏显 H103。技师张伟现场拍照后提单，需走检索→质检→配件预核→站长刘波确认。

## Step 2 · 站长人确 + inbox（1.5min）

- 切换 **站长（刘波）** → 批准
- `GET /inbox` 或 UI「刷新收件箱」— 证明双项目联动（非假联调）
- 可选展示 feedback 回写

## Step 3 · 对照 P2 / P3（1min）

- **P2** 冲突并列不作裁决 → waiting_hitl
- **P3** 越权薪酬 → rejected（POL-ACL-01）

## Step 4 · P5 缺料 + **P8 配件员（必演示，30s）**

- **P5** 缺料 → 展示 `suggested_action: 建议：经开调拨 · 预计 4h`
- **P8 必做**：切换人设 **配件员（陈雨）** → 跑 `p8_parts_clerk_conflict` → conflict_bundle **redacted**
- 口述：同题不同岗可见性 — 配件岗只见摘要，站长/技师看明细

## Step 5 · P7 + A-07（45s）

- **P7** 二次进站 + 缺料
- UI「跑 A-07 对比」或贴 `compare_report.json` **B01** diff

## Step 6 · 收尾（30s）

1+1>2；局限：演示 Key、mock 收件箱、非 ERP 调度。  
Plan B 见 [PLAN_B.md](PLAN_B.md)。

---

## 非 playbook 口语报修（答辩备用，先 smoke 验证）

```
SY215C 大臂抬不起来，师傅来看看
客户说动臂没劲，H103 亮了，星沙站
长沙星沙 SY215 液压异响挺大，安排上门
泵车大臂发软，码是 H103 那个
大臂没劲也没码，先安排上门排查
```

```bash
python scripts\smoke_with_rag.py --compare-live
pytest tests/test_intent_oral.py -q
```
