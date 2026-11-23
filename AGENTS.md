# AGENTS.md

本文件是 `D:\lanchain rag项目` 工作区的默认约定，对本目录及其子目录下的所有会话生效。

## 进度可见

- 任何需要 3 步以上、或预计耗时较长的任务，开始前必须用 `todo_write` 建立任务清单；一步就能完成的小任务可以省略。
- 清单项用动词开头，粒度到“可验收”，例如“重写检索重排并补去重”，不要写“处理检索”这种笼统项。
- 同一时间只保留一个 `in_progress`；完成一项就立刻标记 `completed`，不要攒到最后一次性更新。
- 阶段切换时，用 1–3 行中文说明：已完成什么、正在做什么、下一步是什么；发现风险或改变方案时也要说明原因。
- 最终答复前检查任务清单：未完成项必须说明原因，不能把未验证的事情说成已完成。

## 项目速查

| 项 | 值 |
|---|---|
| 后端 | FastAPI + SQLAlchemy 2 async + LangChain，入口 `backend/app/main.py` |
| 前端 | Vue 3 + TS + Vite + Element Plus，源码 `frontend/src`，构建产物 `frontend/dist` |
| 解释器 | `.venv\Scripts\python.exe`（Python 3.14.5） |
| 启动 | `start.bat`（需要 `.env` 里有 `DASHSCOPE_API_KEY`） |
| 测试 | `.\.venv\Scripts\python.exe -m pytest backend\tests -q` |
| 提交 | 走 `agents/gitcommit-agent/AGENT.md` 的链路：tester + quality-engineer 凭证 → pre-commit 门禁 |

## 硬约束

- **不提交** `.env`、`data/`、`frontend/dist/`、`.venv/`、`node_modules/`、`.tmp/`。
- **不执行** `pip install`（本机直连 PyPI 会卡死）；依赖已装齐，需要新包先问用户。
- **不绕过** 提交门禁：被拦下就按提示重跑 tester / quality-engineer，不要 `--no-verify`。
- 密钥只从环境变量或 `.env` 读取；任何情况下不把完整 key 写进代码、日志、报告。
- 修改后端接口时同步更新 `backend/tests`，否则门禁会拦。

## 技能与代理

- 项目技能在 `.dsh/skills/`：`unit-test-rag`、`security-audit`、`check_comments`、`git-save`。
- 子代理说明书在 `agents/`：`tester`、`quality-engineer`、`gitcommit-agent`。
- 两者都不是自动执行的，需要在会话里显式加载/派发。
