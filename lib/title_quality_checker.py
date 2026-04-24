#!/usr/bin/env python3
"""
タイトル品質チェッカー — 誤字・エンティティ残存・文字化けを自動検出・修正

cron: 毎日8時に直近24時間の記事タイトルを自動チェック
用途: パイプライン内のリアルタイム検証 + 日次バッチ修正

使い方:
  python3 lib/title_quality_checker.py              # 日次バッチ(直近24h)
  python3 lib/title_quality_checker.py --check "タイトル文字列"  # 単一チェック(パイプライン用)
  python3 lib/title_quality_checker.py --days 7     # 直近7日分チェック
"""

import json
import os
import re
import sys
import html
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CONFIG = SCRIPT_DIR / "config"
LOGS = SCRIPT_DIR / "logs"

# ── 誤字パターン辞書 ──
TYPO_MAP = {
    "スケジュル": "スケジュール",
    "グルー復帰": "グループ復帰",
    "アルバ ム": "アルバム",
    "コンサ ート": "コンサート",
    "メンバ ー": "メンバー",
    "デビュ ー": "デビュー",
    "プロフィル": "プロフィール",
    "カムバク ": "カムバック",
    "チケッ ト": "チケット",
    "ランキン グ": "ランキング",
    "アーテ ィスト": "アーティスト",
    "パフォー マンス": "パフォーマンス",
    "ミュージッ ク": "ミュージック",
    "ワールドツ アー": "ワールドツアー",
    "オフィシャ ル": "オフィシャル",
    "セットリス ト": "セットリスト",
    "コラボレー ション": "コラボレーション",
    "リリス ": "リリース",
    "カンバック": "カムバック",
    "ライブスト リーミング": "ライブストリーミング",
}

# カタカナ語の不自然な空白パターン（カタカナ+空白+カタカナ）
KATAKANA_SPACE_RE = re.compile(r"([ァ-ヶー])\s([ァ-ヶー])")


def check_title(title: str) -> list[dict]:
    """タイトルの品質問題を検出して返す"""
    issues = []

    # 1. HTMLエンティティ残存
    entity_match = re.findall(r"&#\d+;|&[a-z]+;", title)
    if entity_match:
        issues.append({
            "type": "entity",
            "detail": f"HTMLエンティティ残存: {', '.join(entity_match)}",
            "auto_fix": True,
        })

    # 2. 文字化け（U+FFFD 置換文字）
    if "\ufffd" in title:
        issues.append({
            "type": "mojibake",
            "detail": "文字化け(U+FFFD)検出",
            "auto_fix": False,  # 元の文字が不明なので再生成が必要
        })

    # 3. 制御文字・改行
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", title) or "\\n" in title:
        issues.append({
            "type": "control_char",
            "detail": "制御文字または改行コード残存",
            "auto_fix": True,
        })

    # 4. 既知の誤字パターン
    for typo, correct in TYPO_MAP.items():
        if typo in title:
            issues.append({
                "type": "typo",
                "detail": f"誤字「{typo}」→「{correct}」",
                "auto_fix": True,
            })

    # 5. カタカナ語の不自然な空白
    space_matches = KATAKANA_SPACE_RE.findall(title)
    if space_matches:
        issues.append({
            "type": "katakana_space",
            "detail": f"カタカナ語内の不自然な空白: {len(space_matches)}箇所",
            "auto_fix": True,
        })

    # 6. 半角カナ
    if re.search(r"[\uFF65-\uFF9F]", title):
        issues.append({
            "type": "halfwidth_kana",
            "detail": "半角カタカナ検出",
            "auto_fix": True,
        })

    # 7. 連続する全角空白
    if "　　" in title:
        issues.append({
            "type": "double_space",
            "detail": "連続全角空白",
            "auto_fix": True,
        })

    return issues


def fix_title(title: str) -> str:
    """タイトルの自動修正可能な問題を全て修正"""
    fixed = title

    # HTMLエンティティをデコード
    fixed = html.unescape(fixed)

    # 制御文字・改行を除去
    fixed = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", fixed)
    fixed = fixed.replace("\\n", " ").replace("\n", " ").replace("\r", "")

    # 既知の誤字を修正
    for typo, correct in TYPO_MAP.items():
        fixed = fixed.replace(typo, correct)

    # カタカナ語内の不自然な空白を除去
    fixed = KATAKANA_SPACE_RE.sub(r"\1\2", fixed)

    # 半角カナを全角に変換
    fixed = unicodedata.normalize("NFKC", fixed)
    # NFKCで崩れる可能性のある記号を元に戻す
    # (NFKCは半角カナ→全角カナの変換に使うが副作用で一部記号が変わる)

    # 連続空白を単一に
    fixed = re.sub(r"　　+", "　", fixed)
    fixed = re.sub(r"  +", " ", fixed)

    return fixed.strip()


def load_discord_webhook() -> str:
    """Discord webhook URL取得"""
    wh_file = CONFIG / "discord_webhooks.json"
    if wh_file.exists():
        try:
            data = json.loads(wh_file.read_text())
            for key in ("daily_ceo_report", "alert_summary", "urgent_errors"):
                urls = data.get(key, [])
                if urls:
                    return urls[0] if isinstance(urls, list) else urls
        except Exception:
            pass
    fallback = Path.home() / ".kpop_discord_webhook"
    if fallback.exists():
        return fallback.read_text().strip()
    return os.environ.get("DISCORD_WEBHOOK", "")


