# 电商商品知识库 RAG 问答系统

基于 **LangChain + 阿里云千问** 的企业级 RAG 知识库问答系统，面向电商商品场景。用户通过浏览器完成知识库问答，管理员维护商品资料；回答基于检索到的知识片段生成，并给出可追溯的引用来源。

## 功能一览

- **知识库管理**（仅管理员）：创建 / 编辑 / 删除知识库，上传 PDF、DOCX、TXT、Markdown、CSV、JSON，后台异步解析、切片、向量化、建索引，实时展示入库进度，支持切片预览、重新入库、检索测试。
- **知识库问答**（所有登录用户）：SSE 流式回答，先推送引用片段再逐字生成；回答中的 `[1]`、`[2]` 角标可点击查看原文，底部展示参考来源。
- **多用户多会话**：每个用户拥有独立会话列表，支持新建、重命名、置顶、删除；会话与消息持久化，重新登录可找回历史。
- **账号体系**：注册、登录、刷新令牌、修改密码；Argon2 密码哈希、JWT 双令牌、登录限流、审计日志。
- **权限控制**：内置管理员 `admin / 123456`，只有管理员能进入知识库管理页；普通用户只能问答。
- **管理与统计**：平台概览、近 7 天提问趋势、用户角色与禁用管理、模型调用记录、审计日志、缓存状态。
- **回答反馈**：对回答点赞 / 点踩，用于统计满意度。

## 技术栈

| 层 | 选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI + Uvicorn | 异步 IO、SSE 流式、OpenAPI 文档 |
| LLM 编排 | **LangChain 1.x** | `ChatOpenAI` + LCEL + 自定义 Retriever + 流式回调 |
| 大模型 | 阿里云百炼 qwen-max / qwen-turbo | OpenAI 兼容接口 |
| Embedding | text-embedding-v3（1024 维） | DashScope 批量向量化 |
| 重排 | gte-rerank-v2 | 原生 Rerank API |
| 关系存储 | SQLite（WAL）+ SQLAlchemy 2 Async | 用户、会话、消息、文档元数据 |
| 关键词检索 | SQLite FTS5 + jieba | 预分词 BM25，中文召回 |
| 向量库 | Chroma（本地持久化） | cosine 相似度检索 |
| 缓存 | diskcache | 精确缓存 + 语义缓存 |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Element Plus | 响应式 SPA |
| 认证 | Argon2 + PyJWT | Access / Refresh 双令牌 |

## 架构

```
浏览器 (Vue3 SPA)
   │  REST + SSE
   ▼
FastAPI
   ├── /api/auth          注册 / 登录 / 刷新 / 改密
   ├── /api/kbs           知识库 CRUD、检索测试
   ├── /api/kbs/{id}/documents  上传、切片、重入库
   ├── /api/conversations 会话与历史消息
   ├── /api/chat/stream   SSE 流式问答
   └── /api/admin         统计、用户、审计、调用记录
          │
          ├── 检索链：Query 改写 → 向量 Top20 + BM25 Top20
          │           → RRF(k=60) 融合 → gte-rerank 重排 Top6
          ├── 生成链：Prompt(上下文 3500 tokens) → qwen-max 流式
          ├── 缓存：问题精确缓存 → 语义缓存(cosine ≥ 0.95)
          └── 存储：SQLite(WAL) + Chroma + 本地 uploads
```

## 目录结构

```
backend/app
├── api/            # auth / kbs / documents / conversations / chat / admin
├── rag/            # extract / splitter / tokens / vectorstore / retriever / prompt
├── services/       # ingest / chat / cache / ratelimit
├── config.py       # Pydantic Settings
├── db.py           # 异步引擎、WAL、FTS5 DDL
├── models.py       # 12 张数据表
├── schemas.py      # Pydantic v2 模型
├── llm.py          # 千问 Chat / Embedding / Rerank 封装
├── security.py     # Argon2 + JWT
└── main.py         # 应用入口、静态托管、SPA fallback

frontend/src
├── api/            # fetch 封装、SSE 解析、接口定义
├── components/     # 消息气泡、引用抽屉
├── layouts/        # 侧边栏布局
├── views/          # 登录、注册、问答、知识库管理、统计、设置
├── stores/         # Pinia 认证状态
└── router/         # 路由与权限守卫

scripts
├── check_api.py    # 千问连通性自检
└── seed_demo.py    # 生成电商演示数据并入库
```

## 快速开始

### 1. 环境要求

- Python 3.11+（推荐 3.12；本项目在 3.14 上验证通过）
- Node.js 18+（推荐 20/22）
- 可访问 `dashscope.aliyuncs.com` 的网络

