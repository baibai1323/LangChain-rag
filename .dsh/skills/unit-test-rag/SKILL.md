---
name: unit-test-rag
description: 给「电商知识库 RAG 问答系统」（FastAPI + SQLAlchemy 2 Async + Pydantic v2 + LangChain）编写、审查、运行和扩展 pytest 单元测试时使用。含本项目实测覆盖率、路由测试模板、假 LLM/向量库配方、Windows 沙箱坑与变异验证流程。
---

# 电商 RAG 系统 · 单元测试技能（本项目实测版）

**用途**：给 `backend/app` 里的模块补测试、审查已有用例、或把测试从「能跑」提升到「能抓 bug」。
**基线**：本技能所有数字与命令都在当前仓库实测过，不是模板占位。

---

## 0. 环境事实（先确认，别猜）

| 项 | 值 |
|---|---|
| 被测代码 | `D:\lanchain rag项目\backend\app\` |
| 解释器 | `D:\lanchain rag项目\.venv\Scripts\python.exe`（Python 3.14.5） |
| 框架 | pytest 9.2.0 + pytest-asyncio + pytest-cov |
| 测试目录 | `backend/tests/`（14 个测试文件 + `conftest.py`） |
| 配置 | 项目根 `pytest.ini`：`testpaths=backend/tests`、`-p no:tmpdir`、`asyncio_default_fixture_loop_scope=function` |
| 现状 | **104 passed / 45–47s / 总覆盖率 66%**（云依赖模块除外） |

标准命令（项目根）：

```powershell
$env:TMP='D:\lanchain rag项目\.tmp'; $env:TEMP=$env:TMP
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest --cov=backend/app --cov-report=term-missing
```

---

## 1. 测试矩阵（改动前先看这张表）

| 模块 | 测试文件 | 用例 | 覆盖率 |
|---|---|---|---|
| `rag/tokens.py` | `test_tokens.py` | 9 | 100% |
| `rag/splitter.py` | `test_splitter.py` | 4 | 96% |
| `rag/prompt.py` | `test_prompt.py` | 7 | 100% |
| `rag/extract.py` | `test_extract.py` | 8 | 64% |
| `rag/retriever.py`（纯函数） | `test_retriever.py` | 6 | 44% |
| `security.py` | `test_security.py` | 6 | 100% |
| `services/cache.py` | `test_cache.py` | 7 | 94% |
| `services/ratelimit.py` | `test_ratelimit.py` | 3 | 100% |
| `schemas.py` | `test_schemas.py` | 8 | 100% |
| `api/auth.py` | `test_api_auth.py` | 9 | 93% |
| `api/kbs.py` | `test_api_kbs.py` | 7 | 60% |
| `api/conversations.py` | `test_api_conversations.py` | 7 | 73% |
| `api/admin.py` | `test_api_admin.py` | 12 | 100% |
| `api/documents.py` | `test_api_documents.py` | 9 | 45% |

未覆盖且**不要硬凑**：`api/chat.py`(20%)、`services/ingest.py`(21%)、`rag/vectorstore.py`(36%)、`llm.py`(24%)。它们依赖真实 DashScope 与 Chroma，扩展方式见第 9 节。

---

## 2. 五步流程（照做，不跳步）

1. **提取契约**：读函数，写清输入域 / 输出 / 异常 / 副作用。
2. **枚举场景**：按第 4 节 6 类列清单，先清单后代码。
3. **选隔离层级**：纯函数直测 → 服务层替换依赖 → 路由层 TestClient + 临时库。
4. **写断言**：一个用例一个行为，断言具体值。
5. **跑红绿**：失败先按第 8 节判断「测试错」还是「代码错」。

---

## 3. 契约提取模板

```
被测单元：app.rag.tokens.build_fts_query
签名：build_fts_query(query: str) -> str
输入域：任意中英文查询串，可能为空
输出：'"星耀" OR "x50"'；无有效词返回 ""
异常：无
副作用：无
```

填不完 = 代码没读懂，不许开始写断言。

---

## 4. 场景清单（6 类，缺一类算漏测）

| 类别 | 针对本项目问自己 |
|---|---|
| 正常 | 正常提问能召回吗？正常登录返回双 token 吗？ |
| 边界 | 0/空/超长/预算刚好 3500/缓存刚好 0.95？ |
| 非法 | 文件名 `.exe`、`rating=5`、`role=hacker`？ |
| 异常 | 不存在的会话返回 404 而不是 500？ |
| 外部失效 | 重排挂了是否降级 RRF？Embedding 超时是否报错？ |
| 顺序/幂等 | 重复提问命中缓存？重复入库会不会重复切片？ |

---

## 5. 分层隔离（本项目的硬结构）

### 5.1 纯函数：直接测，不要 mock

`tokens`、`splitter`、`prompt`、`security`、`rrf_fuse`、`dedupe_by_parent` 都是纯函数，
参数化即可。例：

```python
@pytest.mark.parametrize("query,expected", [("X50 多少钱", '"x50" OR "多少钱"'), ("", "")])
def test_build_fts_query(query, expected):
    assert build_fts_query(query) == expected
