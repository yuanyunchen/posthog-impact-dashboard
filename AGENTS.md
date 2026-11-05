# PostHog Dashboard：工程师影响力分析看板（Weave take-home）

## 定位
Weave 工程 take-home：用 PostHog/posthog 仓库最近 ≥90 天的 GitHub 数据，定义并量化"工程师影响力"，做一个单页交互看板展示 Top 5 及理由，公网托管后提交。时限 90 分钟（需自报计时）。作业全文：`.agents/task/01-impact-dashboard/input/assessment.md`。

## 用户偏好
- 回复按「进度 · 问题 · 决策」三段，简短，说效果不说机制（全局规则）。
- 与 Hex take-home 一致：不参考他人对本作业的解答（T01 初设，待用户确认）。

## 环境与命令
- gh 已登录（账号 yuanyunchen，scope repo/gist/read:org），GraphQL 限额 5000/h。
- `.agents/` 已写入 `.git/info/exclude`，不进公开仓库。

<!-- ws:begin -->
## Agent 工作区（v4）

> 本区块由 agent 维护（`ws init` 写入）；区块外的内容由人维护，agent 不改。harness=none

### 规则
<!-- 用户裁决（唯一位置）：必须 / 禁止 / 先问再做，一行一条并注明日期和出处 -->

### 任务树
<!-- ws:tree -->
- T01 PostHog 工程师影响力看板（Weave take-home 全流程） — active
  - T01.01 调研：贡献度/影响力评估的先例、方法与工具 — active，派发 3
  - T01.02 PostHog 仓库与贡献者 context — active，派发 3
  - T01.03 实施：三阶段漏斗并行开发与小规模测试 — active，派发 55
  - T01.04 Dashboard 内容设计与原型 — active，派发 3
  - T01.05 系统机制说明附录：内容稿 — active，派发 2
  - T01.06 提交整理：git 项目与提交物 — active，派发 5（1 未回）
<!-- /ws:tree -->

### 外部资源
<!-- 飞书文档或文件夹 token、外部代码路径、数据表：token/路径 + 一句话 -->
- 作业页：https://app.weaveos.com/assessment/asmt_eD1bGr5o2Ea75Z0p0gnhglFW（提交按钮在页底，未经用户同意不提交）
- 数据源：https://github.com/PostHog/posthog（GitHub API + 窗口内浅克隆）
- 前史：全局记忆卡 hex-ai-eng-takehome（同类招聘作业，含"不看他人解答"裁决先例）

### memory
<!-- ws:memory -->
索引和按类型视图：[.agents/memory/INDEX.md](.agents/memory/INDEX.md)；目录先读它的 README.md

（暂无）
<!-- /ws:memory -->

### 关键决策
<!-- 一行一条：YYYY-MM-DD 决策 — 理由（详情指针） -->
- 2026-11-03 项目建在 Play for Fun/posthog-dashboard，repo 型工作区 — 沿用 ai-eng-takehome-claude 先例；代码与工作区同处，便于直接推公开仓库托管
- 2026-11-03 允许 `git clone --shallow-since` 浅克隆 PostHog（只取窗口内提交）— 拿 diff、git 树谱系与 revert 不占 API 限额；仍不做全量 clone
- 2026-11-03 评估架构：底层数据+分角度打分只作参考，上层由多个评审 agent 综合判断定 Top 5（用户 T01 p422f9304）；类型标签只作解释不作配额
- 2026-11-03 `.agents/` 不提交 git — 仓库将公开用于托管，工作区记录不外露

### 工作协议
<!-- ws:protocol -->
本目录是 v4 工作区（标记文件 `.agents/ws.json`）。以下规则对主 agent 和子智能体都生效，hook 与 `ws check` 会检查。`ws` 不在 PATH 时用 `python3 /Users/yuanyunchen/.claude/skills/workspace-management/scripts/ws`。

