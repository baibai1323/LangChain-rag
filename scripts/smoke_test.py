"""后端接口冒烟测试（不依赖前端，不调用大模型）。

用法：
    .venv\\Scripts\\python.exe scripts\\smoke_test.py
"""

from __future__ import annotations

import random
import string
import sys

import httpx

BASE = "http://127.0.0.1:8000"


def show(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}{(' - ' + detail) if detail else ''}")
    return ok


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=20.0)
    results: list[bool] = []

    r = client.get("/api/health")
    results.append(show("健康检查", r.status_code == 200, r.text[:120]))

    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    username = f"smoke_{suffix}"

    r = client.post("/api/auth/register", json={"username": username, "password": "test123456"})
    token = r.json().get("access_token", "") if r.status_code == 200 else ""
    results.append(show("注册普通用户", r.status_code == 200 and bool(token), r.text[:120]))

    r = client.post(
        "/api/auth/login", json={"username": "admin", "password": "123456"}
    )
    admin_token = r.json().get("access_token", "") if r.status_code == 200 else ""
    results.append(show("管理员登录", r.status_code == 200 and bool(admin_token), r.text[:120]))

    user_headers = {"Authorization": f"Bearer {token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    r = client.get("/api/auth/me", headers=user_headers)
    results.append(show("获取当前用户", r.status_code == 200 and r.json().get("role") == "user", r.text[:120]))

    r = client.post(
        "/api/kbs",
        headers=user_headers,
        json={"name": "越权测试", "description": "普通用户不应能创建"},
    )
    results.append(show("普通用户禁止建库", r.status_code == 403, f"status={r.status_code}"))

    r = client.post(
        "/api/kbs",
        headers=admin_headers,
        json={"name": f"冒烟测试库 {suffix}", "description": "smoke test"},
    )
    kb = r.json() if r.status_code in (200, 201) else {}
    results.append(
        show("管理员创建知识库", r.status_code in (200, 201) and bool(kb.get("id")), r.text[:150])
    )

    kb_id = kb.get("id", "")
    if kb_id:
        r = client.get("/api/kbs", headers=user_headers)
        results.append(show("普通用户可见知识库列表", r.status_code == 200 and len(r.json()) >= 1))

        r = client.get(f"/api/kbs/{kb_id}/stats", headers=admin_headers)
        results.append(show("知识库统计", r.status_code == 200, r.text[:120]))

        r = client.delete(f"/api/kbs/{kb_id}", headers=admin_headers)
        results.append(show("管理员删除知识库", r.status_code == 200, r.text[:120]))

    r = client.get("/api/admin/stats", headers=admin_headers)
    results.append(
        show(
            "管理员统计",
            r.status_code == 200 and "users" in r.json(),
            r.text[:120],
        )
    )

    r = client.get("/api/admin/stats", headers=user_headers)
    results.append(show("普通用户禁止访问统计", r.status_code == 403, f"status={r.status_code}"))

    r = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong-password"}
    )
    results.append(show("错误密码被拒绝", r.status_code == 401, f"status={r.status_code}"))

    failed = results.count(False)
    print(f"\n共 {len(results)} 项，通过 {len(results) - failed} 项，失败 {failed} 项")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
