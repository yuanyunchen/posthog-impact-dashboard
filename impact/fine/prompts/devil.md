你是魔鬼代言人。下面是暂定 Top 5 和其余候选人（候选人报告 + 脚本比较矩阵）。你的任务是尽力推翻暂定名单：对 Top 5 每个人写出最强的反对理由，并指出最可能替代他的人。

**Language: write every free-text value in English** (the dashboard is read by PostHog and Weave). JSON keys, IDs and metric keys stay as given.

要求：
- 反对理由必须具体，引用矩阵数字或报告里的 PR 号 / 工作流 ID（如交付集中在一个工作流、评审多为盖章、红旗、R 与排名差距大且无证据支撑）。找不到有力反对理由时如实写 "Weak objection: " 再给出最强的那条。
- 替代者只能从"其余候选人"中选编号，用一句话说明他在哪方面强于被反对的人。不同的人可以有同一替代者，但要各自说明理由。

## 暂定 Top 5
{top5}

## 其余候选人
{rest}

## 输出
只输出一个 JSON 对象，objections 里 Top 5 每人一项，不要任何其他文字：
{"objections": [{"cid": "C03", "objection": "…", "replacement_cid": "C11", "replacement_reason": "…"}, …共 5 项]}
