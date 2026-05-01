#!/usr/bin/env python3
"""
post_watchdog.py — パイプライン自律監査・自動修復エージェント

チェック→自動修復→Discord通知 の3段構え。
人間が気づく前に自分で直す。

チェック項目:
  1. X投稿: 直近N時間で投稿ゼロ → アラート
  2. X投稿: x_post.log にエラー行 → アラート
  3. パイプライン: 直近N時間で記事投稿ゼロ → アラート
  4. x_failsafe: 発動中 → 自動修復（誤発動なら解除）
  5. パイプライン: pipeline.jsonl にエラー → アラート
  6. kpi: x_post_status 連続失敗 → アラート
  7. ログ鮮度: 各パイプラインのログが当日未更新 → 自動再実行
  8. title_performance: 重複レコード → 自動除去

自動修復アクション:
  - failsafe_auto_clear: フェイルセーフ誤発動の自動解除
  - pipeline_restart: 停止パイプラインの自動再実行
  - dedup_title_performance: title_performance.jsonl 重複除去

Usage:
  python3 lib/post_watchdog.py              # 全チェック+自動修復
  python3 lib/post_watchdog.py --dry-run    # Discord送信・修復なし、表示のみ
  python3 lib/post_watchdog.py --check x_post  # 個別チェックのみ
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── 設定 ────────────────────────────────────────────────────────────────────

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config" / "discord_webhooks.json"

JST = timezone(timedelta(hours=9))

X_POST_SILENCE_HOURS = 26   # 旧4h → パイプライン停止多発で誤検知。1日1投稿保証ベースに緩和
ARTICLE_SILENCE_HOURS = 26  # 旧6h → 同上
ACTIVE_HOUR_START = 7
ACTIVE_HOUR_END = 22  # fix: 21:00 cron実行時に h<21 がFalseになり全silence検査がスキップされていたバグを修正

# パイプライン定義: (ログパス, 実行時刻JST, スクリプト, 引数, ラベル)
PIPELINES = [
    (BASE / "logs" / "morning_meeting.log",  9,  None,     [],         "CEOモーニングブリーフ"),
    (Path("/home/aiuser/ai_kpop.log"),        7,  BASE / "kpop_pipeline.sh",         [],         "速報パイプライン"),
    (BASE / "logs" / "beauty_pipeline.log",  11,  BASE / "kpop_pipeline.sh",
        ["韓国コスメ・K-POPアイドルの美容法・スキンケアルーティン・ガラス肌"],                      "美容パイプライン"),
    (BASE / "logs" / "strategy_pipeline.log",12,  BASE / "kpop_strategy_pipeline.sh",[],         "戦略パイプライン"),
    (BASE / "logs" / "lifestyle_pipeline.log",15, BASE / "kpop_pipeline.sh",
        ["韓国旅行・ソウルのカフェ・ポップアップストア・K-POPイベント・聖地巡礼"],                  "ライフスタイルパイプライン"),
    (BASE / "logs" / "fashion_pipeline.log", 18,  BASE / "kpop_pipeline.sh",
        ["K-POPアイドルのファッション・着用アイテム・韓国トレンド・ポップアップイベント情報"],      "ファッションパイプライン"),
    (BASE / "logs" / "ai_meeting.log",       21,  BASE / "ai_company" / "run_ai_meeting.sh", [], "AI日次運営会議"),
]

# ─── ユーティリティ ───────────────────────────────────────────────────────────

def now_jst() -> datetime:
    return datetime.now(JST)


def is_active_hours() -> bool:
    h = now_jst().hour
    return ACTIVE_HOUR_START <= h < ACTIVE_HOUR_END


def get_discord_webhook(channel: str) -> str:
    if not CONFIG.exists():
        return ""
    try:
        d = json.loads(CONFIG.read_text())
        return d.get(channel, "")
    except Exception:
        return ""


def _clean_discord_body(body: str) -> str:
    """Discord embed description の整形:
    - 連続空行を1行に圧縮
    - 行末の余分な空白を除去
    - 2000文字を超えた場合は末尾を省略し [省略] を付加
    """
    import re as _re
    lines = [l.rstrip() for l in body.splitlines()]
    # 3行以上の連続空行を1行に
    cleaned = _re.sub(r'\n{3,}', '\n\n', "\n".join(lines))
    if len(cleaned) > 1900:
        cleaned = cleaned[:1900] + "\n…[省略]"
    return cleaned


def _post_discord(url: str, payload: bytes) -> bool:
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return res.status in (200, 204)


def send_discord_alert(title: str, body: str, level: str = "error") -> bool:
    url = get_discord_webhook("urgent_errors")
    if not url:
        print(f"  [watchdog] Discord webhook未設定 → 標準出力のみ")
        return False

    color = 0xFF0000 if level == "error" else (0xFF9900 if level == "warn" else 0x00CC00)
    icon = "🚨" if level == "error" else ("⚠️" if level == "warn" else "✅")
    ts = now_jst().strftime("%Y-%m-%d %H:%M JST")

    payload = json.dumps({
        "username": "watchdog",
        "embeds": [{
            "title": f"{icon} {title}",
            "description": _clean_discord_body(body),
            "color": color,
            "footer": {"text": f"post_watchdog | {ts}"},
        }]
    }).encode()

    try:
        return _post_discord(url, payload)
    except Exception as e:
        print(f"  [watchdog] Discord送信失敗(urgent_errors): {e}")
        # フォールバック: alert_summary チャネルに送信
        fallback_url = get_discord_webhook("alert_summary")
        if fallback_url and fallback_url != url:
            try:
                _post_discord(fallback_url, payload)
                print(f"  [watchdog] フォールバック(alert_summary)で送信成功")
                return True
            except Exception as e2:
                print(f"  [watchdog] フォールバックも失敗: {e2}")
        return False


def log_alert(check_name: str, message: str, dry_run: bool, level: str = "error") -> dict:
    alert = {
        "ts": now_jst().isoformat(),
        "check": check_name,
        "message": message,
        "dry_run": dry_run,
        "level": level,
    }
    alert_log = LOGS / "watchdog_alerts.jsonl"
    alert_log.parent.mkdir(parents=True, exist_ok=True)
    with open(alert_log, "a") as f:
        f.write(json.dumps(alert, ensure_ascii=False) + "\n")

    icon = "🚨" if level == "error" else "⚠️"
    print(f"  {icon} [{check_name}] {message[:120]}")

    # Discord送信は main() のバッチ送信に委譲（個別送信しない）
    return alert


# ─── 通知クールダウン ──────────────────────────────────────────────────────────
# check_name → 最終Discord送信時刻（JST） を保存するファイル
_NOTIF_COOLDOWN_FILE = LOGS / "watchdog_notif_cooldown.json"

# check_nameごとのクールダウン秒数（デフォルト: 6h — 9時/21時の1日2回まとめ送信に合わせた間隔）
_DEFAULT_COOLDOWN = 6 * 3600  # 6h
_NOTIF_COOLDOWN_SECONDS: dict[str, int] = {
    "recurring_error_patterns":    24 * 3600,  # 24h: 既知パターンは1日1回で十分
    "recurring_error_accumulation": 24 * 3600,
    "pipeline_external_wp_post":   24 * 3600,  # 24h: テスト記事は既知情報
    "gate_fatigue":                 6 * 3600,  # 6h: 閾値緩和判断用
}


def _load_cooldown_state() -> dict:
    try:
        return json.loads(_NOTIF_COOLDOWN_FILE.read_text()) if _NOTIF_COOLDOWN_FILE.exists() else {}
    except Exception:
        return {}


def _save_cooldown_state(state: dict) -> None:
    try:
        _NOTIF_COOLDOWN_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception:
        pass


def is_discord_throttled(check_name: str) -> bool:
    """指定チェックのDiscord通知がクールダウン中かどうかを返す（送信しない場合True）"""
    seconds = _NOTIF_COOLDOWN_SECONDS.get(check_name, _DEFAULT_COOLDOWN)
    state = _load_cooldown_state()
    last_str = state.get(check_name)
    if not last_str:
        return False
    try:
        last_dt = datetime.fromisoformat(last_str)
        elapsed = (now_jst() - last_dt).total_seconds()
        if elapsed < seconds:
            remaining_h = (seconds - elapsed) / 3600
            print(f"  ℹ️ [{check_name}] 通知クールダウン中（残り{remaining_h:.1f}h）→ Discord送信スキップ")
            return True
    except Exception:
        pass
    return False


def mark_discord_sent(check_name: str) -> None:
    """Discord送信後にクールダウン状態を更新する"""
    state = _load_cooldown_state()
    state[check_name] = now_jst().isoformat()
    _save_cooldown_state(state)


def log_repair(action: str, message: str, dry_run: bool) -> None:
    """自動修復アクションをログに記録し Discord に通知する"""
    entry = {
        "ts": now_jst().isoformat(),
        "action": action,
        "message": message,
        "dry_run": dry_run,
    }
    repair_log = LOGS / "watchdog_repairs.jsonl"
    repair_log.parent.mkdir(parents=True, exist_ok=True)
    with open(repair_log, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"  🔧 [AUTO-REPAIR:{action}] {message[:120]}")

    if not dry_run:
        send_discord_alert(
            title=f"[自動修復] {action}",
            body=message,
            level="info",
        )


# ─── チェック関数 ─────────────────────────────────────────────────────────────

def check_x_post_silence(dry_run: bool) -> list[dict]:
    """X投稿: 稼働時間帯に N 時間投稿ゼロならアラート"""
    alerts = []
    if not is_active_hours():
        return alerts

    x_log = LOGS / "x_post.log"
    if not x_log.exists():
        alerts.append(log_alert("x_post_silence",
            "x_post.log が存在しません。X投稿が一度も実行されていない可能性があります。", dry_run))
        return alerts

    last_success_ts = None
    pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] RESULT: (?:投稿成功|フック投稿成功)')
    for line in x_log.read_text(errors="replace").splitlines():
        m = pattern.search(line)
        if m:
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
                if last_success_ts is None or ts > last_success_ts:
                    last_success_ts = ts
            except ValueError:
                pass

    threshold = now_jst() - timedelta(hours=X_POST_SILENCE_HOURS)
    if last_success_ts is None:
        alerts.append(log_alert("x_post_silence",
            "X投稿成功ログがありません。post_to_x.sh が正常に実行されていない可能性があります。", dry_run))
    elif last_success_ts < threshold:
        elapsed = now_jst() - last_success_ts
        h, m2 = divmod(int(elapsed.total_seconds() / 60), 60)
        alerts.append(log_alert("x_post_silence",
            f"X投稿が{h}時間{m2}分間ありません（最終成功: {last_success_ts.strftime('%m/%d %H:%M')}）。\n"
            f"確認先: logs/x_post.log", dry_run))
    return alerts


def check_x_post_errors(dry_run: bool) -> list[dict]:
    """X投稿: x_post.log の直近エラーを検知"""
    alerts = []
    x_log = LOGS / "x_post.log"
    if not x_log.exists():
        return alerts

    cutoff = now_jst() - timedelta(hours=X_POST_SILENCE_HOURS)
    error_lines = []
    pattern_ts = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]')
    # フェイルセーフ発動・スキップは別チェックで監視するため除外
    pattern_err = re.compile(r'失敗|ERROR|❌|HTTP [45]\d\d|プレフライト不合格')
    pattern_skip = re.compile(r'フェイルセーフ|スキップ|DRY-RUN')

    for line in x_log.read_text(errors="replace").splitlines():
        m = pattern_ts.search(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        except ValueError:
            continue
        if ts >= cutoff and pattern_err.search(line) and not pattern_skip.search(line):
            error_lines.append(line.strip())

    unique_errors = list(dict.fromkeys(error_lines))[:5]
    if unique_errors:
        alerts.append(log_alert("x_post_error",
            f"X投稿ログに直近{X_POST_SILENCE_HOURS}h以内のエラー{len(unique_errors)}件:\n" +
            "\n".join(f"  • {e[:120]}" for e in unique_errors), dry_run))
    return alerts


def check_article_silence(dry_run: bool) -> list[dict]:
    """記事投稿: N 時間以内に kpi_posts.jsonl への書き込みがなければアラート"""
    alerts = []
    if not is_active_hours():
        return alerts

    kpi = LOGS / "kpi_posts.jsonl"
    if not kpi.exists():
        alerts.append(log_alert("article_silence",
            "kpi_posts.jsonl が存在しません。記事投稿パイプラインが未実行の可能性があります。", dry_run))
        return alerts

    last_post_ts = None
    for line in kpi.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("timestamp", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
                if last_post_ts is None or ts > last_post_ts:
                    last_post_ts = ts
        except Exception:
            continue

    threshold = now_jst() - timedelta(hours=ARTICLE_SILENCE_HOURS)
    if last_post_ts is None:
        alerts.append(log_alert("article_silence",
            "記事投稿ログ(kpi_posts.jsonl)に有効なレコードがありません。", dry_run))
    elif last_post_ts < threshold:
        elapsed = now_jst() - last_post_ts
        h, m2 = divmod(int(elapsed.total_seconds() / 60), 60)
        alerts.append(log_alert("article_silence",
            f"記事投稿が{h}時間{m2}分間ありません（最終投稿: {last_post_ts.strftime('%m/%d %H:%M')}）。\n"
            f"確認先: logs/pipeline.jsonl, /home/aiuser/ai_kpop.log", dry_run))
    return alerts


def check_failsafe(dry_run: bool) -> list[dict]:
    """フェイルセーフ発動中かチェック。誤発動なら自動解除する。"""
    alerts = []
    fs_log = LOGS / "x_failsafe.jsonl"
    if not fs_log.exists():
        return alerts

    cutoff = now_jst() - timedelta(hours=24)
    recent = []
    for line in fs_log.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("ts", "")
            # タイムスタンプ形式の正規化
            try:
                ts = datetime.fromisoformat(ts_str).astimezone(JST)
            except Exception:
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
                except Exception:
                    continue
            if ts >= cutoff:
                recent.append(r)
        except Exception:
            continue

    if not recent:
        return alerts

    # ── 自動修復: 誤発動かどうかを判定 ──
    # kpi_posts.jsonl で X 投稿成功実績が 3 件未満 → データ不足による誤発動
    kpi = LOGS / "kpi_posts.jsonl"
    x_post_success_count = 0
    if kpi.exists():
        for line in kpi.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if str(r.get("x_post_status", "")) in ("成功", "投稿成功"):
                    x_post_success_count += 1
            except Exception:
                continue

    # title_performance.jsonl で win/lose の実績をチェック
    perf = LOGS / "title_performance.jsonl"
    x_posted_ids = set()
    win_lose_records = []
    if kpi.exists():
        for line in kpi.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if str(r.get("x_post_status", "")) in ("成功", "投稿成功"):
                    pid = str(r.get("post_id", ""))
                    if pid:
                        x_posted_ids.add(pid)
            except Exception:
                continue

    if perf.exists():
        for line in perf.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                pid = str(r.get("post_id", ""))
                if r.get("result") in ("win", "lose") and pid in x_posted_ids:
                    win_lose_records.append(r)
            except Exception:
                continue

    is_false_positive = x_post_success_count < 3 or len(win_lose_records) < 3

    if is_false_positive:
        # 自動修復: フェイルセーフログをクリア
        if not dry_run:
            fs_log.write_text("")
            log_repair(
                "failsafe_auto_clear",
                f"フェイルセーフ誤発動を検知し自動解除しました。\n"
                f"理由: X投稿成功実績={x_post_success_count}件（判定に必要な3件未満）\n"
                f"x_failsafe.jsonl をクリアしました。",
                dry_run,
            )
        else:
            print(f"  🔧 [DRY-RUN] フェイルセーフ誤発動を検知 → 本番なら自動解除します "
                  f"(X投稿成功={x_post_success_count}件)")
    else:
        # 本物のフェイルセーフ → アラートのみ
        alerts.append(log_alert(
            "failsafe_active",
            f"§10 フェイルセーフが直近24h以内に{len(recent)}回発動しています。\n"
            f"X投稿実績のある記事のCTR低下3連続が確認されました。\n"
            f"確認先: logs/x_failsafe.jsonl, logs/title_performance.jsonl",
            dry_run,
        ))
    return alerts


def check_pipeline_errors(dry_run: bool) -> list[dict]:
    """pipeline.jsonl の直近エラーステップをチェック"""
    alerts = []
    pl = LOGS / "pipeline.jsonl"
    if not pl.exists():
        return alerts

    cutoff = now_jst() - timedelta(hours=ARTICLE_SILENCE_HOURS)
    errors = []
    for line in pl.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("timestamp", "")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
            if ts >= cutoff and r.get("status") == "error":
                errors.append(r)
        except Exception:
            continue

    if errors:
        details = "\n".join(
            f"  • [{r.get('step','')}] {r.get('message','')[:80]}" for r in errors[:5]
        )
        alerts.append(log_alert("pipeline_error",
            f"パイプラインで直近{ARTICLE_SILENCE_HOURS}h以内に{len(errors)}件のエラー:\n{details}\n"
            f"確認先: logs/pipeline.jsonl", dry_run))
    return alerts


def check_x_post_status_in_kpi(dry_run: bool) -> list[dict]:
    """kpi_posts.jsonl の x_post_status が連続失敗していないかチェック"""
    alerts = []
    kpi = LOGS / "kpi_posts.jsonl"
    if not kpi.exists():
        return alerts

    records = []
    for line in kpi.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if "x_post_status" in r:
                records.append(r)
        except Exception:
            continue

    if len(records) < 3:
        return alerts

    recent = records[-3:]
    fail_statuses = ["失敗", "スキップ", "DRY-RUN", ""]
    consecutive_fails = all(
        any(f in str(r.get("x_post_status", "")) for f in fail_statuses)
        for r in recent
    )
    if consecutive_fails:
        details = "\n".join(
            f"  • post_id={r.get('post_id','')} status={r.get('x_post_status','N/A')}"
            for r in recent
        )
        alerts.append(log_alert("x_post_consecutive_fail",
            f"直近3記事でX投稿が連続して失敗/スキップしています:\n{details}\n"
            f"確認先: logs/kpi_posts.jsonl, logs/x_post.log", dry_run))
    return alerts


def _pipeline_already_ran_today(log_path: Path) -> bool:
    """ログが今日 JST で更新されているか"""
    if not log_path.exists():
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
    return mtime.strftime("%Y-%m-%d") == now_jst().strftime("%Y-%m-%d")


def _pipeline_is_running(script: Path) -> bool:
    """同じスクリプトのプロセスが既に動いているか"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(script)],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def check_pipeline_log_staleness(dry_run: bool) -> list[dict]:
    """各パイプラインのログが当日未更新なら自動再実行を試みる"""
    alerts = []
    if not is_active_hours():
        return alerts

    jst_now = now_jst()
    # パイプラインを再実行したか記録（同一watchdog実行内で重複防止）
    restarted = set()

    for log_path, scheduled_hour, script, args, label in PIPELINES:
        # まだ実行時刻を2時間以上過ぎていない → スキップ
        if jst_now.hour < scheduled_hour + 2:
            continue

        if _pipeline_already_ran_today(log_path):
            continue  # 正常

        mtime_str = "（ファイルなし）"
        if log_path.exists():
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
            elapsed_h = int((jst_now - mtime).total_seconds() / 3600)
            mtime_str = f"最終更新: {mtime.strftime('%m/%d %H:%M JST')} ({elapsed_h}h前)"

        # ── 自動修復: パイプライン再実行 ──
        if not dry_run and script and script.exists() and label not in restarted:
            # 既に同スクリプトが動いていれば再実行しない
            if _pipeline_is_running(script):
                print(f"  ⏳ [{label}] 既に実行中のため再実行スキップ")
                continue

            restarted.add(label)
            log_repair(
                "pipeline_restart",
                f"{label} のログが当日未更新のため自動再実行します。\n{mtime_str}\n"
                f"スクリプト: {script.name} {' '.join(args)}",
                dry_run,
            )
            # バックグラウンドで再実行（ログに追記）
            env = os.environ.copy()
            venv_activate = BASE / ".venv" / "bin" / "activate"
            cmd = (
                f"source {venv_activate} && "
                f"cd {BASE} && "
                f"timeout 5400 bash {script} {' '.join(repr(a) for a in args)}"
                f" >> {log_path} 2>&1"
            )
            subprocess.Popen(
                ["bash", "-c", cmd],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            if dry_run:
                print(f"  🔧 [DRY-RUN] {label}: 当日未更新 → 本番なら自動再実行します ({mtime_str})")
            alerts.append(log_alert(
                "pipeline_log_stale",
                f"{label}: ログが当日未更新です。自動再実行を試みましたが確認してください。\n{mtime_str}",
                dry_run,
                level="warn",
            ))

    return alerts


def check_thumbnail_genre_mismatch(dry_run: bool) -> list[dict]:
    """thumbnail_performance.jsonl の直近レコードでジャンル誤分類を検知する。
    breaking が旅行・美容・ファッション記事に使われていたら警告。"""
    alerts = []
    thumb_log = LOGS / "thumbnail_performance.jsonl"
    if not thumb_log.exists():
        return alerts

    cutoff = now_jst() - timedelta(hours=24)
    mismatches = []

    # タイトルに旅行・美容・ファッション系ワードがあるのに breaking ジャンルのサムネ
    MISMATCH_RULES = [
        (["旅行", "ソウル", "カフェ", "聖地巡礼", "ポップアップ", "観光"], ["breaking"], "travel"),
        (["コスメ", "スキンケア", "美容", "ガラス肌", "ヘアケア"], ["breaking", "live"], "beauty"),
        (["ファッション", "コーデ", "着用", "ブランド"], ["breaking", "live"], "fashion"),
    ]

    for line in thumb_log.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("timestamp", r.get("ts", ""))
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
            if ts < cutoff:
                continue
            title = r.get("title", "").lower()
            genre = r.get("genre", "")
            for keywords, bad_genres, expected in MISMATCH_RULES:
                if any(k in title for k in keywords) and genre in bad_genres:
                    mismatches.append({
                        "post_id": r.get("post_id", "?"),
                        "title": r.get("title", "")[:50],
                        "genre": genre,
                        "expected": expected,
                    })
        except Exception:
            continue

    if mismatches:
        details = "\n".join(
            f"  • post_id={m['post_id']} genre={m['genre']}→{m['expected']} title={m['title']}"
            for m in mismatches[:5]
        )
        # AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY
        # サムネ不一致の自動修復は行わない。理由:
        #   - 正しいジャンルのサムネ再生成にはmake_thumbnail.pyとWP APIが必要
        #   - 間違えてサムネを消すリスクがある（記事公開中）
        #   - 誤検知の可能性あり（タイトルキーワードのみで判定）
        # 対応: WARNログ + NG記録。post_audit.sh [6]サムネチェックが正規のfix経路。
        alerts.append(log_alert(
            "thumbnail_genre_mismatch",
            f"サムネジャンル誤分類が{len(mismatches)}件検知されました:\n{details}\n"
            f"旅行・美容・ファッション記事に breaking ジャンルが使われています。\n"
            f"[AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY] 手動でpost_audit.shを再実行するか"
            f" make_thumbnail.py でサムネを再生成してください。",
            dry_run,
            level="warn",
        ))
        # watchdog_repairs.jsonlにも記録（後追い確認用）
        log_repair(
            "thumbnail_genre_mismatch_detected",
            f"検知のみ（自動修復なし）: {len(mismatches)}件 | post_ids="
            f"{[m['post_id'] for m in mismatches[:5]]}",
            dry_run,
        )
    return alerts


def check_error_patterns(dry_run: bool) -> list[dict]:
    """error_patterns.json を読み込み、再発率の高いエラーをアラートする
    [クールダウン] recurring_error_patterns: 24h に1回のみ Discord 送信
    """
    alerts = []
    ep_file = BASE / "config" / "error_patterns.json"
    if not ep_file.exists():
        return alerts

    try:
        ep = json.loads(ep_file.read_text())
    except Exception:
        return alerts

    patterns = ep.get("patterns", {})
    recurring = ep.get("recurring_errors", [])

    # resolved_errors に記録されたキーを収集（修復済みパターンはアラート対象外）
    resolved_keys = set()
    for r in ep.get("resolved_errors", []):
        k = r.get("key", "")
        if k:
            resolved_keys.add(k)

    # 直近7日以内に2回以上発生したパターン（修復済みを除外）
    cutoff = now_jst() - timedelta(days=7)
    high_freq = []
    for pattern_name, info in patterns.items():
        if pattern_name in resolved_keys:
            continue  # 修復済みパターンはスキップ
        count = info.get("count", 0)
        last_seen_str = info.get("last_seen", "")
        try:
            last_seen = datetime.fromisoformat(last_seen_str).astimezone(JST)
        except Exception:
            continue
        if count >= 2 and last_seen >= cutoff:
            high_freq.append({
                "pattern": pattern_name,
                "count": count,
                "last_seen": last_seen,
                "fix": info.get("fix", ""),
                "agent": info.get("agent", ""),
            })

    if high_freq:
        details = "\n".join(
            f"  • [{h['pattern']}] {h['count']}回発生 最終:{h['last_seen'].strftime('%m/%d %H:%M')} agent={h['agent']}"
            for h in sorted(high_freq, key=lambda x: -x["count"])[:5]
        )
        msg = (
            f"再発エラーパターン {len(high_freq)}件（直近7日）:\n{details}\n"
            f"確認先: config/error_patterns.json, logs/audit_feedback.jsonl"
        )
        alerts.append(log_alert("recurring_error_patterns", msg, dry_run, level="warn"))

    # recurring_errorsに登録済みパターンが3件以上なら昇格推奨（解決済みは除外）
    unresolved = [r for r in recurring if not r.get("resolved_at")]
    if len(unresolved) >= 3:
        rec_names = ", ".join(
            r.get("key", str(r)) if isinstance(r, dict) else str(r)
            for r in unresolved[:5]
        )
        msg = (
            f"繰り返しエラーが{len(unresolved)}件蓄積(未解決): {rec_names}\n"
            f"→ auto_improve.py report で指令昇格状況を確認してください"
        )
        alerts.append(log_alert("recurring_error_accumulation", msg, dry_run, level="warn"))

    return alerts


def check_dedup_title_performance(dry_run: bool) -> list[dict]:
    """title_performance.jsonl の重複レコードを自動除去"""
    alerts = []
    perf = LOGS / "title_performance.jsonl"
    if not perf.exists():
        return alerts

    lines = perf.read_text(errors="replace").splitlines()
    seen: dict[str, bool] = {}
    deduped = []
    removed = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            deduped.append(line)
            continue

        pid = r.get("post_id", "")
        result = r.get("result", "")
        key = f"pid:{pid}" if pid else f"title:{r.get('title','')}:{result}"

        if key in seen:
            removed += 1
        else:
            seen[key] = True
            deduped.append(line)

    if removed > 0:
        if not dry_run:
            perf.write_text("\n".join(deduped) + "\n")
            log_repair(
                "dedup_title_performance",
                f"title_performance.jsonl から重複レコード{removed}件を除去しました。\n"
                f"（{len(lines)} → {len(deduped)} 行）",
                dry_run,
            )
        else:
            print(f"  🔧 [DRY-RUN] title_performance.jsonl: 重複{removed}件検知 → 本番なら自動除去します")
    return alerts


def check_draft_x_posted(dry_run: bool) -> list[dict]:
    """逆監査: draft/pending 状態の記事なのに X 投稿済みの事故を検知する。

    AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY
    - 自動でX投稿を削除しない（tweet_idによる削除はデータ損失リスク）
    - 検知してログ・Discord通知するのみ
    - 人間がWordPressで publish 昇格 か X投稿削除を判断する
    """
    alerts = []
    kpi_file = LOGS / "kpi_posts.jsonl"
    if not kpi_file.exists():
        return alerts

    cutoff = now_jst() - timedelta(hours=48)
    accidents = []

    for line in kpi_file.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("date", r.get("timestamp", ""))
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=JST)
            else:
                ts = ts.astimezone(JST)
            if ts < cutoff:
                continue

            # X投稿済みかつ記事ステータスが非publish
            x_status = str(r.get("x_post_status", ""))
            wp_status = str(r.get("status", "publish"))  # KPIに無ければpublishとみなす
            x_posted = "成功" in x_status or "投稿成功" in x_status
            is_draft = wp_status in ("draft", "pending", "future")

            if x_posted and is_draft:
                accidents.append({
                    "post_id": r.get("post_id", "?"),
                    "title": r.get("title", "")[:50],
                    "wp_status": wp_status,
                    "x_status": x_status[:30],
                })
        except Exception:
            continue

    if accidents:
        details = "\n".join(
            f"  ⛔ post_id={a['post_id']} status={a['wp_status']} x={a['x_status']} title={a['title']}"
            for a in accidents[:5]
        )
        alerts.append(log_alert(
            "draft_x_posted_accident",
            f"🚨 draft/pending 記事なのに X 投稿済みの事故が{len(accidents)}件検知:\n{details}\n"
            f"対応: WordPress管理画面でステータスを publish に昇格 または X投稿を手動削除してください。\n"
            f"[AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY]",
            dry_run,
            level="error",
        ))
    return alerts


