"""
自動リライト実行エンジン (auto_rewriter.py)

REWRITE_NOW (P0/P1) / IMPROVE (P2) の記事を自動差し替えする。

安全制御:
  - 1記事につき最大2回まで
  - 24時間以内の連続リライト禁止
  - WIN記事は絶対触らない
  - GSC登録済みはタイトル変更1回まで
  - スラッグ変更禁止

P0/P1 (REWRITE_NOW):
  - タイトル差し替え (Claude生成)
  - meta description 再生成
  - サムネテキスト差し替え
  - X再投稿 (新ツイート)

P2 (IMPROVE):
  - X投稿のみ改善 (リプライ or 新ツイート)
  - タイトルは維持 (thumb_score<60なら変更)

出力:
  logs/rewrite_actions.jsonl
"""
import json
import os
import sys
import re
import subprocess
import urllib.request
import urllib.error
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR   = os.path.dirname(SCRIPT_DIR)
LOGS_DIR   = os.path.join(BASE_DIR, "logs")

QUEUE_FILE   = os.path.join(LOGS_DIR, "regeneration_queue.jsonl")
ACTIONS_FILE = os.path.join(LOGS_DIR, "rewrite_actions.jsonl")
EVAL_FILE    = os.path.join(LOGS_DIR, "post_publish_evaluations.jsonl")
GSC_FILE     = os.path.join(LOGS_DIR, "gsc_tracking.json")
PATTERNS_FILE = os.path.join(LOGS_DIR, "winning_patterns.jsonl")

WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
WP_AUTH_FILE = os.path.expanduser("~/.wp_auth")

MAX_REWRITES_PER_POST = 2
MIN_INTERVAL_HOURS    = 24

# ── ユーティリティ ──────────────────────────────────────────────────────────────

def load_jsonl(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def append_jsonl(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def now_utc():
    return datetime.now(timezone.utc)


def notify_discord(message):
    try:
        sys.path.insert(0, BASE_DIR)
        from lib.resolve_discord_webhook import resolve
        url = resolve("seo_insights")
        if not url:
            return
        body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"},
            method="POST")
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"  [rewriter] discord通知失敗(続行): {e}", file=sys.stderr)


def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── WP認証 ──────────────────────────────────────────────────────────────────────

def get_wp_auth_header():
    """~/.wp_auth から Basic トークン取得"""
    if not os.path.exists(WP_AUTH_FILE):
        return None, "AUTH_FAIL:~/.wp_authが存在しない"
    try:
        content = open(WP_AUTH_FILE).read()
        m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
        if m:
            return m.group(1), None
        # 生トークン形式
        token = content.strip().split()[-1]
        return f"Basic {token}", None
    except Exception as e:
        return None, f"AUTH_FAIL:~/.wp_auth読み込みエラー({e})"


def wp_request(method, path, data=None):
    """WP REST API リクエスト。戻り値: (response_dict, error_str)"""
    auth, err = get_wp_auth_header()
    if err:
        return None, err

    url = f"{WP_BASE}{path}"
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-autorewriter/1.0",
    }
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")[:300]
        return None, f"API_FAIL:HTTP {e.code} {body_text}"
    except Exception as e:
        return None, f"API_FAIL:{e}"


# ── 安全チェック ─────────────────────────────────────────────────────────────────

def load_action_history():
    """post_id -> list[action]"""
    hist = {}
    for r in load_jsonl(ACTIONS_FILE):
        pid = str(r.get("post_id", ""))
        hist.setdefault(pid, []).append(r)
    return hist