```

### 5.2 服务层：临时目录 + monkeypatch

`CacheService` 读 `settings.cache_dir`，而它是只读 property：

```python
@pytest.fixture()
def cache(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)  # 不能直接改 cache_dir
    return CacheService()
```

限流是进程级滑动窗口，autouse fixture 清空：

```python
@pytest.fixture(autouse=True)
def reset_limiters():
    auth_limiter._hits.clear(); chat_limiter._hits.clear()
    yield
    auth_limiter._hits.clear(); chat_limiter._hits.clear()
```

### 5.3 路由层：三件套缺一不可

`backend/tests/conftest.py` 已封装：

1. **同步引擎建表 + 异步引擎跑请求**（避免连接跨事件循环复用）；
2. **`poolclass=NullPool`**，每个请求新连接；
3. **`TestClient(app)` 不加 `with`**（加了会触发 lifespan 的 `init_db/seed_admin`，写真实 `data/app.db`）。

```python
async def override_get_db():
    async with session_factory() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db
```

预置数据：`admin/admin123456`、`alice/user123456`、`KnowledgeBase(id="kbtest1")`。
fixture：`client`、`admin_headers`、`user_headers`、`tmp_path`、`db_path`。

---

## 6. 路由测试 5 个模板（本项目已覆盖，新接口照抄）

```python
def test_requires_auth(client):
    assert client.get("/api/admin/stats").status_code == 401

def test_requires_admin(client, user_headers):
    assert client.get("/api/admin/stats", headers=user_headers).status_code == 403

def test_not_found(client, admin_headers):
    assert client.get("/api/documents/nope/chunks", headers=admin_headers).status_code == 404

