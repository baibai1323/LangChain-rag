"""注释质量体检 —— common-check 技能的度量脚本。

只做能机器判定的事（密度、函数文档、可疑注释、命名与魔法数字），
语义是否与代码一致、小白能否读懂，交给人/AI 按 SKILL.md 的 rubric 判断。

用法：
    python check_comments.py <文件或目录> [...] [--min-ratio 0.3] [--json]

退出码：0 无 P0/P1 问题；1 有；2 参数或解析错误。
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

PY_EXT = {".py"}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".vue", ".mjs", ".cjs"}
SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "dist", "build", ".pytest_cache"}

# 这些单字母/短名在循环与坐标里是惯例，不算命名问题
NAME_WHITELIST = {"i", "j", "k", "n", "m", "x", "y", "z", "_", "id", "db", "ok"}

# 这些数字属于常见约定，不强制加注释
MAGIC_WHITELIST = {0, 1, -1, 2, 10, 100, 1000}

COMMENTED_CODE_RE = re.compile(
    r"^#\s*(def |class |import |from \w+ import|if |for |while |return |print\(|elif |else:)"
    r"|^#\s*[A-Za-z_]\w*\s*=\s*[^=]"
)


def is_blank(line: str) -> bool:
    """空行与只有空白的行不算有效行。"""
    return not line.strip()


def density_of(comments: set[int], lines: list[str]) -> tuple[int, int, float]:
    """返回（注释行数, 有效行数, 密度）。密度 = 注释行 / 有效行。"""
    effective = [i + 1 for i, line in enumerate(lines) if not is_blank(line)]
    hit = [n for n in effective if n in comments]
    ratio = len(hit) / len(effective) if effective else 0.0
    return len(hit), len(effective), ratio


def docstring_span(node: ast.AST) -> set[int]:
    """把函数/类的 docstring 所占行号收集出来，它们也算注释行。"""
    span: set[int] = set()
    body = getattr(node, "body", [])
    if not body:
        return span
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        end = getattr(first, "end_lineno", None) or first.lineno
        span.update(range(first.lineno, end + 1))
    return span


def analyze_python(path: Path, min_ratio: float) -> dict:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    result = {
        "file": str(path),
        "kind": "python",
        "issues": [],
        "stats": {},
    }

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        result["issues"].append({"level": "P0", "line": exc.lineno or 0, "msg": f"语法错误：{exc.msg}"})
        return result

    # 1) 收集注释行：纯注释行 + docstring 行
    pure_comments: dict[int, str] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                pure_comments[tok.start[0]] = tok.string
    except (tokenize.TokenError, IndentationError):
        pass

    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc_lines |= docstring_span(node)

    comment_lines = set(pure_comments) | doc_lines
    n_comment, n_effective, ratio = density_of(comment_lines, lines)
    result["stats"]["comment_lines"] = n_comment
    result["stats"]["effective_lines"] = n_effective
    result["stats"]["density"] = round(ratio, 3)

    if ratio < min_ratio:
        result["issues"].append(
            {
                "level": "P0",
                "line": 0,
                "msg": f"注释密度 {ratio:.0%}，低于要求的 {min_ratio:.0%}（每 10 行有效代码至少 3 行注释）",
            }
        )

    # 2) 逐个函数检查：文档、长函数缺块内注释、参数说明是否对得上
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(node)
        end = getattr(node, "end_lineno", None) or node.lineno
        span = range(node.lineno, end + 1)
        inner_pure = [n for n in pure_comments if n in span and n > node.lineno]
        body_doc = docstring_span(node)
        code_lines = [n for n in span if not is_blank(lines[n - 1]) and n not in body_doc and n not in pure_comments]

        if not doc:
            result["issues"].append(
                {"level": "P1", "line": node.lineno, "msg": f"函数 {node.name}() 没有 docstring"}
            )
        if len(code_lines) >= 15 and not inner_pure:
            result["issues"].append(
                {
                    "level": "P1",
                    "line": node.lineno,
                    "msg": f"函数 {node.name}() 正文 {len(code_lines)} 行，但体内没有任何注释",
                }
            )

        if doc:
            declared = {a.arg for a in node.args.args + node.args.kwonlyargs if a.arg not in {"self", "cls"}}
            documented = set(re.findall(r"^\s{0,8}([a-zA-Z_]\w*)\s*[:：]", doc, re.MULTILINE))
            documented &= declared | {"return", "returns", "返回", "yields"}
            unknown = documented - declared - {"return", "returns", "返回", "yields"}
            if unknown:
                result["issues"].append(
                    {
                        "level": "P1",
                        "line": node.lineno,
                        "msg": f"函数 {node.name}() 的 docstring 写了参数 {sorted(unknown)}，但签名里没有",
                    }
                )

        # 嵌套深度：超过 4 层说明该拆函数了
        depth = 0
        for n in span:
            line = lines[n - 1]
            if is_blank(line):
                continue
            indent = len(line) - len(line.lstrip(" "))
            depth = max(depth, indent // 4)
        if depth >= 5:
            result["issues"].append(
                {"level": "P2", "line": node.lineno, "msg": f"函数 {node.name}() 缩进最深 {depth} 层，小白很难跟"}
            )

    # 3) 可疑注释：被注释掉的代码、TODO 没署名、太短的噪音注释
    for lineno, text in sorted(pure_comments.items()):
        body = text.lstrip("#").strip()
        if COMMENTED_CODE_RE.match(text.strip()):
            result["issues"].append({"level": "P2", "line": lineno, "msg": f"疑似被注释掉的代码：{text.strip()[:60]}"})
        elif re.match(r"^(TODO|FIXME|XXX)\b", body) and not re.search(r"[（(][^）)]*[）)]", body):
            result["issues"].append({"level": "P2", "line": lineno, "msg": f"TODO/FIXME 没有写清负责人或原因：{body[:40]}"})
        elif len(body) <= 3 and not re.match(r"^\W*$", body):
            result["issues"].append({"level": "P2", "line": lineno, "msg": f"注释太短，等于没说：「{body}」"})

    # 4) 魔法数字：比较/算术里的裸数字，且该行没有注释解释
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) or isinstance(node, ast.BinOp):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                    if sub.value in MAGIC_WHITELIST:
                        continue
                    line_no = getattr(sub, "lineno", 0)
                    if line_no in pure_comments:
                        continue
                    snippet = lines[line_no - 1].strip()[:60] if line_no <= len(lines) else ""
                    result["issues"].append(
                        {"level": "P2", "line": line_no, "msg": f"魔法数字 {sub.value} 没有解释：{snippet}"}
                    )
                    break

    result["stats"]["functions"] = sum(
        1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return result


def vue_script_range(lines: list[str]) -> tuple[int, int] | None:
    """返回 .vue 文件中 <script> 段的起止行号（1-based，含端点）。

    Vue 单文件组件里 <template> 是 HTML 结构，不是逻辑代码；如果把它算进
    注释密度的分母，模板越长密度越不可能达标。技能文档也明确“模板不计入
    密度”，所以这里只取 <script> 段参与统计。
    """
    start = None
    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if start is None and stripped.startswith("<script"):
            start = i
        elif start is not None and stripped.startswith("</script>"):
            return start, i
    return None


def analyze_js(path: Path, min_ratio: float) -> dict:
    """JS/TS/Vue 用行扫描近似判定，只保证密度与函数前是否有注释。

    .vue 文件只统计 <script> 段；<template>/<style> 不计入有效行。
    """
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    result = {"file": str(path), "kind": "js", "issues": [], "stats": {}}

    # .vue 先算出脚本段范围，后面的扫描都只在段内进行。
    span = vue_script_range(lines) if path.suffix == ".vue" else None
    if path.suffix == ".vue":
        if span is None:
            # 没有 <script> 的纯模板组件没有可统计的逻辑代码。
            result["stats"].update({"comment_lines": 0, "effective_lines": 0, "density": 1.0})
            return result
        lo, hi = span
        scan_lines = [(i, lines[i - 1]) for i in range(lo, hi + 1)]
    else:
        scan_lines = list(enumerate(lines, start=1))

    comment_lines: set[int] = set()
    in_block = False
    for i, line in scan_lines:
        stripped = line.strip()
        if in_block:
            comment_lines.add(i)
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("/*"):
            comment_lines.add(i)
            if "*/" not in stripped:
                in_block = True
        elif stripped.startswith("//") or stripped.startswith("*"):
            comment_lines.add(i)

    effective_lines = [line for _, line in scan_lines if not is_blank(line)]
    ratio = len(comment_lines) / len(effective_lines) if effective_lines else 0.0
    result["stats"]["comment_lines"] = len(comment_lines)
    result["stats"]["effective_lines"] = len(effective_lines)
    result["stats"]["density"] = round(ratio, 3)
    if ratio < min_ratio:
        result["issues"].append(
            {
                "level": "P0",
                "line": 0,
                "msg": f"注释密度 {ratio:.0%}，低于要求的 {min_ratio:.0%}",
            }
        )

    fn_re = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)|^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(")
    for i, line in scan_lines:
        m = fn_re.match(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        prev = lines[i - 2].strip() if i >= 2 else ""
        if not (prev.startswith("//") or prev.endswith("*/") or prev.startswith("*")):
            result["issues"].append({"level": "P1", "line": i, "msg": f"函数 {name}() 前面没有注释说明用途"})

    return result


def iter_files(targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in targets:
        p = Path(raw)
        if p.is_file():
            out.append(p)
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file() or f.suffix not in PY_EXT | JS_EXT:
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            out.append(f)
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    min_ratio = 0.3
    for a in argv:
        if a.startswith("--min-ratio="):
            min_ratio = float(a.split("=", 1)[1])

    if not args:
        print(__doc__)
        return 2

    files = iter_files(args)
    if not files:
        print("没有找到可检查的 .py / .js / .ts / .vue 文件")
        return 2

    reports = []
    for f in files:
        try:
            if f.suffix in PY_EXT:
                reports.append(analyze_python(f, min_ratio))
            elif f.suffix in JS_EXT:
                reports.append(analyze_js(f, min_ratio))
        except Exception as exc:  # 单个文件读不了不该拖垮整轮体检
            reports.append({"file": str(f), "kind": "error", "stats": {}, "issues": [{"level": "P2", "line": 0, "msg": f"解析失败：{exc}"}]})

    if as_json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        total = {"P0": 0, "P1": 0, "P2": 0}
        for r in reports:
            issues = r["issues"]
            density = r["stats"].get("density")
            density_txt = f"{density:.0%}" if isinstance(density, float) else "  - "
            counts = {lv: sum(1 for i in issues if i["level"] == lv) for lv in ("P0", "P1", "P2")}
            for lv in counts:
                total[lv] += counts[lv]
            print(f"\n{r['file']}  密度 {density_txt}  P0={counts['P0']} P1={counts['P1']} P2={counts['P2']}")
            for issue in sorted(issues, key=lambda x: (x["level"], x["line"])):
                print(f"  [{issue['level']}] L{issue['line']}: {issue['msg']}")
        print(f"\n合计：P0={total['P0']} P1={total['P1']} P2={total['P2']}，共 {len(reports)} 个文件")

    return 1 if total_invalid(reports) else 0


def total_invalid(reports: list[dict]) -> bool:
    return any(i["level"] in {"P0", "P1"} for r in reports for i in r["issues"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
