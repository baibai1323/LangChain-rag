# agents/

存放自定义子代理（subagent）的**定义文件**。

DSH 没有「agent 配置目录」这种机制：`~/.dsh` 下只有 `skills/`，没有 `agents/`；子代理只能在会话里由主 agent 运行时派发。所以这里的 `AGENT.md` 是**约定式说明书**：派活时让子代理先读它，它就知道自己是谁、能用什么、不许干什么。

## 现有代理

| 名字 | 目录 | 干什么 |
|---|---|---|
| tester | `agents/tester/AGENT.md` | 用 `unit-test-rag` 技能给 RAG 后端写/跑 pytest，产出覆盖率与 bug 清单 |
| quality-engineer | `agents/quality-engineer/AGENT.md` | 用 `security-audit` + `check-comments` 技能，从安全/注释/测试健康度/工程卫生四维审查，产出分级报告 |
| gitcommit-agent | `agents/gitcommit-agent/AGENT.md` | 提交前的编排者：并行派 tester 与 quality-engineer，核对两份凭证，通过后按 `git-save` 提交 |

## 一条完整链路

```
改完代码
  └─ gitcommit-agent
       ├─ 并行 → tester            写测试、跑全量、写 tester 凭证
       ├─ 并行 → quality-engineer  四维审查、写报告、写 QE 凭证
       ├─ 自己 verify 两份凭证     不信口头结论，读文件核对
       └─ git-save → git commit
                       └─ pre-commit 门禁（tools/quality-gate）
                            验凭证 → 自己再跑一遍 pytest → 验 P0/P1 → 放行
```

门禁拦住时**不要** `--no-verify`：按提示重跑对应的 agent 就行。

## 怎么用

在这个工作区开新会话时，直接说：

> 让 tester 测一轮这个 RAG 项目
> 让 quality-engineer 审一轮
> 提交这次改动（会自动走 gitcommit-agent 那条链路）

主 agent 会读对应的 `AGENT.md`，把里面的内容作为子代理的任务说明派下去。

两个检查代理的分工：**tester 动手写测试**（结果是有更多用例），**quality-engineer 只审不动手**（结果是分级报告）。所以「测试覆盖够不够、注释写没写对、有没有安全隐患」问 quality-engineer；「给我把这块的测试补上」问 tester。

## 写一个新代理的格式

```
agents/<名字>/AGENT.md
---
name: <名字>
description: <一句话，说清什么时候该用它>
---
# 角色
# 技能来源（要读的文件路径）
# 环境（解释器、目录、命令）
# 每轮流程
# 边界（不许做什么）
# 交付格式
```

要点：**把技能路径写死**。项目技能在 `.dsh/skills` 下，子代理有时候加载不到，写绝对/相对路径最稳。
