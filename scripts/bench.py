"""真实链路基准测试：登录 → 建会话 → SSE 问答。

输出可直接写进 README 的表格，也把原始数据落到 `docs/benchmark.json`。
只测本机到 DashScope 的真实链路，不 mock，因此数字包含网络与模型推理时间。

用法（服务需先启动）：
    .\\.venv\\Scripts\\python.exe scripts\\bench.py --rounds 8 --burst 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx

QUESTIONS = [
    "星耀 X50 支持卫星通信吗？保修多久？",
    "云帆 Pro 14 的屏幕刷新率和色域是多少？",
    "静界 Air 的降噪深度是多少分贝？",
    "这款手机多少钱？有学生优惠吗？",
    "通勤双肩包能装下 16 英寸笔记本吗？下雨天防水吗？",
    "轻岚风衣的面料成分是什么？怎么洗涤？",
    "数码家电支持几天无理由退货？",
    "配送安装服务收费吗？大概多久上门？",
]


def percentile(values: list[float], ratio: float) -> float:
    """最近秩法分位数，和 observability 模块口径一致。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(ratio * (len(ordered) - 1))))
    return round(ordered[index], 1)


async def login(client: httpx.AsyncClient, username: str, password: str) -> dict:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def pick_kb(client: httpx.AsyncClient, headers: dict) -> str:
    response = await client.get("/api/kbs", headers=headers)
    response.raise_for_status()
    kbs = response.json()
    if not kbs:
        raise SystemExit("没有知识库，请先运行 scripts/seed_demo.py")
    return kbs[0]["id"]


async def new_conversation(client: httpx.AsyncClient, headers: dict, kb_id: str) -> str:
    response = await client.post(
        "/api/conversations", headers=headers, json={"kb_id": kb_id}
    )
    response.raise_for_status()
    return response.json()["id"]


async def ask(
    client: httpx.AsyncClient,
    headers: dict,
    conversation_id: str,
    question: str,
    use_cache: bool = True,
) -> dict:
    """发一条问题，返回首字延迟、总耗时、引用数与是否命中缓存。"""
    started = time.perf_counter()
    first_token_ms: float | None = None
    text_parts: list[str] = []
    done: dict = {}
    event = ""

    async with client.stream(
        "POST",
        "/api/chat/stream",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "question": question,
            "use_cache": use_cache,
        },
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if event == "delta":
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started) * 1000, 1)
                    text_parts.append(data.get("text", ""))
                elif event == "done":
                    done = data
                elif event == "error":
                    raise RuntimeError(data.get("message", "SSE error"))

    total_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "ttft_ms": first_token_ms or total_ms,
        "total_ms": total_ms,
        "chars": len("".join(text_parts)),
        "citations": len(done.get("citations", [])),
        "from_cache": bool(done.get("from_cache")),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="123456")
    parser.add_argument("--rounds", type=int, default=8, help="顺序提问轮数")
    parser.add_argument("--burst", type=int, default=5, help="同一问题的并发数")
    parser.add_argument("--no-cache", action="store_true", help="关闭精确/语义缓存，测冷链路")
    parser.add_argument("--gap", type=float, default=0.0, help="顺序请求之间的间隔秒数")
    parser.add_argument("--out", default="docs/benchmark.json")
    args = parser.parse_args()

    timeout = httpx.Timeout(180.0, connect=10.0)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        headers = await login(client, args.username, args.password)
        kb_id = await pick_kb(client, headers)
        conversation_id = await new_conversation(client, headers, kb_id)

        use_cache = not args.no_cache
        mode = "冷链路（缓存关闭）" if args.no_cache else "带缓存"
        print(f"知识库 {kb_id}，顺序 {args.rounds} 轮，{mode} …")
        sequential: list[dict] = []
        for index in range(args.rounds):
            question = QUESTIONS[index % len(QUESTIONS)]
            result = await ask(
                client, headers, conversation_id, question, use_cache=use_cache
            )
            result["question"] = question
            sequential.append(result)
            print(
                f"  {index + 1:02d} 首字 {result['ttft_ms']:>7.0f}ms "
                f"总 {result['total_ms']:>7.0f}ms 引用 {result['citations']} "
                f"缓存 {'是' if result['from_cache'] else '否'}"
            )
            if args.gap:
                await asyncio.sleep(args.gap)

        print(f"并发 {args.burst} 个相同问题 …")
        burst_question = QUESTIONS[0]
        burst_started = time.perf_counter()
        burst = await asyncio.gather(
            *(
                ask(client, headers, conversation_id, burst_question, use_cache=use_cache)
                for _ in range(args.burst)
            ),
            return_exceptions=True,
        )
        burst_wall_ms = round((time.perf_counter() - burst_started) * 1000, 1)
        burst_ok = [item for item in burst if isinstance(item, dict)]
        burst_errors = [str(item) for item in burst if not isinstance(item, dict)]

        cold = [item for item in sequential if not item["from_cache"]]
        warm = [item for item in sequential if item["from_cache"]]
        summary = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "base_url": args.base_url,
            "kb_id": kb_id,
            "rounds": args.rounds,
            "cache_disabled": args.no_cache,
            "cold": {
                "count": len(cold),
                "ttft_p50_ms": percentile([item["ttft_ms"] for item in cold], 0.50),
                "ttft_p95_ms": percentile([item["ttft_ms"] for item in cold], 0.95),
                "total_p50_ms": percentile([item["total_ms"] for item in cold], 0.50),
                "total_p95_ms": percentile([item["total_ms"] for item in cold], 0.95),
            },
            "warm": {
                "count": len(warm),
                "ttft_p50_ms": percentile([item["ttft_ms"] for item in warm], 0.50),
                "total_p50_ms": percentile([item["total_ms"] for item in warm], 0.50),
            },
            "burst": {
                "concurrency": args.burst,
                "success": len(burst_ok),
                "errors": burst_errors,
                "wall_ms": burst_wall_ms,
                "qps": round(len(burst_ok) / (burst_wall_ms / 1000), 2) if burst_wall_ms else 0.0,
                "ttft_p50_ms": percentile([item["ttft_ms"] for item in burst_ok], 0.50),
            },
            "sequential": sequential,
        }

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        all_ttft = [item["ttft_ms"] for item in sequential]
        all_total = [item["total_ms"] for item in sequential]
        print("\n结果")
        print(f"  模式: {'冷链路（缓存关闭）' if args.no_cache else '带缓存'}")
        print(f"  首字 p50/p95: {percentile(all_ttft, 0.5):.0f} / {percentile(all_ttft, 0.95):.0f} ms")
        print(f"  总耗时   p50/p95: {percentile(all_total, 0.5):.0f} / {percentile(all_total, 0.95):.0f} ms")
        if warm:
            print(f"  缓存命中 {len(warm)} 次，命中后总耗时 p50 {percentile([w['total_ms'] for w in warm], 0.5):.0f} ms")
        print(f"  并发 {args.burst} 墙钟 {burst_wall_ms:.0f} ms，成功 {len(burst_ok)}，吞吐 {summary['burst']['qps']} req/s")
        print(f"  原始数据已写入 {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
