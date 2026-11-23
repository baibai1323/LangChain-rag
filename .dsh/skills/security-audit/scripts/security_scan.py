"""安全扫描器 —— security-audit 技能的第一道机器筛。

覆盖四类问题：
  1. 源码里的硬编码密钥 / 密码 / Token（含注释掉的，因为 Git 历史里还在）
  2. SQL 注入：f-string、字符串拼接、% 格式化拼进 execute/text
  3. 配置文件里的明文敏感信息（.env / yaml / json / ini / properties）
  4. 其他高危写法：eval / pickle / shell=True / 关闭证书校验 / 弱哈希 / 调试开关

设计原则：
  - **输出里绝不回显完整凭证**，只保留首尾各 2 个字符，其余用 *** 代替。
  - 宁可多报让人复核，也不要漏报；每条结果都带「为什么危险」和「怎么改」。
  - 只读，不执行被扫描项目的任何代码。

用法：
    python security_scan.py <文件或目录> [...] [--json] [--min-severity=低]
退出码：0 = 无高危；1 = 有高危；2 = 参数错误。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 扫描时跳过的目录：依赖、构建产物、版本库
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".idea", ".vscode"}

# 参与扫描的文本类扩展名（.env 之类没有后缀的单独处理）
TEXT_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".sh", ".ps1", ".cmd", ".bat",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".env", ".txt", ".md", ".html", ".sql", ".java", ".go", ".php",
}

SEVERITY_ORDER = {"高": 0, "中": 1, "低": 2}

# 这些值一看就是占位符或运行时注入，不算硬编码
PLACEHOLDER_RE = re.compile(
    r"^\s*(\$\{[^}]*\}|%\([^)]*\)s|\{\{[^}]*\}\}|<[^>]*>|x{3,}|changeme|change-me|your[-_].*|placeholder|example|\*{3,}|none|null|true|false|\"\"|'')",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Rule:
    """一条检测规则：匹配到什么、为什么危险、怎么改。"""

    rid: str
    severity: str
    message: str
    suggestion: str
    pattern: re.Pattern[str]
    mask: bool = False  # True 表示命中的是凭证本体，输出时要打码


def rule(rid: str, severity: str, message: str, suggestion: str, pattern: str, mask: bool = False, flags: int = 0) -> Rule:
    return Rule(rid, severity, message, suggestion, re.compile(pattern, flags), mask)


# ---------------------------------------------------------------- 规则表

SECRET_RULES = [
    rule(
        "SEC-001",
        "高",
        "疑似硬编码密码/密钥",
        "改用环境变量或密钥管理服务读取，如 os.environ['DB_PASSWORD']",
        r"(?i)\b\w*(password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|client[_-]?secret)\w*\b\s*[:=]\s*[\"'][^\"']{6,}[\"']",
        mask=True,
    ),
    rule(
        "SEC-002",
        "高",
        "疑似云平台/代码托管平台令牌",
        "立即到对应平台吊销该令牌，改为环境变量注入",
        r"\b(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|xox[baprs]-[A-Za-z0-9\-]{10,})",
        mask=True,
    ),
    rule(
        "SEC-003",
        "高",
        "私钥文件内容被直接写进代码",
        "删除私钥，改为从密钥文件路径读取，并确保该文件在 .gitignore 里",
        r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----",
    ),
    rule(
        "SEC-004",
        "高",
        "数据库/中间件连接串带明文密码",
        "拆成 host/user/password 三项，密码从环境变量读取",
        r"(?i)\b(mysql|postgres(?:ql)?|mongodb(?:\+srv)?|redis|amqp|mssql)://[^:\s/]+:[^@\s]+@",
        mask=True,
    ),
    rule(
        "SEC-005",
        "中",
        "这里像 JWT 或会话令牌本体",
        "确认为真实凭证则吊销并把签发逻辑改为运行时生成",
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
        mask=True,
    ),
]

SQL_RULES = [
    rule(
        "SQL-001",
        "高",
        "SQL 语句用 f-string 拼接变量，存在注入风险",
        "改用参数化查询：session.exec(text('... WHERE id = :id'), params={'id': value})",
        r"(?i)\b(execute|executemany|text|raw|executescript)\s*\(\s*f[\"']",
    ),
    rule(
        "SQL-002",
        "高",
        "SQL 语句用 + 号或 % 拼接，存在注入风险",
        "改用参数化占位符（? 或 :name），不要把变量拼进 SQL 文本",
        r"(?i)(\b(select|insert|update|delete)\b[^\n]*[\"']\s*\+)|(\b(exec|execute|executemany|text|raw)\s*\(\s*[\"'][^\"']*[\"']\s*%)",
    ),
    rule(
        "SQL-003",
        "中",
        "SQL 语句用 .format() 构造",
        "改用参数化查询；.format 无法转义引号，等于给注入开门",
        r"(?i)(select|insert|update|delete)\b[^\"']*[\"']\s*\.format\(",
    ),
    rule(
        "SQL-004",
        "高",
        "JS 模板字符串直接拼进 SQL",
        "改用占位符参数（$1 / ?），值走参数数组",
        r"(?i)\b(query|execute|raw)\s*\(\s*`[^`]*\$\{",
    ),
    rule(
        "SQL-005",
        "中",
        "where/查询条件用字符串拼接",
        "改用 ORM 条件表达式或参数化，别拼字符串",
        r"(?i)\b(where|having|order\s+by)\b[^\"']*[\"']\s*\+",
    ),
]

RISK_RULES = [
    rule("RISK-001", "高", "使用 eval/exec 执行动态字符串", "改用明确的解析逻辑，禁止执行外部输入",
         r"(?<![\w.])(eval|exec)\s*\("),
    rule("RISK-002", "高", "pickle/cPickle 反序列化不可信数据", "改用 JSON；pickle 反序列化等同于执行任意代码",
         r"\b(pickle|cPickle|_pickle)\s*\.\s*loads?\s*\("),
    rule("RISK-003", "高", "yaml.load 未指定 SafeLoader", "改用 yaml.safe_load()",
         r"\byaml\s*\.\s*load\s*\("),
    rule("RISK-004", "高", "subprocess 使用 shell=True", "改为列表参数 + shell=False，避免命令注入",
         r"shell\s*=\s*True"),
    rule("RISK-005", "高", "os.system / os.popen 执行外部输入", "改用 subprocess.run(..., shell=False)",
         r"\bos\s*\.\s*(system|popen)\s*\("),
    rule("RISK-006", "高", "HTTP 请求关闭了证书校验", "删除 verify=False，或显式配置可信 CA",
         r"verify\s*=\s*False"),
    rule("RISK-007", "高", "CORS 允许任意来源", "改为白名单域名；配合 credentials 时禁止用 *",
         r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]|origin\s*:\s*[\"']\*[\"']"),
    rule("RISK-008", "中", "密码类数据使用弱哈希（md5/sha1）", "改用 bcrypt / argon2 / PBKDF2",
         r"(?i)\b(md5|sha1)\s*\("),
    rule("RISK-009", "中", "用 random 生成令牌或验证码", "改用 secrets.token_urlsafe()",
         r"\brandom\s*\.\s*(random|randint|choice)\s*\("),
    rule("RISK-010", "中", "调试开关处于打开状态", "生产环境关闭 DEBUG，用环境变量控制",
         r"(?i)\b(debug|DEBUG)\s*[:=]\s*(True|true|1)\b"),
    rule("RISK-011", "中", "前端直接插入 HTML（XSS 风险）", "改用文本插值；必须用 HTML 时先做转义/净化",
         r"v-html\s*=|dangerouslySetInnerHTML|\.innerHTML\s*="),
    rule("RISK-012", "低", "异常被静默吞掉", "至少记录日志，否则线上故障无从排查",
         r"except\s*(Exception)?\s*:\s*pass\b"),
    rule("RISK-013", "低", "文件权限设为所有人可写", "改为 0o600 / 0o644",
         r"chmod\s*\(?\s*0?777"),
    rule("RISK-014", "中", "JWT 关闭签名校验或允许 none 算法", "始终校验签名，算法写死白名单",
         r"verify_signature\s*[:=]\s*False|algorithms?\s*[:=]\s*\[?\s*[\"']none[\"']"),
]

CONFIG_EXT = {".env", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties"}
CONFIG_KEY_RE = re.compile(
    r"(?i)^\s*[\"']?([\w.\-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential)[\w.\-]*)[\"']?\s*[:=]\s*(.+)$"
)


def mask_value(raw: str) -> str:
    """把凭证打码：保留首尾各 2 字符，其余用 *** 覆盖，避免报告本身变成泄密源。"""
    text = raw.strip().strip("\"'")
    if len(text) <= 6:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def iter_files(targets: list[str]) -> list[Path]:
    """展开目录，只保留文本类文件；.env 这类无后缀文件按文件名判断。"""
    out: list[Path] = []
    for raw in targets:
        p = Path(raw)
        if p.is_file():
            out.append(p)
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            name = f.name.lower()
            if f.suffix.lower() in TEXT_EXT or name.startswith(".env") or name in {"dockerfile", "makefile"}:
                out.append(f)
    return out


def scan_line(rule_obj: Rule, line: str) -> str | None:
    """返回要展示的片段（已打码），不匹配返回 None。"""
    m = rule_obj.pattern.search(line)
    if not m:
        return None
    if rule_obj.mask:
        hit = m.group(0)
        return line.strip().replace(hit, mask_value(hit))[:120]
    return line.strip()[:120]


def scan_file(path: Path) -> list[dict]:
    """扫一个文件，返回命中列表；读不了就跳过，不让单个文件拖垮整轮。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    findings: list[dict] = []
    is_config = path.suffix.lower() in CONFIG_EXT or path.name.lower().startswith(".env")

    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        for r in SECRET_RULES + SQL_RULES + RISK_RULES:
            # 配置文件由 CFG-001 统一定性，避免同一条明文被重复报两次
            if is_config and r.rid == "SEC-001":
                continue
            snippet = scan_line(r, line)
            if snippet is None:
                continue
            # 占位符与运行时注入的写法（${VAR}、%()s、os.environ）不算硬编码
            if r.rid.startswith("SEC-") and PLACEHOLDER_RE.search(line.split("=", 1)[-1].split(":", 1)[-1]):
                continue
            if r.rid.startswith("SEC-") and re.search(r"(os\.environ|os\.getenv|process\.env|getenv\()", line):
                continue
            findings.append(
                {
                    "rule": r.rid,
                    "severity": r.severity,
                    "file": str(path),
                    "line": lineno,
                    "message": r.message,
                    "snippet": snippet,
                    "suggestion": r.suggestion,
                }
            )

        # 配置文件的专项判定：KEY=VALUE 里 VALUE 是明文
        if is_config:
            m = CONFIG_KEY_RE.match(line)
            if m and m.group(2).strip() and not PLACEHOLDER_RE.match(m.group(2).strip().strip("\"'")):
                findings.append(
                    {
                        "rule": "CFG-001",
                        "severity": "高",
                        "file": str(path),
                        "line": lineno,
                        "message": f"配置文件里 {m.group(1)} 是明文",
                        "snippet": f"{m.group(1)}={mask_value(m.group(2))}",
                        "suggestion": "该配置文件不要进版本库；改用 .env.example 占位 + 部署时注入",
                    }
                )
    return findings


