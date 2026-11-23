"""并发压测脚本：问答稳态、尖峰合并、认证风暴与混合行为。

设计目标：
- 用真实 HTTP/SSE 链路压测，不 mock 模型，因此带预算保护（默认 20 元）。
- 每个虚拟用户有独立账号、独立 IP（配合服务端 TRUST_PROXY_HEADERS）、独立会话。
- 支持阶梯加压：--vus "10,25,50,100"。

常用命令：
    python scripts/loadtest.py prepare --users 100
    python scripts/loadtest.py chat --vus 100 --duration 180 --think "45,75"
    python scripts/loadtest.py burst --vus 50
    python scripts/loadtest.py auth-register --users 50
    python scripts/loadtest.py auth-login --vus 100 --wrong-ratio 0.3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

QUESTIONS = [
    "星耀 X50 支持卫星通信吗？保修多久？",
    "云帆 Pro 14 的屏幕参数和电池容量是多少？",
    "静界 Air 耳机的降噪深度和续航怎么样？",
    "这款手机多少钱？最近有什么优惠？",
    "笔记本保修几年？主板和电池都保吗？",
    "通勤双肩包能装下 16 英寸笔记本吗？防水吗？",
    "轻岚风衣的面料和尺码怎么选？",
    "支持 7 天无理由退货吗？退货运费谁承担？",
]

USERS_FILE = Path(".loadtest/users.json")


# ---------------------------------------------------------------- 预算与统计


@dataclass
class Budget:
    """按 token 估算花费，超过上限就停止发新请求。"""

    limit: float = 20.0
    input_per_k: float = 0.0024
    output_per_k: float = 0.0096
    spent: float = 0.0
    calls: int = 0
    exceeded: bool = False

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.calls += 1
        self.spent += prompt_tokens / 1000 * self.input_per_k
        self.spent += completion_tokens / 1000 * self.output_per_k
        if self.spent >= self.limit:
            self.exceeded = True


@dataclass
class Sample:
    """一条请求的观测结果。"""

    ok: bool
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    status: int = 0
    cached: bool = False
    citations: int = 0
    error: str = ""
    kind: str = "chat"


def percentile(values: list[float], ratio: float) -> float:
    """最近秩法分位数，空列表返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(ratio * (len(ordered) - 1))))
    return ordered[index]


def summarize(samples: list[Sample]) -> dict:
    """把样本聚合成报告用的指标。"""
    ok = [s for s in samples if s.ok]
    chats = [s for s in ok if s.kind == "chat"]
    cold = [s.ttft_ms for s in chats if not s.cached]
    warm = [s.ttft_ms for s in chats if s.cached]
    total = [s.total_ms for s in ok]
    status: dict[str, int] = {}
    for s in samples:
        key = str(s.status) if s.status else "conn_error"
        status[key] = status.get(key, 0) + 1
    return {
        "requests": len(samples),
        "success": len(ok),
        "errors": len(samples) - len(ok),
        "error_rate": round((len(samples) - len(ok)) / len(samples), 4) if samples else 0,
        "cache_hits": sum(1 for s in ok if s.cached),
        "ttft_ms": {
            "p50": round(percentile(cold + warm, 0.5), 1),
            "p95": round(percentile(cold + warm, 0.95), 1),
            "p99": round(percentile(cold + warm, 0.99), 1),
        },
        "ttft_cold_ms": {
            "count": len(cold),
            "p50": round(percentile(cold, 0.5), 1),
            "p95": round(percentile(cold, 0.95), 1),
        },
        "ttft_cached_ms": {
            "count": len(warm),
            "p50": round(percentile(warm, 0.5), 1),
            "p95": round(percentile(warm, 0.95), 1),
        },
        "total_ms": {
            "p50": round(percentile(total, 0.5), 1),
            "p95": round(percentile(total, 0.95), 1),
            "p99": round(percentile(total, 0.99), 1),
        },
        "status": status,
        "errors_detail": [s.error for s in samples if not s.ok][:10],
    }


# ---------------------------------------------------------------- HTTP 客户端