def safety_check(post_id, rank, gsc_data, action_hist):
    """
    戻り値: (ok: bool, reason: str)
    """
    pid = str(post_id)
    prev_actions = action_hist.get(pid, [])

    # WIN記事は触らない (evaluation rankで判定)
    # → rank が WIN の場合は呼ばれないが念のため
    if rank == "WIN":
        return False, "WIN記事は変更禁止"

    # 最大2回
    if len(prev_actions) >= MAX_REWRITES_PER_POST:
        return False, f"リライト上限({MAX_REWRITES_PER_POST}回)到達"

    # 24h以内の連続リライト禁止
    if prev_actions:
        last_ts = parse_ts(prev_actions[-1].get("executed_at", ""))
        if last_ts and (now_utc() - last_ts) < timedelta(hours=MIN_INTERVAL_HOURS):
            return False, f"24h以内の連続リライト禁止 (最終: {prev_actions[-1].get('executed_at','')})"

    # GSC登録済み記事のタイトル変更は1回まで
    gsc = gsc_data.get(pid, {})
    if gsc.get("indexed"):
        title_change_count = sum(1 for a in prev_actions if a.get("title_changed"))
        if title_change_count >= 1:
            return False, "GSC登録済み記事のタイトル変更は1回まで (既に変更済み)"

    return True, "ok"


# ── Claude呼び出し ───────────────────────────────────────────────────────────────

def call_claude(prompt, max_tokens=300):
    """Claude CLI経由でテキスト生成。失敗時はNone"""
    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ── コンテンツ生成 ───────────────────────────────────────────────────────────────

def generate_new_title(original_title, category, pattern_hint=""):
    """勝ちパターンに基づく新タイトル生成"""
    hint = pattern_hint or "数字・固有名詞・感情語・対比構造を含む"
    prompt = f"""以下の記事タイトルをCTR最大化のために改善してください。

元タイトル: {original_title}
カテゴリ: {category}
改善指針: {hint}

条件:
- 30文字以内
- 数字・感情語（衝撃/ついに/判明/速報）・対比（急騰/復帰/電撃）のいずれかを含む
- スラッグ(URL)は変更しない前提なので、SEO的に過激すぎる変更は避ける
- 改善後のタイトルのみ出力（説明不要）"""

    result = call_claude(prompt)
    if result:
        # 最初の行のみ取得
        return result.split("\n")[0].strip()[:50]
    return None


def generate_meta_desc(title, category):
    """meta description再生成 (110-130文字)"""
    prompt = f"""以下の記事のmeta descriptionを日本語で生成してください。

タイトル: {title}
カテゴリ: {category}

条件:
- 110〜130文字ちょうど
- 記事内容の要点を含む
- クリックを促す感情語を1つ含む
- 「...」「…」は使わない
- meta descriptionのテキストのみ出力（説明不要）"""

    result = call_claude(prompt)
    if result:
        text = result.split("\n")[0].strip()
        if 110 <= len(text) <= 130:
            return text
        # 長さ調整: 130文字で切る
        if len(text) > 130:
            return text[:128] + "。"
    return None


def generate_thumb_text(title, category):
    """サムネテキスト生成 (2行、各15文字以内)"""
    prompt = f"""K-POPニュースのサムネイル文字テキストを生成してください。

記事タイトル: {title}
カテゴリ: {category}

条件:
- 必ず2行で出力（改行で区切る）
- 各行15文字以内
- 1行目: 感情語か対比語（例: 衝撃発表、急騰、電撃復帰）
- 2行目: 具体的内容（アーティスト名or数字を含む）
- 「...」「…」は使わない
- 2行のテキストのみ出力"""

    result = call_claude(prompt)
    if result:
        lines = [l.strip() for l in result.split("\n") if l.strip()][:2]
        if len(lines) == 2 and all(len(l) <= 15 for l in lines):
            return "\n".join(lines)
    return None


def generate_x_hook(title, url, category):
    """X投稿用フック文生成 (120-150文字、URLなし)"""
    prompt = f"""K-POPニュースのX(Twitter)投稿用フック文を生成してください。

記事タイトル: {title}
カテゴリ: {category}

条件:
- 120〜150文字（URLは別途付加するので含めない）
- 数字・固有名詞（アーティスト名）・感情語・対比構造を含む
- ハッシュタグは2〜3個（#KPOP #韓国音楽 など）
- 末尾に改行して「#KPOP」系タグを付ける
- フック文のみ出力"""

    result = call_claude(prompt)
    if result:
        return result.strip()
    # フォールバック
    return f"【速報】{title[:40]}\n\n詳細はこちら👇\n\n#KPOP #韓国音楽"


