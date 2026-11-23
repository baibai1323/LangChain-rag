"""千问(DashScope)连通性自检：对话 / 流式 / Embedding / Rerank。

只从环境变量读取密钥，不落盘、不回显。
用法:
    python scripts/check_api.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")
KEY = os.environ.get("DASHSCOPE_API_KEY", "").strip()
CHAT_MODEL = os.environ.get("QWEN_CHAT_MODEL", "qwen-max")
EMBED_MODEL = os.environ.get("QWEN_EMBED_MODEL", "text-embedding-v3")
EMBED_DIM = int(os.environ.get("QWEN_EMBED_DIM", "1024"))
RERANK_MODEL = os.environ.get("QWEN_RERANK_MODEL", "gte-rerank-v2")
RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    }


def post_json(url: str, payload: dict, timeout: int = 120) -> tuple[int, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw[:800]
    except Exception as exc:  # noqa: BLE001 - 自检脚本需要打印所有失败原因
        return -1, f"{type(exc).__name__}: {exc}"


def brief(data: object, limit: int = 600) -> str:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return text[:limit] + ("..." if len(text) > limit else "")


def check_chat() -> bool:
    print(f"[1/4] chat  model={CHAT_MODEL}")
    started = time.perf_counter()
    status, data = post_json(
        f"{BASE}/chat/completions",
        {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "user", "content": "用一句话介绍你自己，并说明你是什么模型。"}
            ],
            "max_tokens": 80,
            "temperature": 0.2,
        },
    )
    elapsed = time.perf_counter() - started
    if status != 200 or not isinstance(data, dict):
        print(f"      FAIL HTTP {status} ({elapsed:.1f}s): {brief(data)}")
        return False
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})
    print(f"      OK   {elapsed:.1f}s  usage={usage}")
    print(f"      reply: {content.strip()[:120]}")
    return True


def check_stream() -> bool:
    print(f"[2/4] stream model={CHAT_MODEL}")
    payload = {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": "从1数到10，用空格分隔。"}],
        "max_tokens": 60,
        "stream": True,
    }
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={**_headers(), "Accept": "text/event-stream"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_at = None
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (
                    event.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                )
                if delta:
                    if first_token_at is None:
                        first_token_at = time.perf_counter() - started
                    chunks.append(delta)
    except Exception as exc:  # noqa: BLE001
        print(f"      FAIL {type(exc).__name__}: {exc}")
        return False
    text = "".join(chunks)
    total = time.perf_counter() - started
    if not text:
        print(f"      FAIL 未收到任何增量内容 (total={total:.1f}s)")
        return False
    print(
        f"      OK   first_token={first_token_at:.2f}s total={total:.2f}s "
        f"chars={len(text)}"
    )
    print(f"      reply: {text[:120]}")
    return True


def check_embedding() -> bool:
    print(f"[3/4] embedding model={EMBED_MODEL} dim={EMBED_DIM}")
    started = time.perf_counter()
    status, data = post_json(
        f"{BASE}/embeddings",
        {
            "model": EMBED_MODEL,
            "input": ["商品支持七天无理由退货吗？", "这款耳机的续航是多久？"],
            "dimensions": EMBED_DIM,
            "encoding_format": "float",
        },
    )
    elapsed = time.perf_counter() - started
    if status != 200 or not isinstance(data, dict):
        print(f"      FAIL HTTP {status} ({elapsed:.1f}s): {brief(data)}")
        return False
    vectors = data.get("data", [])
    if len(vectors) != 2:
        print(f"      FAIL 期望 2 条向量，实际 {len(vectors)}: {brief(data)}")
        return False
    dim = len(vectors[0].get("embedding", []))
    usage = data.get("usage", {})
    print(f"      OK   {elapsed:.1f}s  count={len(vectors)} dim={dim} usage={usage}")
    return dim == EMBED_DIM


def check_rerank() -> bool:
    print(f"[4/4] rerank model={RERANK_MODEL}")
    started = time.perf_counter()
    status, data = post_json(
        RERANK_URL,
        {
            "model": RERANK_MODEL,
            "input": {
                "query": "耳机续航多久",
                "documents": [
                    "该耳机单次充电续航 8 小时，配合充电盒可达 32 小时。",
                    "本商品支持七天无理由退货。",
                    "耳机采用蓝牙 5.3，支持主动降噪。",
                ],
            },
            "parameters": {"return_documents": False, "top_n": 3},
        },
    )
    elapsed = time.perf_counter() - started
    if status != 200 or not isinstance(data, dict):
        print(f"      FAIL HTTP {status} ({elapsed:.1f}s): {brief(data)}")
        return False
    results = data.get("output", {}).get("results", [])
    scores = [(r.get("index"), round(float(r.get("relevance_score", 0)), 4)) for r in results]
    print(f"      OK   {elapsed:.1f}s  ranking(index,score)={scores}")
    return bool(results)


def main() -> int:
    if not KEY:
        print("缺少 DASHSCOPE_API_KEY 环境变量")
        return 2
    print(f"base_url={BASE}")
    print(f"key=***{KEY[-4:]} (len={len(KEY)})")
    results = {
        "chat": check_chat(),
        "stream": check_stream(),
        "embedding": check_embedding(),
        "rerank": check_rerank(),
    }
    print("\n===== 汇总 =====")
    for name, ok in results.items():
        print(f"{name:10s} {'PASS' if ok else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