def check_pipeline_external_wp_posts(dry_run: bool) -> list[dict]:
    """pipeline外WP記事検知: 直近48h以内にpost_audit.logで監査されたpost_idが
    pipeline.jsonlのwordpress_postに記録されていない場合にwarn。

    AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY
    - 自動修復なし。検知・Discord通知のみ。
    - 目的: テスト直投稿・手動投稿の可観測性向上（2234型再発防止）

    ロジック:
    - pipeline.jsonl の wordpress_post ステップの message フィールドから
      post_idを正規表現で抽出してIDセットを構築（全量）
    - post_audit.log の「投稿後監査開始: ID=X」から直近48h内の監査済みIDを収集
    - 後者にあって前者にないIDを pipeline外記事とみなす
    """
    alerts = []
    pl = LOGS / "pipeline.jsonl"
    audit_log = LOGS / "post_audit.log"

    if not pl.exists() or not audit_log.exists():
        return alerts

    # pipeline.jsonl: wordpress_postステップのmessageから post_id=\d+ を抽出（全量）
    pipeline_post_ids: set[str] = set()
    _pid_re = re.compile(r"post_id=(\d+)")
    for line in pl.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            if r.get("step") != "wordpress_post":
                continue
            m = _pid_re.search(r.get("message", ""))
            if m:
                pipeline_post_ids.add(m.group(1))
            # フォールバック: post_idフィールドが直接ある場合
            pid_field = str(r.get("post_id", ""))
            if pid_field and pid_field.isdigit():
                pipeline_post_ids.add(pid_field)
        except Exception:
            continue

    # post_audit.log: 直近48h以内の「投稿後監査開始: ID=X」を収集
    cutoff = now_jst() - timedelta(hours=48)
    audited_post_ids: dict[str, str] = {}  # post_id -> 初出timestamp
    _audit_re = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[AUDIT\] .*投稿後監査開始.*ID=(\d+)')
    for line in audit_log.read_text(errors="replace").splitlines():
        m = _audit_re.search(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        pid = m.group(2)
        if pid not in audited_post_ids:
            audited_post_ids[pid] = m.group(1)

    # 差分: 監査済みだがpipelineに記録がないID = pipeline外記事
    external_ids = {pid: ts for pid, ts in audited_post_ids.items()
                    if pid not in pipeline_post_ids}

    if external_ids:
        details = "\n".join(
            f"  ⚠️ post_id={pid} 初回監査={ts}"
            for pid, ts in sorted(external_ids.items(), key=lambda x: x[1])[:5]
        )
        msg = (
            f"pipeline.jsonl未記録の記事が直近48h以内に{len(external_ids)}件検知:\n{details}\n"
            f"原因: テスト直投稿・手動投稿の可能性。WordPress管理画面で確認してください。\n"
            f"確認先: logs/pipeline.jsonl, logs/post_audit.log\n"
            f"[AUTO_FIX_POLICY: HUMAN_REVIEW_ONLY]"
        )
        alerts.append(log_alert("pipeline_external_wp_post", msg, dry_run, level="warn"))
    return alerts


# ─── メイン ───────────────────────────────────────────────────────────────────

def check_gate_fatigue(dry_run: bool) -> list[dict]:
    """品質ゲート連続BLOCK検知: 同じゲートで直近6h以内に3回以上BLOCK/HARD_FAILしている場合に警告。

    目的: 2026-04-16の38h沈黙事故の再発防止。gardevoir・pre_publish_gate・thumb_ctr_block・
    post_to_x HOOK_CTRが個別は妥当でも重ねがけで常時停止するパターンを早期発見する。
    閾値緩和の人間判断を促すための通知であり、自動緩和はしない。
    """
    alerts = []
    pl = LOGS / "pipeline.jsonl"
    if not pl.exists():
        return alerts

    WINDOW_HOURS = 6
    MIN_CONSECUTIVE_BLOCKS = 3
    # ゲート名と「失敗」とみなすステータス
    GATE_BLOCK_STATUSES = {
        "pre_publish_gate":       ("BLOCKED",),
        "thumb_ctr_block":        ("BLOCKED",),
        "gardevoir_hook_critic":  ("HARD_FAIL",),
    }

    cutoff = now_jst() - timedelta(hours=WINDOW_HOURS)
    # ゲート別に直近のBLOCK/HARD_FAIL記録を集める
    gate_events: dict[str, list[dict]] = {g: [] for g in GATE_BLOCK_STATUSES}

    for line in pl.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("timestamp", "")
            if not ts_str:
                continue
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
            if ts < cutoff:
                continue
            step = r.get("step", "")
            status = r.get("status", "")
            if step in GATE_BLOCK_STATUSES and status in GATE_BLOCK_STATUSES[step]:
                gate_events[step].append(r)
        except Exception:
            continue

    fatigued = []
    for gate, events in gate_events.items():
        if len(events) >= MIN_CONSECUTIVE_BLOCKS:
            last_msgs = [e.get("message", "")[:100] for e in events[-3:]]
            fatigued.append((gate, len(events), last_msgs))

    if fatigued:
        lines = []
        for gate, count, msgs in fatigued:
            lines.append(f"🚨 **{gate}**: 直近{WINDOW_HOURS}hで{count}回BLOCK/HARD_FAIL")
            for m in msgs:
                lines.append(f"    • {m}")
        body = (
            f"品質ゲートの連続BLOCK検知（閾値: {MIN_CONSECUTIVE_BLOCKS}回以上）\n"
            + "\n".join(lines)
            + "\n\n対応案: 閾値緩和の妥当性を判断。gardevoir PASS後の過剰BLOCKは2026-04-16事故の再来リスク。"
        )
        alerts.append(log_alert("gate_fatigue", body, dry_run, level="warning"))
    return alerts


def check_bounce_rate_anomaly(dry_run: bool) -> list[dict]:
    """GA4 bounce_rateの急騰検知: 前回比で50%以上上昇した場合に警告。

    ボット流入やGA4トラッキング破損の早期発見が目的。
    kpi_daily.jsonl の直近2件を比較する。
    """
    alerts = []
    kpi_file = LOGS / "kpi_daily.jsonl"
    if not kpi_file.exists():
        return alerts

    lines = kpi_file.read_text(errors="replace").strip().splitlines()
    if len(lines) < 2:
        return alerts

    try:
        prev = json.loads(lines[-2])
        curr = json.loads(lines[-1])
    except (json.JSONDecodeError, IndexError):
        return alerts

    prev_br = prev.get("ga4_bounce_rate", 0)
    curr_br = curr.get("ga4_bounce_rate", 0)
    curr_engaged = curr.get("ga4_engaged_sessions", 0)
    curr_sessions = curr.get("ga4_sessions", 0)
    curr_date = curr.get("date", "?")
    prev_date = prev.get("date", "?")

    # bounce_rate が 50% を超え、かつ前回比で 30ポイント以上上昇
    if curr_br > 0.5 and (curr_br - prev_br) > 0.3:
        engagement_pct = round(curr_engaged / curr_sessions * 100, 1) if curr_sessions > 0 else 0
        body = (
            f"bounce_rate急騰: {prev_date}={round(prev_br*100,1)}% → {curr_date}={round(curr_br*100,1)}%\n"
            f"engaged_sessions: {curr_engaged}/{curr_sessions} ({engagement_pct}%)\n"
            f"原因候補: ボット/スパム流入、GA4トラッキング破損、リファラスパム\n"
            f"対応: GA4コンソールでトラフィックソース別engagement確認"
        )
        alerts.append(log_alert("bounce_rate", body, dry_run, level="warning"))
    return alerts


CHECKS = {
    "x_post":        check_x_post_silence,
    "x_errors":      check_x_post_errors,
    "article":       check_article_silence,
    "failsafe":      check_failsafe,
    "pipeline":      check_pipeline_errors,
    "x_kpi":         check_x_post_status_in_kpi,
    "log_staleness": check_pipeline_log_staleness,
    "thumb_genre":   check_thumbnail_genre_mismatch,
    "error_patterns": check_error_patterns,
    "dedup":         check_dedup_title_performance,
    "draft_x_guard": check_draft_x_posted,        # 逆監査: draft記事X投稿事故検知
    "external_wp":   check_pipeline_external_wp_posts,  # pipeline外WP記事検知（HUMAN_REVIEW_ONLY）
    "gate_fatigue":  check_gate_fatigue,          # 品質ゲート連続BLOCK検知（2026-04-16事故再発防止）
    "bounce_rate":   check_bounce_rate_anomaly,    # GA4 bounce_rate急騰検知（ボット/トラッキング破損）
}


def _send_batch_discord(alerts: list[dict]) -> bool:
    """全アラートを1通のDiscordメッセージにまとめて送信する。
    クールダウン中のアラートはスキップし、送信したものだけクールダウンを記録する。"""
    if not alerts:
        return False

    # クールダウン判定: 各アラートを送信対象/スキップに分類
    to_send = []
    for alert in alerts:
        check = alert.get("check", "unknown")
        if is_discord_throttled(check):
            continue
        to_send.append(alert)

    if not to_send:
        print("  ℹ️ 全アラートがクールダウン中 → Discord送信スキップ")
        return False

    # まとめ本文を構築
    ts = now_jst().strftime("%Y-%m-%d %H:%M JST")
    lines = [f"**検知時刻**: {ts}", f"**異常件数**: {len(to_send)}件", ""]

    error_count = sum(1 for a in to_send if a.get("level", "error") == "error")
    warn_count = len(to_send) - error_count

    for alert in to_send:
        check = alert.get("check", "unknown")
        level = alert.get("level", "error")
        icon = "🚨" if level == "error" else "⚠️"
        msg = alert.get("message", "")
        # 各アラートは要約のみ（最初の100文字）
        summary = msg.split("\n")[0][:100]
        lines.append(f"{icon} **[{check}]** {summary}")

    body = "\n".join(lines)
    if len(body) > 1900:
        body = body[:1900] + "\n…[省略]"

    title = f"📋 監査レポート: {error_count}件エラー / {warn_count}件警告"
    level = "error" if error_count > 0 else "warn"

    ok = send_discord_alert(title=title, body=body, level=level)

    # 送信成功したアラートのクールダウンを記録
    if ok:
        for alert in to_send:
            mark_discord_sent(alert.get("check", "unknown"))

    return ok


def main():
    parser = argparse.ArgumentParser(description="パイプライン自律監査・自動修復エージェント")
    parser.add_argument("--dry-run", action="store_true", help="Discord送信・修復なし、表示のみ")
    parser.add_argument("--check", choices=list(CHECKS.keys()), metavar="CHECK",
                        help=f"個別チェックのみ実行: {', '.join(CHECKS.keys())}")
    args = parser.parse_args()

    checks_to_run = {args.check: CHECKS[args.check]} if args.check else CHECKS

    print(f"[watchdog] 監査開始 {now_jst().strftime('%Y-%m-%d %H:%M JST')}")
    if args.dry_run:
        print("  [DRY-RUN] Discord送信・自動修復はスキップします")

    all_alerts = []
    for name, fn in checks_to_run.items():
        print(f"  checking: {name} ...", end=" ", flush=True)
        try:
            alerts = fn(args.dry_run)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        if alerts:
            print(f"⚠ {len(alerts)}件の問題")
            all_alerts.extend(alerts)
        else:
            print("✅ 正常")

    print(f"\n[watchdog] 完了 — 検知: {len(all_alerts)}件")

    if all_alerts and not args.dry_run:
        # まとめ送信: 全アラートを1通のDiscordメッセージにバッチ送信
        sent = _send_batch_discord(all_alerts)
        if sent:
            print(f"  Discord #urgent_errors にまとめ通知送信済み")
        # auto_repair.sh をバックグラウンドで起動（自律調査・修復ループ）
        auto_repair = BASE / "ai_company" / "auto_repair.sh"
        if auto_repair.exists():
            try:
                subprocess.Popen(
                    ["bash", str(auto_repair)],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(BASE),
                )
                print(f"  🤖 auto_repair.sh をバックグラウンド起動しました")
            except Exception as e:
                print(f"  [watchdog] auto_repair.sh 起動失敗: {e}")
        else:
            print(f"  [watchdog] auto_repair.sh が見つかりません: {auto_repair}")

    sys.exit(1 if all_alerts else 0)


if __name__ == "__main__":
    main()