def send_discord(webhook: str, message: str):
    """Discordにメッセージ送信"""
    if not webhook:
        print("  ⚠️ Discord webhook未設定 — ログのみ")
        return
    payload = json.dumps({"content": message[:2000]}).encode()
    req = Request(webhook, data=payload, headers={"Content-Type": "application/json"})
    try:
        urlopen(req, timeout=10)
        print("  ✅ Discord送信完了")
    except URLError as e:
        print(f"  ⚠️ Discord送信失敗: {e}")


def wp_api(endpoint: str, method: str = "GET", data: dict | None = None) -> dict | list:
    """WordPress REST API呼び出し"""
    site_url = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
    url = f"{site_url}/wp-json/wp/v2/{endpoint}"
    headers = {"Content-Type": "application/json"}

    # 認証
    user = os.environ.get("WP_USER", "")
    pw = os.environ.get("WP_PASS", "") or os.environ.get("WP_APP_PASSWORD", "")
    if user and pw:
        import base64
        cred = base64.b64encode(f"{user}:{pw}".encode()).decode()
        headers["Authorization"] = f"Basic {cred}"

    body = json.dumps(data).encode() if data else None
    req = Request(url, data=body, headers=headers, method=method)
    resp = urlopen(req, timeout=30)
    return json.loads(resp.read())


def check_recent_posts(hours: int = 24) -> list[dict]:
    """直近N時間の記事タイトルをチェック"""
    # ISO8601 で after パラメータ生成
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    posts = wp_api(f"posts?per_page=50&after={after}&_fields=id,title,date&orderby=date&order=desc")

    results = []
    for p in posts:
        title = p["title"]["rendered"]
        pid = p["id"]
        issues = check_title(title)
        if issues:
            fixed = fix_title(title)
            results.append({
                "id": pid,
                "original": title,
                "fixed": fixed,
                "issues": issues,
                "has_mojibake": any(i["type"] == "mojibake" for i in issues),
            })
    return results


def fix_wp_title(post_id: int, new_title: str) -> bool:
    """WordPressの記事タイトルを更新"""
    try:
        wp_api(f"posts/{post_id}", method="POST", data={"title": new_title})
        return True
    except Exception as e:
        print(f"  ❌ ID:{post_id} 更新失敗: {e}")
        return False


def run_batch(hours: int = 24):
    """バッチ実行: 直近N時間の記事を検査・修正"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{now}] タイトル品質チェック開始（直近{hours}時間）")

    results = check_recent_posts(hours)

    if not results:
        print("  ✅ 問題のあるタイトルはありません")
        return

    print(f"  ❌ 問題あり: {len(results)}件")

    fixed_count = 0
    skipped_count = 0
    report_lines = [f"📝 **タイトル品質チェック** ({now})\n問題: {len(results)}件\n"]

    for r in results:
        issue_types = ", ".join(i["type"] for i in r["issues"])
        print(f"  ID:{r['id']} [{issue_types}]")
        print(f"    元: {r['original']}")
        print(f"    修: {r['fixed']}")

        if r["has_mojibake"]:
            print(f"    ⚠️ 文字化けは自動修正不可 — 手動確認が必要")
            skipped_count += 1
            report_lines.append(f"⚠️ ID:{r['id']} 文字化け — 手動確認必要\n  `{r['original']}`")
        elif r["original"] != r["fixed"]:
            if fix_wp_title(r["id"], r["fixed"]):
                fixed_count += 1
                report_lines.append(f"✅ ID:{r['id']} 修正済\n  `{r['original']}`\n  → `{r['fixed']}`")
            else:
                skipped_count += 1
                report_lines.append(f"❌ ID:{r['id']} 更新失敗\n  `{r['original']}`")

    summary = f"\n修正: {fixed_count}件 / スキップ: {skipped_count}件 / 合計: {len(results)}件"
    print(summary)
    report_lines.append(summary)

    # Discord通知
    webhook = load_discord_webhook()
    if fixed_count > 0 or skipped_count > 0:
        send_discord(webhook, "\n".join(report_lines))

    # ログ記録
    log_entry = {
        "ts": now,
        "checked": len(results),
        "fixed": fixed_count,
        "skipped": skipped_count,
        "details": [
            {"id": r["id"], "original": r["original"], "fixed": r["fixed"],
             "issues": [i["type"] for i in r["issues"]]}
            for r in results
        ],
    }
    log_file = LOGS / "title_check.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def main():
    # env_loader
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    if "--check" in sys.argv:
        idx = sys.argv.index("--check")
        title = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if not title:
            print("使い方: python3 title_quality_checker.py --check 'タイトル'")
            sys.exit(1)
        issues = check_title(title)
        if issues:
            fixed = fix_title(title)
            for i in issues:
                print(f"  [{i['type']}] {i['detail']}")
            print(f"  修正後: {fixed}")
            # パイプライン用: 修正後タイトルを stdout に出力
            sys.exit(1)  # 問題あり
        else:
            sys.exit(0)  # 問題なし
    else:
        hours = 24
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 1
            hours = days * 24
        run_batch(hours)


if __name__ == "__main__":
    main()