1. 需求原文：用户每条消息和每轮的最终回答由 hook 自动记入 `.agents/conversation.md`（Q&A），用户消息另记一份 `.agents/inbox.md`。凡是需求或方向变化，当轮归档：`ws req <节点ID> --entry <id>`；开新任务用 `ws req --new <slug> --entry <id>`；不是需求的用 `ws req --not-req <id>`。没有 hook 的环境（Codex 等）把用户原话照录：`ws req <节点ID> --stdin`。
2. 任务节点：`.agents/task/NN-<名>/`，子任务在节点的 `task/` 下，结构相同。用 `ws task new <slug> [--parent ID]` 创建，不手建目录。task.md 由上层写，执行者不改：上半部「任务说明」（目标、背景、要求、约束、验收标准、输入、未定事项）是当前有效的完整任务，「要求」逐条 `- [ ]`，完成 `[x]`，取消 `[-]` 写理由并告知用户；每次归档新原文后当轮整段改写并用 `ws task spec <ID> --stdin` 写回；下半部「原文记录」只追加。任务说明写好、goal.md 和 plan.md 写好后执行 `ws task status <ID> active`；过程用 `ws log <ID> "…"` 追加进 progress.md；写完 result.md 后执行 `ws task status <ID> done`。
3. 拆分：一步能做完的直接做；需要独立验收或跨多步的建子任务；交给子智能体执行的走派发。输入给定、输出很小的单次判断（打分、两两比较）用脚本批量调模型，不逐条开子智能体。
4. 派发：先 `ws dispatch <ID> <slug> --stdin`（从 stdin 传入背景、成功标准、必读路径、可写范围），再原样使用它打印的那行 prompt。规范类内容写进 `.agents/memory/`，派发说明里只引用路径。未经 `ws dispatch` 的派发会被拦截；只读调研类子智能体（Explore、Plan 等）不受限。外部执行（codex exec、claude -p）用 `ws dispatch --external` 登记。给原执行者加新要求先 `ws followup <派发ID> --stdin` 再发续接消息；产物、可写范围或角色变了就新开派发。
5. 子智能体：只在自己的派发目录和 task.md 授权的路径内写；结果写入派发目录的 result.md（frontmatter `status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED`）：上层下一步要用的写进 result.md（6KB 内），只有复核才看的放附件并列进「附件」；聊天最后只回 `<STATUS> <result.md 路径>`；信息不足或受阻时返回 NEEDS_CONTEXT 或 BLOCKED，不猜。同一任务多次派发共用的说明写进节点的 `brief.md`，`ws dispatch` 会自动列进必读。
6. 主 agent 以 result.md 为准，不以聊天回复为准；没有 result.md 的派发按失败处理。「需要上层处理」逐条定修 / 豁免 / 报用户，各记一行 `ws log <ID> --tag decision "Snn …"`，推迟到汇总不算处理；同类派发先试跑一份，问题处理完再铺开。重要节点交给另一个子智能体独立验收。步骤与原因见派发协议第二节。
7. memory：只放跨任务有用的事实、做法、教训、资料摘要、长期决策，按主题分目录；文件头写 summary、type、tags、source、status、updated，代码或数据类再写 basis（依据的提交）和 covers（覆盖的目录）；开头写要点。单文件超过 8KB 改成同名目录：README.md（要点 + 下层文件表，读完就能干活）+ 下层文件。计划、建议、TODO 留在任务节点；用户裁决只写 AGENTS.md「规则」节。子智能体新写的标 `status: draft`，节点收尾时转正或合并。
8. AGENTS.md 由 agent 维护，100–200 行；`<!-- ws:… -->` 区块由 `ws index` 生成，不手改；「规则」节只记用户的裁决，自己想出的规则走 harness-management。
9. 收尾：`ws check` 无 error；改过代码或数据的，核对提示过期的 memory；冲突以 task.md 为准，其次是实际产物，最后才是自己写的记录。给人看的产物放节点的 `deliverables/`；密钥只放 `.agents/secrets.env`，不进 task.md 和 memory。一个节点派发超过 3 波（距本波第一次派发 10 分钟以上算新一波）就把后续波次建成子任务，`ws dispatch` 会拦下。可复用的事实、标准、方法、教训转进 memory，派发只引用路径：口径不必每次重讲、各子智能体一致、下个会话不用翻几十份结果。时机：试跑定下口径时、同一段说明要写第二遍时、节点收尾时。

常用：`ws status` 看现状 · `ws check` 查问题 · `ws index` 刷新索引。规范全文：/Users/yuanyunchen/.claude/skills/workspace-management/references/spec.md
<!-- /ws:protocol -->

### Skills
<!-- ws:skills -->
（暂无。工作区专属 skill 放 `.agents/skills/<名>/SKILL.md`，用时按本表路径读取）
<!-- /ws:skills -->
<!-- ws:end -->