def dedupe(findings: list[dict]) -> list[dict]:
    """同一行同一规则重复命中时只留一条（比如一行里有多个赋值）。"""
    seen: set[tuple[str, int, str]] = set()
    out: list[dict] = []
    for f in findings:
        key = (f["file"], f["line"], f["rule"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    as_json = "--json" in argv
    min_severity = "低"
    for a in argv:
        if a.startswith("--min-severity="):
            min_severity = a.split("=", 1)[1]

    if not args:
        print(__doc__)
        return 2

    files = iter_files(args)
    if not files:
        print("没有找到可扫描的文本文件")
        return 2

    findings: list[dict] = []
    for f in files:
        findings.extend(scan_file(f))
    findings = dedupe(findings)
    findings = [f for f in findings if SEVERITY_ORDER[f["severity"]] <= SEVERITY_ORDER.get(min_severity, 2)]
    findings.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], x["file"], x["line"]))

    if as_json:
        print(json.dumps({"scanned": len(files), "findings": findings}, ensure_ascii=False, indent=2))
    else:
        counts = {lv: sum(1 for f in findings if f["severity"] == lv) for lv in ("高", "中", "低")}
        for f in findings:
            print(f"\n[{f['severity']}] {f['rule']}  {f['file']}:{f['line']}")
            print(f"    {f['message']}")
            print(f"    命中：{f['snippet']}")
            print(f"    建议：{f['suggestion']}")
        print(f"\n扫描 {len(files)} 个文件：高危 {counts['高']} 条、中危 {counts['中']} 条、低危 {counts['低']} 条")

    return 1 if any(f["severity"] == "高" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