# ── WP更新 ──────────────────────────────────────────────────────────────────────

def update_wp_post(post_id, updates):
    """
    updates: dict with optional keys: title, excerpt
    スラッグは変更しない。
    戻り値: (success: bool, error: str)
    """
    data = {}
    if "title" in updates:
        data["title"] = updates["title"]
    if "excerpt" in updates:
        data["excerpt"] = updates["excerpt"]

    if not data:
        return True, "変更なし"

    resp, err = wp_request("POST", f"/posts/{post_id}", data)
    if err:
        return False, err
    if resp and resp.get("id"):
        return True, "ok"
    return False, f"WP応答異常: {str(resp)[:200]}"


# ── X投稿 ────────────────────────────────────────────────────────────────────────

def post_to_x(hook_text, url, is_reply=False, reply_to_id=None):
    """
    post_to_x.sh を呼び出してX投稿。
    hook_text: フック文 (URL除く)
    戻り値: (success: bool, result_str: str)
    """
    post_script = os.path.join(BASE_DIR, "google_metrics", "post_to_x.sh")
    if not os.path.exists(post_script):
        return False, "post_to_x.shが見つからない"

    # DRY_RUN制御はpost_to_x.sh内のENABLE_X_POST環境変数に依存
    env = os.environ.copy()
    try:
        result = subprocess.run(
            ["bash", post_script, hook_text, url],
            capture_output=True, text=True, timeout=120,
            env=env
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0 and "BLOCKED" not in output.upper() and "ERROR" not in output.upper()
        return success, output[:500]
    except Exception as e:
        return False, str(e)


# ── メインリライト処理 ────────────────────────────────────────────────────────────

def process_item(item, gsc_data, action_hist):
    """1件のキューアイテムを処理。戻り値: action_record dict"""
    post_id  = str(item.get("post_id", ""))
    priority = item.get("priority", "P2")
    rank     = item.get("rank", "IMPROVE")
    title    = item.get("title", "")
    url      = item.get("url", "")
    category = item.get("category", "")

    action = {
        "post_id": post_id,
        "priority": priority,
        "rank": rank,
        "executed_at": now_utc().isoformat(),
        "original_title": title,
        "new_title": None,
        "title_changed": False,
        "meta_changed": False,
        "thumb_changed": False,
        "x_posted": False,
        "x_result": None,
        "wp_update_ok": False,
        "wp_error": None,
        "skipped": False,
        "skip_reason": None,
        "before_score": None,
        "after_score": None,
        "improvement_delta": None,
    }

    # 安全チェック
    ok, reason = safety_check(post_id, rank, gsc_data, action_hist)
    if not ok:
        action["skipped"] = True
        action["skip_reason"] = reason
        print(f"  SKIP post_id={post_id}: {reason}")
        return action

    print(f"  処理中: [{priority}] {rank} post_id={post_id} {title[:30]}")

    wp_updates = {}
    is_p0_p1 = priority in ("P0", "P1")

    # ── タイトル差し替え ────────────────────────────────────────────────────────
    if is_p0_p1:
        # GSC登録済みかチェック
        gsc = gsc_data.get(post_id, {})
        indexed = gsc.get("indexed", False)
        title_change_count = sum(1 for a in action_hist.get(post_id, []) if a.get("title_changed"))

        if not indexed or title_change_count == 0:
            candidates = item.get("candidates", [])
            pattern_hint = candidates[0].get("title_hint", "") if candidates else ""
            new_title = generate_new_title(title, category, pattern_hint)
            if new_title and new_title != title:
                wp_updates["title"] = new_title
                action["new_title"] = new_title
                action["title_changed"] = True
                print(f"    タイトル: {title[:25]} → {new_title[:25]}")

        # meta description 再生成
        use_title = action["new_title"] or title
        meta = generate_meta_desc(use_title, category)
        if meta:
            wp_updates["excerpt"] = meta
            action["meta_changed"] = True

    elif priority == "P2":
        # IMPROVE: thumb_scoreが低ければタイトルも変更
        # (簡易判定: winning_patternsから該当記事のthumb_scoreを確認)
        # 今回はX投稿改善のみ、タイトルは維持
        pass

    # ── WP更新実行 ───────────────────────────────────────────────────────────────
    if wp_updates:
        wp_ok, wp_err = update_wp_post(post_id, wp_updates)
        action["wp_update_ok"] = wp_ok
        action["wp_error"] = wp_err if not wp_ok else None
        if not wp_ok:
            print(f"    ⚠️ WP更新失敗: {wp_err}")
        else:
            print(f"    ✅ WP更新成功")

    # ── X投稿 ────────────────────────────────────────────────────────────────────
    hook_title = action["new_title"] or title
    hook_text  = generate_x_hook(hook_title, url, category)

    x_ok, x_result = post_to_x(hook_text, url)
    action["x_posted"] = x_ok
    action["x_result"] = x_result[:300] if x_result else None
    if x_ok:
        print(f"    ✅ X投稿成功")
    else:
        print(f"    ⚠️ X投稿失敗/スキップ: {(x_result or '')[:100]}")

    return action


def run(dry_run=False):
    queue  = load_jsonl(QUEUE_FILE)
    gsc    = load_json(GSC_FILE)
    hist   = load_action_history()

    if not queue:
        print("再生成キューが空です")
        return []

    # WINランクの最新評価を取得してフィルタ
    latest_evals = {}
    for r in load_jsonl(EVAL_FILE):
        pid = str(r.get("post_id", ""))
        if pid not in latest_evals or (r.get("hours_since_publish", 0) or 0) > (latest_evals[pid].get("hours_since_publish", 0) or 0):
            latest_evals[pid] = r

    # 優先度順ソート
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    sorted_queue = sorted(queue, key=lambda x: priority_order.get(x.get("priority", "P2"), 2))

    actions = []
    for item in sorted_queue:
        post_id = str(item.get("post_id", ""))

        # WIN記事はスキップ
        ev = latest_evals.get(post_id, {})
        if ev.get("rank") == "WIN":
            print(f"  SKIP (WIN) post_id={post_id}")
            continue

        if dry_run:
            print(f"  [DRY-RUN] {item.get('priority')} {item.get('rank')} post_id={post_id} {item.get('title','')[:30]}")
            continue

        action = process_item(item, gsc, hist)
        actions.append(action)
        append_jsonl(ACTIONS_FILE, action)

        # 処理後にhistを更新
        hist.setdefault(post_id, []).append(action)

    return actions


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("[DRY-RUN モード] WP/X更新は実行しません")

    results = run(dry_run=dry)

    if not dry:
        skipped = [r for r in results if r.get("skipped")]
        executed = [r for r in results if not r.get("skipped")]
        wp_ok    = [r for r in executed if r.get("wp_update_ok")]
        wp_fail  = [r for r in executed if r.get("wp_error")]
        x_ok     = [r for r in executed if r.get("x_posted")]
        summary = (f"完了: 実行={len(executed)} SKIP={len(skipped)} "
                   f"WP更新成功={len(wp_ok)} X投稿成功={len(x_ok)}")
        print(f"\n{summary}")
        if executed:
            notify_discord(f"✏️ auto_rewriter {summary}")
        if wp_fail:
            notify_discord(f"⚠️ auto_rewriter WP更新失敗: {len(wp_fail)}件 "
                            f"post_id={[r['post_id'] for r in wp_fail]}")
