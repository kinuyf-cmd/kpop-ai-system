"""自律コンテンツパイプライン(2026-11-13)の共通部品。

キュー(content/queue.tsv)・WP REST・claude -p 呼び出し・費用上限・通知をまとめる。
各段(monitor / draft / publish / weekly_report)はここだけに依存する。
"""
from __future__ import annotations

import base64
import csv
import fcntl
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE))

CONTENT = BASE / "content"
QUEUE = CONTENT / "queue.tsv"
DRAFTS = CONTENT / "drafts"
FACTCHECK = CONTENT / "factcheck"
APPROVALS = CONTENT / "approvals"
PIPELINE_LOG = CONTENT / "pipeline_log.jsonl"
COST_LOG = CONTENT / "claude_cost.tsv"
PLACEMENT_LOG = CONTENT / "x_placement_log.tsv"
STOP_FILE = CONTENT / "STOP"          # 置くと全段が何もせず終わる(緊急停止)
SITE_IDENTITY = BASE / "config" / "site_identity.json"

WP_SITE = "https://www.kpopjournal.tokyo"
WP_API = WP_SITE + "/wp-json/wp/v2"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"

# キューの列。status の遷移:
#   NEW → DRAFTING → DRAFTED → (FACTCHECK_FAIL | VALIDATE_FAIL | REJECTED | READY)
#   READY → PUBLISHED(→ X_DONE / X_DEFERRED / X_SKIPPED) / LIVE_FAIL(下書きへ戻した)
#   HUB_UPDATE = 既存ハブへの追記が正しい項目(新規記事にしない。人が追記する)
#   ERROR = 段の途中で例外
QUEUE_COLS = ["id", "detected_at", "kind", "subject", "claim", "event_date",
              "source_urls", "hub_post_id", "status", "post_id", "updated_at", "note"]

CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
DAILY_USD_CAP = float(os.environ.get("CONTENT_PIPELINE_DAILY_USD", "10"))
DAILY_PUBLISH_CAP = int(os.environ.get("CONTENT_PIPELINE_DAILY_PUBLISH", "4"))


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stopped() -> bool:
    return STOP_FILE.exists()


def log_event(stage: str, **kw) -> None:
    PIPELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PIPELINE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now(), "stage": stage, **kw}, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- queue
@contextmanager
def queue_lock():
    """queue.tsv の読み書きを直列化する(cron と手動実行の並走対策)。"""
    CONTENT.mkdir(parents=True, exist_ok=True)
    with open(CONTENT / ".queue.lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def read_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    with QUEUE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [{c: (r.get(c) or "") for c in QUEUE_COLS} for r in rows]


def write_queue(rows: list[dict]) -> None:
    tmp = QUEUE.with_suffix(".tsv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=QUEUE_COLS, delimiter="\t",
                           lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _tsv_safe(r.get(c, "")) for c in QUEUE_COLS})
    os.replace(tmp, QUEUE)  # 非原子書込で0バイト化した前例あり([[adsense-token-zero-byte-nonatomic-write]])


