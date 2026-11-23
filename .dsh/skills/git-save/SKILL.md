---
name: git-save
description: 把工作区的改动安全地提交（必要时推送）——先看 diff、排除敏感与无关文件、按规范写中文提交信息、处理 hook 拒绝与凭据问题。不 force push、不绕过门禁。
---

# git-save · 安全提交

**目标**：把「改完了」变成「干净地进了版本库」，并且出问题时能说清楚卡在哪。

一句话原则：**先看清楚要提交什么，再动手；被门禁拦下就修，不改门禁。**

## 本项目速查

| 项 | 值 |
|---|---|
| 仓库根 | `D:\lanchain rag项目`（下文 `<repo>` 都指它） |
| 当前分支 | `master`（单人项目，直接在主分支提交） |
| 门禁 | `.git/hooks/pre-commit` → `tools/quality-gate/gate.py`，校验 tester / quality-engineer 两份凭证 |
| 允许提交 | `backend/`、`frontend/src` 与配置、`scripts/`、`tools/`、`docs/`、`README.md`、`start.bat`、`.gitignore`、`.dsh/`、`agents/` |
| 禁止提交 | `.env`（含 key）、`data/`（数据库/上传/Chroma）、`frontend/dist/`、`.venv/`、`node_modules/`、`.tmp/`、`.tools/`、`backend/.pytest-work/` |

这些路径都已在 `.gitignore` 里；如果 `git status` 里出现它们，说明忽略规则漏了，先补规则再提交。

---

## 0. 前置检查（30 秒，不许跳）

```powershell
git -C <repo> status --short
git -C <repo> diff --stat
```

判断四件事：

1. **有没有不该进库的东西**：`.env`、`*.key`、`*.pem`、数据库文件、`node_modules/`、`dist/`、日志、`__pycache__`、临时脚本。
2. **有没有你自己都不认识的改动**：别的 agent 或别的会话改的，先问清楚，不要顺手带上。
3. **改动是否属于同一个主题**：混了三件事就拆成三次提交。
4. **当前分支对不对**：`git -C <repo> branch --show-current`，别在 main 上提交实验代码。

发现敏感文件：从暂存区移出（`git restore --staged <file>`）并加进 `.gitignore`，**不要提交后再删**（历史里还在）。

---

## 1. 暂存

优先按路径明确暂存，少用 `git add -A`：

```powershell
git -C <repo> add <具体文件1> <具体文件2>
# 全部相关时才用：
git -C <repo> add -A
git -C <repo> status --short   # 复查一遍暂存了什么
```

---

## 2. 写提交信息

格式：`<类型>: <一句话>`，空一行，再写为什么。

| 类型 | 用在 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修 bug |
| `test` | 只加/改测试 |
| `docs` | 文档 |
| `ci` | 工作流、构建脚本 |
| `chore` | 依赖、配置、杂务 |
| `refactor` | 不改行为的重构 |

要求：

- 标题 ≤ 50 字，说**做了什么**，不写「update」「修改」这种空话。
- 正文说**为什么**：修的是哪个现象、为什么这么改。别人半年后靠它判断能不能回滚。
- 有对应问题/报告就引用，例如「见 reports/quality-tiantian-2026-11-20.md P1-1」。

```powershell
git -C <repo> commit -m "fix: 导出 CSV 时给公式前缀加引号" -m "备注以 = 开头会被 Excel 当公式执行，导入第三方 CSV 即可构造；现在导出时加前导单引号，并在导入时还原。"
```

---

## 3. 被 hook 拦下怎么办

门禁（`tools/quality-gate`）失败时**不要**用 `--no-verify` 绕过，按提示处理：

| 提示 | 含义 | 动作 |
|---|---|---|
| 没有找到 tester 的检查凭证 | 没跑测试 | 读 `agents\tester\AGENT.md` 派一轮，它会写凭证 |
| 测试没通过 —— N failed | 代码或测试真的红了 | 修到绿，再重跑 tester |
| 代码在 tester 检查之后又被改过 | 凭证指纹过期 | 重跑 tester（不要手改 JSON） |
| 质量问题未清零：P0=x P1=y | 质量审查不通过 | 读 `agents\quality-engineer\AGENT.md` 复审，先修掉 P0/P1 |
| 凭证已超过 12 小时 | 太久没复查 | 重跑对应的 agent |

门禁自己也会跑一遍 `pytest backend/tests`，所以「凭证是绿的但代码已经红了」同样会被拦下。

`--no-verify` 只允许一种情况：用户明确说「这次先跳过」，且要在提交信息正文里写清原因与补做计划。

---

## 4. 推送（用户要求时才推）

本项目当前没有配置远端；用户明确要求推送时，先 `git -C <repo> remote -v` 确认。没有远端就不要自作主张 `git remote add`。

```powershell
$env:GIT_TERMINAL_PROMPT = "0"
git -C <repo> push origin <branch>
```

**这台机器的特有坑**（都踩过）：

- GCM（Git 凭据管理器）在需要写权限时会弹 GUI 登录框；没人点就无限挂起。看到 push 卡住超过 60 秒，别等，直接 `job_kill`（如果是后台任务）。
- 卡住的解法：用 `git credential fill` 取出已存凭据，写一个临时 `.cmd` 当 `GIT_ASKPASS`，配合 `-c credential.helper=` 做非交互推送；用完立刻删掉这个脚本（里面有明文 token）。
- PowerShell 会把 git 的 stderr 进度输出当成 `NativeCommandError`，**退出码 1 不代表失败**。核对真实结果要看：
  ```powershell
  git -C <repo> ls-remote origin refs/heads/<branch>
  git -C <repo> log --oneline -1
  ```
- 推送后把本地 HEAD 和远端 sha 对一遍，一致才算成功。

---

## 5. 收尾

```powershell
git -C <repo> status --short   # 应该是干净的（或只剩确实不提交的东西）
git -C <repo> log --oneline -1
```

在最终答复里写：提交哈希、改了哪些文件、是否推送、推送后的远端 sha。

---

## 6. 禁止

- ❌ `git push --force` / `--force-with-lease`（除非用户明确要求，且先说明会覆盖什么）。
- ❌ `git commit --no-verify` 作为日常路径。
- ❌ 提交 `.env`、密钥、token、数据库文件、`node_modules/`、构建产物。
- ❌ `git add -A` 之后不复查就提交。
- ❌ 把多个不相关改动塞进一个提交。
- ❌ 在 hook 报错时直接改 hook 或删 marker 绕过。
- ❌ 把 token 打印到终端或写进日志。
