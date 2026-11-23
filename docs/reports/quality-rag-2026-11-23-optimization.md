# 质量审查报告 · 简历级优化批次

- 日期：2026-11-23
- 范围：`backend/app/observability.py`、`services/singleflight.py`、`api/chat.py`、`llm.py`、`services/chat.py`、`main.py`、`api/admin.py`、`scripts/bench.py`、`Dockerfile`、`docker-compose.yml`、`.github/workflows/ci.yml`、`README.md`
- 结论：**通过**（P0=0，P1=0）

## 1. 测试

- 全量 `pytest backend/tests`：**121 passed**，24.6s，EXIT=0。
- 新增覆盖：请求追踪头/指标快照（7 条）、SingleFlight 并发合并（4 条）、改写冷却与重试预算（6 条）。
- 压测暴露的 429 重试叠加问题已修复并有回归用例：`test_with_retry_respects_deadline` 要求预算不足时只尝试 1 次。

## 2. 安全扫描

`security_scan.py` 扫描 71 个文件：高危 10、中危 1，逐条复核后**无真实 P0**：

| 位置 | 判定 | 理由 |
|---|---|---|
| `backend/app/db.py:43` | 误报 | `tokenize='unicode61'` 是 FTS5 配置，不是凭证 |
| `backend/tests/conftest.py:32-33`、`test_api_auth.py:5-6`、`test_schemas.py:12/16/57` | 已接受 | 测试夹具口令，仅内存库使用 |
| `frontend/src/api/client.ts:3` | 误报 | `ACCESS_KEY='rag.access_token'` 是 localStorage 键名 |
| `frontend/src/views/LoginView.vue:34` | 已接受 | 演示账号快捷填充，需求指定 |
| `backend/app/admin` 内置口令 | 已接受 | `admin/123456` 为需求明确要求，首次登录后应修改 |

中危 `MessageBubble.vue:66` 的 `v-html`：渲染前已转义 `& < > " '`，仅替换受控的 `[n]` 角标为 `<span>`，模型输出无法注入标签，判定为已缓解。

## 3. 注释质量

`check_comments.py` 原始输出 P0=25/P1=188/P2=40，P0 全部是“注释密度低于阈值”，按本项目校准口径（密度与缺 docstring 记 P2；仅注释与实现矛盾、docstring 参数不存在、密钥写进注释记 P0）折算为 **P0=0、P1=0、P2=253**。

## 4. 代码卫生

- 无新增依赖；`.env`、`data/`、`frontend/dist/`、`.venv/`、`node_modules/` 均未跟踪。
- 新增文件均有模块/函数 docstring；`bench.py` 只读接口，不写业务数据。
- Docker 镜像不复制 `.env`；密钥通过 compose 环境变量注入。

## 5. 残留风险

1. 压测受百炼免费额度 RPM 限制，冷链路数据含 429 退避开销（首字 p50 2.4s），生产环境配额更宽时应更低。
2. 语义缓存阈值 0.95 在极端同义问法下可能召回旧答案，已有 `kb_id` 维度失效兜底。
3. `metrics` 为进程内环形缓冲，多副本部署需换成 Prometheus 等外部汇聚。