def sse_headers(token: str, ip: str) -> dict[str, str]:
    """带鉴权与模拟客户端 IP 的请求头。"""
    return {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-For": ip,
        "Accept": "text/event-stream",
    }


def fake_ip(index: int) -> str:
    """给每个虚拟用户分配独立 IP，避免认证限流把所有请求算到同一个 IP。"""
    return f"10.{(index // 250) % 250}.{index % 250}.{7 + index % 200}"


async def login(client: httpx.AsyncClient, base: str, username: str, password: str, ip: str) -> dict:
    resp = await client.post(
        f"{base}/api/auth/login",
        json={"username": username, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    resp.raise_for_status()
    return resp.json()


async def register(client: httpx.AsyncClient, base: str, username: str, password: str, ip: str) -> dict:
    resp = await client.post(
        f"{base}/api/auth/register",
        json={"username": username, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    resp.raise_for_status()
    return resp.json()


async def first_kb(client: httpx.AsyncClient, base: str, token: str) -> str:
    resp = await client.get(
        f"{base}/api/kbs", headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    items = resp.json()
    if not items:
        raise RuntimeError("知识库为空，先跑 seed_demo.py")
    return items[0]["id"]


async def new_conversation(client: httpx.AsyncClient, base: str, token: str, kb_id: str) -> str:
    resp = await client.post(
        f"{base}/api/conversations",
        json={"kb_id": kb_id, "title": "压测会话"},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


async def ask(
    client: httpx.AsyncClient,
    base: str,
    token: str,
    conversation_id: str,
    question: str,
    ip: str,
    budget: Budget,
    use_cache: bool = True,
) -> Sample:
    """发一条 SSE 问答，解析首字、总耗时、引用与 usage。"""
    started = time.perf_counter()
    first_token: float | None = None
    event = ""
    done: dict = {}
    error_text = ""
    status_code = 200

    try:
        async with client.stream(
            "POST",
            f"{base}/api/chat/stream",
            headers=sse_headers(token, ip),
            json={
                "conversation_id": conversation_id,
                "question": question,
                "use_cache": use_cache,
            },
        ) as resp:
            status_code = resp.status_code
            if resp.status_code != 200:
                await resp.aread()
                body = resp.text[:200]
                return Sample(
                    ok=False,
                    status=status_code,
                    total_ms=(time.perf_counter() - started) * 1000,
                    error=f"HTTP {status_code}: {body}",
                )
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    payload = line[5:].strip()
                    if event == "delta" and first_token is None:
                        first_token = time.perf_counter() - started
                    elif event == "done":
                        done = json.loads(payload)
                    elif event == "error":
                        error_text = json.loads(payload).get("message", "")
    except Exception as exc:  # noqa: BLE001 - 压测要把网络异常也计入错误率
        return Sample(
            ok=False,
            status=status_code,
            total_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )

    total = (time.perf_counter() - started) * 1000
    if error_text or not done:
        return Sample(
            ok=False,
            status=status_code,
            total_ms=total,
            error=error_text or "SSE 未返回 done",
        )

    usage = done.get("usage") or {}
    budget.add(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
    return Sample(
        ok=True,
        ttft_ms=(first_token or 0) * 1000,
        total_ms=total,
        status=status_code,
        cached=bool(done.get("from_cache")),
        citations=len(done.get("citations") or []),
    )


# ---------------------------------------------------------------- 用户准备


async def cmd_prepare(args: argparse.Namespace) -> None:
    """注册压测账号并为每人建一个会话。"""
    base = args.base_url
    users: list[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as client:
        admin = await login(client, base, "admin", "123456", fake_ip(0))
        token = admin["access_token"]
        kb_id = args.kb_id or await first_kb(client, base, token)
        for i in range(1, args.users + 1):
            username = f"load{i:03d}"
            ip = fake_ip(i)
            try:
                data = await register(client, base, username, "load123456", ip)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 409:
                    raise
                data = await login(client, base, username, "load123456", ip)
            conv_id = await new_conversation(client, base, data["access_token"], kb_id)
            users.append(
                {
                    "username": username,
                    "password": "load123456",
                    "token": data["access_token"],
                    "conversation_id": conv_id,
                    "ip": ip,
                }
            )
            if i % 10 == 0:
                print(f"  已准备 {i}/{args.users}")
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps({"kb_id": kb_id, "users": users}, ensure_ascii=False), "utf-8")
    print(f"完成：{len(users)} 个账号，知识库 {kb_id}，状态写入 {USERS_FILE}")


def load_users(limit: int | None = None) -> tuple[str, list[dict]]:
    """读取 prepare 生成的账号。"""
    if not USERS_FILE.exists():
        raise SystemExit("缺少 .loadtest/users.json，先跑 prepare")
    data = json.loads(USERS_FILE.read_text("utf-8"))
    users = data["users"][:limit] if limit else data["users"]
    return data["kb_id"], users


# ---------------------------------------------------------------- 场景


@dataclass
class Run:
    """一次压测运行的共享状态。"""

    base: str
    budget: Budget
    samples: list[Sample] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def record(self, sample: Sample) -> None:
        async with self.lock:
            self.samples.append(sample)


async def chat_worker(
    run: Run,
    user: dict,
    duration: float,
    think: tuple[float, float],
    use_cache: bool = True,
    ramp: float = 0.0,
) -> None:
    """模拟一个持续提问的虚拟用户；ramp 用于错峰启动，接近真实用户到访节奏。"""
    if ramp > 0:
        await asyncio.sleep(ramp)
    deadline = time.monotonic() + duration
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=180)) as client:
        while time.monotonic() < deadline and not run.budget.exceeded:
            question = random.choice(QUESTIONS)
            sample = await ask(
                client,
                run.base,
                user["token"],
                user["conversation_id"],
                question,
                user["ip"],
                run.budget,
                use_cache=use_cache,
            )
            await run.record(sample)
            if run.budget.exceeded:
                break
            await asyncio.sleep(random.uniform(*think))


async def cmd_chat(args: argparse.Namespace) -> None:
    """稳态问答：N 个虚拟用户持续提问。"""
    kb_id, users = load_users(args.vus)
    think = tuple(float(x) for x in args.think.split(","))
    budget = Budget(limit=args.budget)
    run = Run(base=args.base_url, budget=budget)
    started = time.monotonic()
    await asyncio.gather(
        *(
            chat_worker(
                run,
                u,
                args.duration,
                think,
                not args.no_cache,
                args.ramp * index / max(args.vus, 1),
            )
            for index, u in enumerate(users[: args.vus])
        )
    )
    elapsed = time.monotonic() - started
    report = summarize(run.samples)
    report.update(
        {
            "scenario": "chat",
            "vus": args.vus,
            "duration_s": round(elapsed, 1),
            "qps": round(len(run.samples) / elapsed, 2),
            "cost_cny": round(budget.spent, 3),
            "model_calls": budget.calls,
            "budget_exceeded": budget.exceeded,
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


async def cmd_burst(args: argparse.Namespace) -> None:
    """尖峰：N 个用户同一时刻问同一个问题，验证并发合并。"""
    kb_id, users = load_users(args.vus)
    budget = Budget(limit=args.budget)
    run = Run(base=args.base_url, budget=budget)
    question = random.choice(QUESTIONS)
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=180)) as client:

        async def one(user: dict) -> None:
            sample = await ask(
                client,
                args.base_url,
                user["token"],
                user["conversation_id"],
                question,
                user["ip"],
                budget,
                use_cache=False,
            )
            await run.record(sample)

        await asyncio.gather(*(one(u) for u in users[: args.vus]))
    elapsed = time.monotonic() - started
    report = summarize(run.samples)
    report.update(
        {
            "scenario": "burst",
            "vus": args.vus,
            "wall_ms": round(elapsed * 1000, 1),
            "cost_cny": round(budget.spent, 3),
            "model_calls": budget.calls,
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


async def cmd_auth_register(args: argparse.Namespace) -> None:
    """注册风暴：并发创建账号，测 Argon2 内存与写库竞争。"""
    run = Run(base=args.base_url, budget=Budget(limit=args.budget))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as client:

        async def one(i: int) -> None:
            started = time.perf_counter()
            username = f"reg{int(time.time())}{i:03d}"
            try:
                await register(client, args.base_url, username, "reg123456", fake_ip(i))
                sample = Sample(ok=True, status=200, total_ms=(time.perf_counter() - started) * 1000)
            except Exception as exc:  # noqa: BLE001
                sample = Sample(
                    ok=False,
                    total_ms=(time.perf_counter() - started) * 1000,
                    error=f"{type(exc).__name__}: {exc}",
                )
            await run.record(sample)

        await asyncio.gather(*(one(i) for i in range(args.users)))
    report = summarize(run.samples)
    report.update({"scenario": "auth-register", "users": args.users})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


async def cmd_auth_login(args: argparse.Namespace) -> None:
    """登录风暴：正确密码与错误密码混合，验证 401 不升级成 5xx。"""
    kb_id, users = load_users(args.vus)
    run = Run(base=args.base_url, budget=Budget(limit=args.budget))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as client:

        async def one(i: int, user: dict) -> None:
            started = time.perf_counter()
            wrong = random.random() < args.wrong_ratio
            password = "bad-password" if wrong else user["password"]
            try:
                resp = await client.post(
                    f"{args.base_url}/api/auth/login",
                    json={"username": user["username"], "password": password},
                    headers={"X-Forwarded-For": user["ip"]},
                )
                expected = 401 if wrong else 200
                ok = resp.status_code == expected
                await run.record(
                    Sample(
                        ok=ok,
                        status=resp.status_code,
                        total_ms=(time.perf_counter() - started) * 1000,
                        error="" if ok else f"期望 {expected}，实际 {resp.status_code}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                await run.record(
                    Sample(
                        ok=False,
                        total_ms=(time.perf_counter() - started) * 1000,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        await asyncio.gather(*(one(i, u) for i, u in enumerate(users[: args.vus])))
    report = summarize(run.samples)
    report.update(
        {
            "scenario": "auth-login",
            "vus": args.vus,
            "wrong_ratio": args.wrong_ratio,
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


async def cmd_auth_token(args: argparse.Namespace) -> None:
    """令牌链路：登录 → me → refresh → logout。"""
    kb_id, users = load_users(args.vus)
    run = Run(base=args.base_url, budget=Budget(limit=args.budget))
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as client:

        async def one(user: dict) -> None:
            started = time.perf_counter()
            try:
                data = await login(client, args.base_url, user["username"], user["password"], user["ip"])
                token = data["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                await client.get(f"{args.base_url}/api/auth/me", headers=headers)
                refreshed = await client.post(
                    f"{args.base_url}/api/auth/refresh",
                    json={"refresh_token": data["refresh_token"]},
                    headers={"X-Forwarded-For": user["ip"]},
                )
                refreshed.raise_for_status()
                await client.post(
                    f"{args.base_url}/api/auth/logout",
                    headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
                )
                await run.record(Sample(ok=True, status=200, total_ms=(time.perf_counter() - started) * 1000))
            except Exception as exc:  # noqa: BLE001
                await run.record(
                    Sample(
                        ok=False,
                        total_ms=(time.perf_counter() - started) * 1000,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        await asyncio.gather(*(one(u) for u in users[: args.vus]))
    report = summarize(run.samples)
    report.update({"scenario": "auth-token", "vus": args.vus})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


async def cmd_mixed(args: argparse.Namespace) -> None:
    """混合行为：70% 问答、20% 历史消息、10% 认证往返。"""
    kb_id, users = load_users(args.vus)
    budget = Budget(limit=args.budget)
    run = Run(base=args.base_url, budget=budget)
    think = tuple(float(x) for x in args.think.split(","))
    deadline = time.monotonic() + args.duration

    async def one(user: dict) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=180)) as client:
            while time.monotonic() < deadline and not budget.exceeded:
                roll = random.random()
                started = time.perf_counter()
                if roll < 0.7:
                    sample = await ask(
                        client,
                        args.base_url,
                        user["token"],
                        user["conversation_id"],
                        random.choice(QUESTIONS),
                        user["ip"],
                        budget,
                        use_cache=not args.no_cache,
                    )
                elif roll < 0.9:
                    try:
                        resp = await client.get(
                            f"{args.base_url}/api/conversations/{user['conversation_id']}/messages",
                            headers={"Authorization": f"Bearer {user['token']}"},
                        )
                        resp.raise_for_status()
                        sample = Sample(
                            ok=True,
                            total_ms=(time.perf_counter() - started) * 1000,
                            status=resp.status_code,
                        )
                    except Exception as exc:  # noqa: BLE001
                        sample = Sample(
                            ok=False,
                            total_ms=(time.perf_counter() - started) * 1000,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                else:
                    try:
                        resp = await client.get(
                            f"{args.base_url}/api/auth/me",
                            headers={"Authorization": f"Bearer {user['token']}"},
                        )
                        resp.raise_for_status()
                        sample = Sample(
                            ok=True,
                            total_ms=(time.perf_counter() - started) * 1000,
                            status=resp.status_code,
                        )
                    except Exception as exc:  # noqa: BLE001
                        sample = Sample(
                            ok=False,
                            total_ms=(time.perf_counter() - started) * 1000,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                await run.record(sample)
                await asyncio.sleep(random.uniform(*think))

    elapsed_start = time.monotonic()
    await asyncio.gather(*(one(u) for u in users[: args.vus]))
    elapsed = time.monotonic() - elapsed_start
    report = summarize(run.samples)
    report.update(
        {
            "scenario": "mixed",
            "vus": args.vus,
            "duration_s": round(elapsed, 1),
            "cost_cny": round(budget.spent, 3),
            "model_calls": budget.calls,
        }
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    save_report(args, report)


# ---------------------------------------------------------------- 报告


def save_report(args: argparse.Namespace, report: dict) -> None:
    """把一次运行追加写入 docs/loadtest-<日期>.json。"""
    out = Path(args.out) if args.out else Path("docs") / f"loadtest-{datetime.now():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if out.exists():
        try:
            history = json.loads(out.read_text("utf-8"))
        except json.JSONDecodeError:
            history = []
    history.append({"generated_at": datetime.now().isoformat(timespec="seconds"), **report})
    out.write_text(json.dumps(history, ensure_ascii=False, indent=2), "utf-8")
    print(f"\n已写入 {out}")


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="电商 RAG 知识库并发压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--budget", type=float, default=20.0, help="模型花费上限（元）")
    parser.add_argument("--out", default="")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="注册压测账号并建会话")
    prepare.add_argument("--users", type=int, default=100)
    prepare.add_argument("--kb-id", default="")
    prepare.set_defaults(func=cmd_prepare)

    chat = sub.add_parser("chat", help="稳态问答")
    chat.add_argument("--vus", type=int, default=100)
    chat.add_argument("--duration", type=float, default=180)
    chat.add_argument("--think", default="45,75")
    chat.add_argument("--no-cache", action="store_true", help="关闭缓存，测真实冷链路")
    chat.add_argument("--ramp", type=float, default=0.0, help="在多少秒内均匀错峰启动所有 VU")
    chat.set_defaults(func=cmd_chat)

    burst = sub.add_parser("burst", help="尖峰同问")
    burst.add_argument("--vus", type=int, default=50)
    burst.set_defaults(func=cmd_burst)

    reg = sub.add_parser("auth-register", help="注册风暴")
    reg.add_argument("--users", type=int, default=50)
    reg.set_defaults(func=cmd_auth_register)

    login_cmd = sub.add_parser("auth-login", help="登录风暴")
    login_cmd.add_argument("--vus", type=int, default=100)
    login_cmd.add_argument("--wrong-ratio", type=float, default=0.0)
    login_cmd.set_defaults(func=cmd_auth_login)

    token = sub.add_parser("auth-token", help="令牌链路")
    token.add_argument("--vus", type=int, default=100)
    token.set_defaults(func=cmd_auth_token)

    mixed = sub.add_parser("mixed", help="混合行为")
    mixed.add_argument("--vus", type=int, default=100)
    mixed.add_argument("--duration", type=float, default=180)
    mixed.add_argument("--think", default="20,40")
    mixed.add_argument("--no-cache", action="store_true")
    mixed.set_defaults(func=cmd_mixed)
    return parser


def main() -> None:
    """同步入口。"""
    args = build_parser().parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