### 2. 配置密钥

在项目根目录创建 `.env`（不要提交到 Git）：

```ini
DASHSCOPE_API_KEY=sk-你的百炼APIKey
```

也可以直接设置同名环境变量。密钥仅在服务端读取，不会下发到浏览器。

### 3. 安装依赖

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt

cd frontend
npm install
npm run build
cd ..
```

### 4. 启动

```bat
start.bat
```

或手动：

```bat
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

浏览器打开 <http://127.0.0.1:8000>。

### 5. 演示数据（可选）

```bat
.venv\Scripts\python.exe scripts\seed_demo.py
```

会创建两个知识库（数码家电、服饰鞋包）、8 篇商品资料，以及演示账号 `demo / demo123`。

### 6. 账号

| 账号 | 密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| admin | 123456 | 管理员 | 问答 + 知识库管理 + 数据统计 |
| demo | demo123 | 普通用户 | 仅问答 |

## 关键设计

### 检索链路

1. **Query 改写**：结合最近 8 条历史，用 qwen-turbo 将追问改写为独立问题（失败自动回退原问题）。
2. **混合召回**：向量检索 Top20（Chroma）+ BM25 检索 Top20（FTS5 + jieba 预分词）。
3. **RRF 融合**：`score = Σ 1/(k + rank)`，`k=60`，无需调权重即可融合两路结果。
4. **重排**：gte-rerank-v2 对候选精排，取 Top6，低于阈值 0.05 的丢弃；再对“文档名命中查询词”的候选做小幅加权（≤0.08），让用户所说的商品优先；重排失败自动降级为 RRF 排序。
5. **上下文构建**：按 3500 token 预算装入父块（1200 字），同一父块下的子块去重后再编号，避免引用重复。

### 引用一致性

- 检索结果编号 `[1..n]` 同时写入 Prompt 与 `message_citations` 表。
- 生成结束后解析回答中的 `[n]`，只保留真实存在的编号；模型未标注时仍展示“参考来源”，保证可追溯。
- 前端角标与抽屉共用同一份引用数据，点击即可查看原文、页码与相关度。

### 性能优化

- **两级缓存**：问题规范化后精确命中；未命中再做 embedding 语义匹配（cosine ≥ 0.95），命中直接复用回答，省去检索与生成。
- **流式输出**：SSE 先推 `retrieval` 再推 `delta`，首字延迟约 0.5s；前端可随时中断。
- **异步全链路**：SQLAlchemy 2 Async、httpx、`asyncio.to_thread` 包装 Chroma 同步调用。
- **SQLite 调优**：WAL、`synchronous=NORMAL`、`busy_timeout=8000`、连接池 `pre_ping`。
- **入库解耦**：上传接口 202 立即返回，BackgroundTasks 异步解析与向量化，前端轮询任务进度。
- **批量 Embedding**：每批 10 条、并发 4、指数退避重试，降低限流风险。
- **前端按需加载**：路由懒加载、Element Plus 与 vendor 分包。

### 数据一致性

- 先写 `chunks` 再写 Chroma；Chroma 失败回滚删除切片，文档标记失败可重新入库。
- 删除文档 / 知识库时同步清理向量与缓存，避免脏召回。

## 验收结果

- **接口冒烟**：`scripts/smoke_test.py` 覆盖健康检查、注册、登录、鉴权、知识库 CRUD、管理员权限，12/12 通过。
- **单元测试**：`backend/tests/` 共 14 个文件、104 条用例，`pytest` 全绿（约 47s），整体语句覆盖 66%；`api/admin.py`、`models.py`、`schemas.py`、`security.py`、`rag/tokens.py`、`rag/prompt.py`、`services/ratelimit.py` 均为 100%。
  - 运行：`.\.venv\Scripts\python.exe -m pytest`（项目根目录）
  - 覆盖率：`.\.venv\Scripts\python.exe -m pytest --cov=backend/app --cov-report=term-missing`
  - 变异验证：把 `backend/app/rag/tokens.py` 的正则改回旧版后，`test_tokens_keeps_product_model_numbers` 与 `test_build_fts_query_quotes_every_term_and_joins_with_or` 立即失败，恢复后全绿。
  - 未覆盖：`api/chat.py`、`services/ingest.py`、`rag/vectorstore.py` 依赖真实 LLM / Chroma，留给集成测试。
  - 测试规范见项目内技能 [`.dsh/skills/unit-test-rag/SKILL.md`](.dsh/skills/unit-test-rag/SKILL.md)。

### 工程化配套：技能 / 子代理 / 提交门禁