def test_validation(client, admin_headers):
    r = client.post("/api/kbs/kbtest1/documents", headers=admin_headers,
                    files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400

def test_state_change_invalidates_token(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    alice = next(u for u in users if u["username"] == "alice")
    token = _auth(client, "alice", "user123456")
    client.patch(f"/api/admin/users/{alice['id']}",
                 json={"status": "disabled"}, headers=admin_headers)
    assert client.get("/api/auth/me", headers=token).status_code == 401
```

**跨用户隔离**必须测：A 的会话 id 让 B 访问 → 404（不是 403，避免泄露存在性）。

---

## 7. 本项目的硬约定（断言要拴住它们）

1. **引用编号 = `build_context` 的 `selected` 顺序**：`[1]` 对应第一条，不能跳号、不能沿用历史编号。
2. **`[n]` 必须在 `1..len(selected)`**；越界由 `strip_invalid_citations` 删除。
3. **`build_context` 第一条永远装入**，后续超预算才截断——必须测「只够一条」分支。
4. **`build_messages` 只带最近 6 条历史**，user 内容同时包含【参考资料】与【用户问题】。
5. **BM25 必须保留型号**：`X50`、`5G`、`Pro14`、`3.5` 不能被分词丢掉（正则 `[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?`）。
6. **`estimate_tokens` 口径**：中文按字、英文 4 字符≈1 token、**至少记 1**；`"你好" == 3` 是现状。
7. **缓存 Key 归一化**：`lower()` + 去空白；语义阈值 0.95；TTL 3600s；按 KB 隔离。
8. **限流**：第 `limit+1` 次 429，`Retry-After ≥ 1`。
9. **JWT 双令牌**：`typ` 必须匹配；改密/禁用后 `token_version+1`，旧 token 立即 401。
10. **权限边界**：普通用户建库 403、看统计 403；会话/消息跨用户 404。

---

## 8. 断言红线与「假绿」

- ❌ `assert result` / `assert result is not None`。
- ❌ 一个用例断言 5 件事。
- ❌ 只测「不抛异常」。
- ❌ **迁就实现**：接口返回空列表就断言「是列表」，不去问「不存在的 id 该不该 404」。
- ✅ 每个模块至少一条失败路径。
- ✅ 断言契约，不断言巧合。

真实假绿案例（本项目已修）：

```python
# 原来 GET /api/documents/{id}/chunks 对不存在文档返回 200 + 空列表
# 如果测试写成 assert resp.status_code == 200，就把缺陷固化了
# 正确做法：断言 404，并修实现（已修）
```

---

## 9. 扩展路线：怎么把 chat / ingest 也测起来（不联网）

原则：**在最外层的依赖边界打桩**，不 mock 自己的业务函数。

### 9.1 测 SSE 问答（`api/chat.py`）

`chat.py` 直接 import 了 `retrieve`、`stream_answer`，因此 patch 模块属性：

```python
import app.api.chat as chat_mod

async def fake_retrieve(db, kb_id, query, **kwargs):
    return [RetrievedChunk(chunk_id="c1", doc_id="d1", doc_name="手机.md", page=1,
                           content="X50 售价 3999 元", parent_content="X50 售价 3999 元",
                           score=0.9, rerank_score=0.9)]

async def fake_stream(question, context, history):
    yield {"type": "first_token"}
    yield {"type": "delta", "text": "X50 售价 3999 元 [1]"}
    yield {"type": "usage", "usage": {"prompt_tokens": 10, "completion_tokens": 8}}

monkeypatch.setattr(chat_mod, "retrieve", fake_retrieve)
monkeypatch.setattr(chat_mod, "stream_answer", fake_stream)
monkeypatch.setattr(chat_mod.cache_service, "get_exact", lambda *a, **k: None)
monkeypatch.setattr(chat_mod.cache_service, "get_semantic", lambda *a, **k: None)
```

读 SSE：

```python
with client.stream("POST", "/api/chat/stream",
                   headers=user_headers,
                   json={"conversation_id": cid, "question": "X50 多少钱"}) as r:
    events = [line for line in r.iter_lines() if line.startswith("event:")]
```

断言：事件顺序 `status → retrieval → delta* → done`；`done.citations[0].rank == 1`；
消息落库后 `GET /api/conversations/{id}/messages` 能看到 assistant 内容；无命中时固定回复。

### 9.2 测入库（`services/ingest.py`）

直接调用协程，避开 HTTP 与 BackgroundTasks：

```python
monkeypatch.setattr("app.services.ingest.embed_texts", fake_embed)  # 返回固定向量
monkeypatch.setattr("app.services.ingest.vector_store", FakeStore())
await ingest_document(doc_id, task_id)
```

`FakeStore` 只需 `upsert/delete_doc`。断言：`Document.status == "ready"`、`chunk_count` 正确、
`IngestionTask.progress == 100`、失败时 `status == "failed"` 且 `finished_at` 非空。

### 9.3 不要做的事

- 不要给 `POST /api/kbs/{id}/documents` 发**合法**文件：`TestClient` 会同步执行背景任务 → 真连网络。
- 不要启动 lifespan；不要在测试里 `await asyncio.sleep` 等轮询。

---

## 10. 红了：测试错还是代码错

| 现象 | 判断 | 动作 |
|---|---|---|
| `AssertionError`，实际值符合契约 | 测试期望错 | 改测试 |
| `AssertionError`，实际值违反契约 | **代码 bug** | 修代码 + 报告，别改测试 |
| `ValidationError` 没抛 | 输入构造不合法 | 改测试 |
| `AttributeError: property has no setter` | 改了派生属性 | 改 `data_dir` 等源头 |
| `PermissionError [WinError 5]` | 沙箱 tmp 目录 ACL | 确认 `pytest.ini` 仍有 `-p no:tmpdir` |
| `MissingGreenlet` / `no such table` | 没走 override 或没建表 | 查 `dependency_overrides` |

**改生产代码的唯一理由**：测试暴露了契约不一致（如上面 chunks 404），并且改动有独立价值。
改完在交付说明里写清单。

---

## 11. 覆盖率与变异（实测）

- 目标：**关键纯函数/服务 100%，整体 ≥65%**；云依赖模块不计入硬指标。
- 覆盖率只回答「有没有漏」，不回答「测得对不对」。
- 每次全绿后做一次变异：改坏一处 → 必须有用例变红 → 还原。

本项目实测：

```powershell
Copy-Item backend\app\rag\tokens.py backend\app\rag\tokens.py.bak
# 把正则改回 [A-Za-z]+|\d+(?:\.\d+)?
.\.venv\Scripts\python.exe -m pytest backend/tests/test_tokens.py -q
# → 2 failed：test_tokens_keeps_product_model_numbers
#            test_build_fts_query_quotes_every_term_and_joins_with_or
Copy-Item backend\app\rag\tokens.py.bak backend\app\rag\tokens.py
```

改坏后一条都不红 = 这段逻辑没被测到。

---

## 12. Windows / 沙箱坑（都踩过）

1. **pytest tmpdir 崩溃**：`%TEMP%\pytest-of-*` 目录 ACL 异常，收尾 `cleanup_dead_symlinks` 报
   `PermissionError: [WinError 5]`。必须保留 `-p no:tmpdir`，用 `conftest.py` 里的项目内 `tmp_path`。
2. **PowerShell 别做中文文本往返**：`Get-Content -Raw | Set-Content` 会把 UTF-8 中文变乱码，
   甚至写出未闭合的三引号导致 `SyntaxError`。改文件用编辑器工具，或 `python -c` 显式 `encoding="utf-8"`。
3. **`npm.ps1` 未签名**：用 `npm.cmd`；`npm install` 加 `--ignore-scripts` 绕开沙箱 `spawn EPERM`。
4. **pip 直连 PyPI 会卡死**：用 `-i https://pypi.tuna.tsinghua.edu.cn/simple`，并把 `TMP`/`PIP_CACHE_DIR` 指到项目 `.tmp`。
5. **运行命令用 `cmd /c` 包一层**，否则 PowerShell 会把 stderr 当错误，`$LASTEXITCODE` 不可信。

---

## 13. 交付模板

```
## 测试文件
backend/tests/test_xxx.py

## 用例清单
1. test_yyy_normal —— 正常路径，3 组参数
2. test_yyy_rejects —— 非法输入
3. test_yyy_cross_user —— 越权隔离

## 运行结果
104 passed in 46s；总覆盖率 66%

## 未覆盖与原因
- api/chat.py：需要假 LLM，见技能第 9 节

## 发现并修复的代码问题
- GET /api/documents/{id}/chunks 未校验文档存在 → 已改 404
```

---

## 14. 禁止事项

- 不为迁就测试而改生产代码（契约缺陷除外，且需说明）。
- 不连真实 `data/app.db`、不连网络、不 `sleep`。
- 不测第三方库/标准库行为。
- 不写依赖执行顺序的用例。
- 不把测试放进 `app/`，统一 `backend/tests/`。
- 不为了让覆盖率好看去测 getter / `__init__`。

---

## 15. 迁移与演进记录

- 来源：`D:\dsh-work\agent开发学习\skills\unit-test-tiantian\SKILL.md`（同步 SQLModel 版）。
- 本版改动：异步 SQLAlchemy + `NullPool`、TestClient 依赖覆盖、LLM/Chroma 隔离配方、
  JWT/限流/引用编号约定、Windows 沙箱坑、真实覆盖率与变异证据。
- 基线测试：`backend/tests/`（104 条全绿）。