def _tsv_safe(v) -> str:
    return str(v if v is not None else "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def update_item(item_id: str, **fields) -> dict | None:
    with queue_lock():
        rows = read_queue()
        hit = None
        for r in rows:
            if r["id"] == str(item_id):
                r.update({k: str(v) for k, v in fields.items()})
                r["updated_at"] = now()
                hit = r
        write_queue(rows)
    return hit


def get_item(item_id: str) -> dict | None:
    return next((r for r in read_queue() if r["id"] == str(item_id)), None)


# ---------------------------------------------------------------- WP REST
def _auth() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
    except Exception:  # noqa: BLE001
        pass
    user = os.environ.get("WP_USER", "")
    pw = os.environ.get("WP_APP_PASS") or os.environ.get("WP_PASS", "")
    if user and pw:
        return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
    p = Path.home() / ".wp_auth"
    if p.exists():
        import re
        t = p.read_text()
        m = re.search(r"Authorization:\s*(Basic\s+\S+)", t, re.I)
        return m.group(1) if m else "Basic " + t.strip().split()[-1]
    raise RuntimeError("WP 認証情報が無い(.env WP_USER/WP_APP_PASS か ~/.wp_auth)")


def wp(method: str, path: str, data: dict | None = None, timeout: int = 60):
    req = urllib.request.Request(
        WP_API + path,
        data=json.dumps(data, ensure_ascii=False).encode() if data is not None else None,
        headers={"Authorization": _auth(), "Content-Type": "application/json",
                 "User-Agent": "kpj-content-pipeline/1.0"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"WP {method} {path} → HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")


def wp_ro(*args: str) -> str:
    out = subprocess.run(["sudo", "-n", WP_RO, *args], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"kpop-wp-ro {args[:2]} 失敗: {out.stdout[-300:]} {out.stderr[-300:]}")
    return out.stdout


def aioseo_field(post_id: int, col: str) -> str:
    """wp_aioseo_posts の実値(正のソース。[[aioseo-desc-write-traps]])。NULL/未登録は ""。"""
    assert col in ("description", "title", "og_title", "og_description")
    out = wp_ro("db", "query",
                f"SELECT {col} FROM wp_aioseo_posts WHERE post_id={int(post_id)}")
    lines = [l for l in out.splitlines() if l.strip()]
    # 1行目はヘッダ([[wp-ro-db-query-header-literal-newline-trap]])
    v = lines[1].replace("\\n", "\n").strip() if len(lines) > 1 else ""
    return "" if v == "NULL" else v


def aioseo_description(post_id: int) -> str:
    return aioseo_field(post_id, "description")


# ---------------------------------------------------------------- claude -p
def spent_today() -> float:
    if not COST_LOG.exists():
        return 0.0
    today = datetime.now().date().isoformat()
    tot = 0.0
    for line in COST_LOG.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) >= 3 and p[0].startswith(today):
            try:
                tot += float(p[2])
            except ValueError:
                pass
    return tot


def run_claude(role: str, prompt: str, *, allowed_tools: list[str], budget_usd: float,
               model: str = "sonnet", timeout: int = 1200, cwd: Path | None = None) -> str:
    """claude -p を新しい文脈で1回走らせ、最終テキストを返す。

    役割(monitor/writer/factcheck/approver)ごとに別プロセス=別文脈なので、
    ファクトチェックや承認は執筆側の推論を見ずに判定する(独立性の担保)。
    日次の費用上限を超えていれば起動しない。
    """
    if spent_today() + budget_usd > DAILY_USD_CAP:
        raise RuntimeError(f"日次費用上限 ${DAILY_USD_CAP} に達するため {role} を起動しない "
                           f"(本日 ${spent_today():.2f})")
    cmd = [CLAUDE_BIN, "-p", "--output-format", "json", "--model", model,
           "--max-budget-usd", str(budget_usd),
           "--allowedTools", ",".join(allowed_tools),
           "--permission-mode", "dontAsk", "--strict-mcp-config"]
    env = dict(os.environ)
    env.setdefault("HOME", str(Path.home()))
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=timeout, cwd=str(cwd or BASE), env=env)
    cost, result, d = 0.0, "", None
    try:
        d = json.loads(p.stdout)
        cost = float(d.get("total_cost_usd") or 0)
        result = d.get("result") or ""
        is_err = d.get("is_error")
    except ValueError:
        is_err = True
        result = p.stdout
    runs = CONTENT / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{datetime.now():%Y%m%d-%H%M%S}-{role}.txt").write_text(
        f"cost={cost} turns={d.get('num_turns') if isinstance(d, dict) else '?'}\n\n{result}", encoding="utf-8")
    COST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with COST_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now()}\t{role}\t{cost:.4f}\n")
    if p.returncode != 0 or is_err:
        raise RuntimeError(f"claude -p ({role}) 失敗 rc={p.returncode}: "
                           f"{(result or p.stderr)[-400:]}")
    return result


def extract_json(text: str):
    """モデル出力から最後の ```json ブロック(無ければ最外の {...})を取り出してパース。"""
    import re
    blocks = re.findall(r"```json\s*(.*?)```", text, re.S)
    cand = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(cand)


# ---------------------------------------------------------------- 通知
def notify(title: str, body: str, color: int = 0x3498DB, key: str = "") -> None:
    """Discord(alert_summary)へ1行通知。失敗しても段は止めない。"""
    try:
        from lib.discord_notifier import send_discord
        send_discord("alert_summary", title, body, color,
                     event_key=f"content_pipeline__{key or now()}", severity="WARNING")
    except Exception as e:  # noqa: BLE001
        log_event("notify_fail", error=str(e)[:200], title=title)
