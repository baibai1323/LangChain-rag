# -*- coding: utf-8 -*-
"""quality-engineer 的只读护栏：审查前后各跑一次，用哈希证明「没改代码」。

用法（主 agent 在派发前后各执行一次）：

    python guard.py snapshot --repo D:\\lanchain rag项目 --out D:\\lanchain rag项目\\.tmp\\qe-snap.json
    # ...派发 quality-engineer 审查...
    python guard.py verify --repo D:\\lanchain rag项目 --snapshot D:\\lanchain rag项目\\.tmp\\qe-snap.json

verify 发现任何新增/修改/删除都会打印明细并以退出码 1 结束。
需要撤销误改时加 --restore：从快照时留的镜像副本还原，不依赖 git，
因此不会把「审查前就存在的未提交改动」一起冲掉。

只跳过构建产物、依赖目录和二进制文件；源码、配置、文档都会被计入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

# 这些目录里的内容不属于「源码」，既慢又没必要纳入比对。
EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".python312",
    "dist",
    "build",
    "release",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    # 本项目特有：运行数据、临时目录、前端构建产物、本地工具
    "data",
    "uploads",
    ".pytest-work",
    ".tmp",
    ".tools",
    ".npm-cache",
}

# 二进制和数据库文件按内容哈希没有意义，直接跳过。
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".zip", ".exe", ".dll",
    ".so", ".dylib", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2",
    ".pdf", ".docx", ".xlsx", ".bin", ".arrow", ".parquet", ".pkl",
}

# 这些文件名里有密钥或运行态数据，绝不能复制进快照镜像。
SKIP_NAMES = {".env", ".env.local", ".coverage", "jwt_secret"}


def iter_files(root: Path):
    """遍历仓库里的「文本类」文件，跳过依赖目录和二进制后缀。"""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield path


def sha256(path: Path) -> str:
    """分块读取文件内容，避免一次性把大文件读进内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(args) -> int:
    root = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    mirror = out.with_suffix("")
    if mirror.exists():
        shutil.rmtree(mirror)
    mirror.mkdir(parents=True)

    files: dict[str, str] = {}
    for path in iter_files(root):
        rel = path.relative_to(root).as_posix()
        files[rel] = sha256(path)
        target = mirror / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    data = {"root": str(root), "mirror": str(mirror), "files": files}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已记录快照：{len(files)} 个文件 -> {out}")
    return 0


def current(root: Path) -> dict[str, str]:
    """重新计算当前文件哈希。"""
    return {p.relative_to(root).as_posix(): sha256(p) for p in iter_files(root)}


def diff(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """返回 (修改, 新增, 删除) 三组相对路径。"""
    changed = sorted(p for p in before.keys() & after.keys() if before[p] != after[p])
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    return changed, added, removed


def restore(root: Path, mirror: Path, changed: list[str], added: list[str], removed: list[str]) -> None:
    """用快照镜像还原：新增的删掉，修改/删除的从镜像复制回来。"""
    for rel in added:
        target = root / rel
        if target.is_file():
            target.unlink()
    for rel in changed + removed:
        source = mirror / rel
        if source.is_file():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def verify(args) -> int:
    root = Path(args.repo).resolve()
    data = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    changed, added, removed = diff(data["files"], current(root))
    total = len(changed) + len(added) + len(removed)
    if not total:
        print("OK：审查期间仓库没有任何改动。")
        return 0

    print(f"FAIL：审查期间有 {total} 处改动（修改 {len(changed)} / 新增 {len(added)} / 删除 {len(removed)}）")
    for label, items in (("修改", changed), ("新增", added), ("删除", removed)):
        for rel in items:
            print(f"  [{label}] {rel}")

    if args.restore:
        restore(root, Path(data["mirror"]), changed, added, removed)
        print("已按快照还原误改；请重新跑一次 verify 确认。")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="quality-engineer 只读护栏")
    sub = parser.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser("snapshot", help="审查前记录文件哈希与镜像副本")
    snap.add_argument("--repo", required=True)
    snap.add_argument("--out", required=True)
    snap.set_defaults(func=snapshot)

    check = sub.add_parser("verify", help="审查后比对并判定是否违规")
    check.add_argument("--repo", required=True)
    check.add_argument("--snapshot", required=True)
    check.add_argument("--restore", action="store_true", help="发现改动时按快照还原")
    check.set_defaults(func=verify)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