从 `dsh-work` 迁入并按本项目口径改造，均落在仓库内，不依赖外部目录：

| 类型 | 位置 | 用途 |
|---|---|---|
| 技能 | `.dsh/skills/unit-test-rag/` | 本项目的测试矩阵、路由模板、假 LLM/向量库配方、Windows 沙箱坑 |
| 技能 | `.dsh/skills/security-audit/` | 安全扫描脚本 + 本项目重点与已接受例外 |
| 技能 | `.dsh/skills/check-comments/` | 注释质量扫描；密度与缺 docstring 记 P2，不阻断 |
| 技能 | `.dsh/skills/git-save/` | 安全提交：看 diff、排除敏感文件、走门禁 |
| 子代理 | `agents/tester/` | 补测试、跑全量、写 tester 凭证 |
| 子代理 | `agents/quality-engineer/` | 安全/注释/测试/卫生四维审查，出报告并写凭证 |
| 子代理 | `agents/gitcommit-agent/` | 按规范提交并处理 hook 拒绝 |
| 门禁 | `tools/quality-gate/` | pre-commit 校验凭证 + 亲自跑 pytest，P0/P1 不为 0 就拦 |

首次启用门禁：`python tools/quality-gate/install_hooks.py`（已安装到 `.git/hooks/pre-commit`）。
门禁的日常链路是：`tester` 跑测试写凭证 → `quality-engineer` 审查写凭证 → `git commit` 自动校验；凭证放在 `.git/quality-gate/`，代码一改就失效。
- **演示数据**：2 个知识库、8 篇商品资料全部入库成功（5 + 3 篇，共 17 个切片）。
- **检索质量**（数码家电知识库）：
  - “星耀 X50 支持卫星通信吗？” → 命中《星耀 X50 5G 手机商品详情》第 1 位。
  - “笔记本保修几年？” → 售后政策第 1 位、云帆 Pro 14 第 2 位。
  - “耳机降噪多少分贝” → 静界 Air 耳机第 1 位。
- **流式问答**：冷启动首字约 0.5–1.3s、整轮 4–15s；回答带 `[n]` 角标与可点击来源，`done` 事件返回引用数与耗时；重复问题命中缓存约 0.07s。
- **权限隔离**：普通用户访问 `/api/kbs` 创建接口返回 403，访问管理统计返回 403。
- **界面截图**：见 [`docs/screenshots`](docs/screenshots)（登录、问答与引用、引用抽屉、知识库管理、文档详情、数据统计）。

## 接口文档

启动后访问 <http://127.0.0.1:8000/api/docs> 查看 Swagger。

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/register | 注册 |
| POST | /api/auth/login | 登录 |
| POST | /api/auth/refresh | 刷新令牌 |
| POST | /api/auth/password | 修改密码 |
| GET | /api/kbs | 知识库列表 |
| POST | /api/kbs | 创建知识库（管理员） |
| POST | /api/kbs/{id}/documents | 上传文档（管理员） |
| GET | /api/tasks/{id} | 入库任务进度 |
| POST | /api/kbs/{id}/search-test | 检索测试（管理员） |
| GET | /api/conversations | 会话列表 |
| GET | /api/conversations/{id}/messages | 历史消息 |
| POST | /api/chat/stream | SSE 流式问答 |
| POST | /api/messages/{id}/feedback | 回答反馈 |
| GET | /api/admin/stats | 平台统计（管理员） |

SSE 事件顺序：`status` → `retrieval` → `delta`* → `done`；异常时 `error`。

## 常见问题

**Q：没有 `.env` 能启动吗？**
可以启动，但问答与入库会因缺少密钥失败。请在 `.env` 或环境变量中配置 `DASHSCOPE_API_KEY`。

**Q：上传后一直“处理中”？**
查看后端日志与文档状态；常见原因是 Embedding 限流或文件解析失败。可点击“重新入库”。

**Q：回答没有引用？**
确认知识库已有“已就绪”的文档，并用管理员的“检索测试”验证召回；阈值 0.05 会过滤低相关片段。

**Q：换电脑后历史会话还在吗？**
在，会话与消息存储在 SQLite 中；用同一账号登录即可恢复。

## 安全说明

- 密码使用 Argon2id 哈希，数据库中不保存明文。
- JWT Access Token 30 分钟、Refresh Token 7 天；改密后 `token_version` 提升，旧令牌立即失效。
- 登录 / 注册按 IP 限流（10 次/分钟），问答按用户限流（30 次/分钟）。
- 管理接口全部经过 `require_admin` 校验；会话与消息均校验归属，防止越权。
- 上传文件限制 20MB 与扩展名白名单，文件名做路径净化。
