#!/usr/bin/env python3
"""artist_page_generator.py — アーティスト別専用プロフィールページ生成

TOP20アーティストの専用ページを生成し、WPにdraft or publish投稿する。
既存記事がある場合はスキップ（重複防止）。

使い方:
  python3 lib/artist_page_generator.py --artist bts
  python3 lib/artist_page_generator.py --all --dry-run
  python3 lib/artist_page_generator.py --all --status draft
  python3 lib/artist_page_generator.py --list          # 対象一覧表示
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config" / "artist_master.json"
LOGS = BASE / "logs"
LOG_FILE = LOGS / "artist_page_generation.jsonl"
WP_URL = "https://www.kpopjournal.tokyo"
WP_API = f"{WP_URL}/wp-json/wp/v2"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))


def load_artists() -> list[dict]:
    with open(CONFIG) as f:
        data = json.load(f)
    return data["artists"]


def get_artist(artist_id: str) -> dict | None:
    for a in load_artists():
        if a["id"] == artist_id:
            return a
    return None


def check_existing_post(slug: str) -> dict | None:
    """WP APIでスラッグの既存記事を確認"""
    import urllib.request
    import urllib.parse
    url = f"{WP_API}/posts?slug={urllib.parse.quote(slug)}&status=publish,draft,pending"
    try:
        # wp_auth から認証情報を取得
        auth_header = _read_wp_auth()
        req = urllib.request.Request(url, headers={"Authorization": auth_header})
        with urllib.request.urlopen(req, timeout=15) as res:
            posts = json.loads(res.read())
        if posts:
            return posts[0]
    except Exception:
        pass
    return None


def _read_wp_auth() -> str:
    """~/.wp_auth から Basic認証ヘッダ値を読み取る"""
    wp_auth_path = Path.home() / ".wp_auth"
    if wp_auth_path.exists():
        for line in wp_auth_path.read_text().splitlines():
            m = re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\\n]+)"?', line.strip())
            if m:
                return m.group(1).split(": ", 1)[1]
    import base64
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return f"Basic {token}"


def build_prompt(artist: dict) -> str:
    """Claude呼び出し用のプロンプトを構築"""
    today = datetime.now(JST).strftime("%Y年%m月%d日")
    members_text = ""
    if artist.get("members"):
        lines = []
        for m in artist["members"]:
            lines.append(f"  - {m['name']}（{m.get('name_ko', '')}）: {m.get('role', '')} / 誕生日: {m.get('birthday', '不明')}")
        members_text = "\n".join(lines)

    debut = artist.get("debut_date", "不明")
    return f"""今日は{today}です。
以下のK-POPアーティストの完全プロフィールページ記事を生成せよ。

【アーティスト情報】
- 名前: {artist['name_ja']}（{artist['name_en']} / {artist['name_ko']}）
- 所属事務所: {artist.get('agency', '不明')}
- デビュー日: {debut}
- タイプ: {artist.get('type', 'group')}
- メンバー:
{members_text}

【WebSearchで必ず取得すべき最新情報】
1.「{artist['name_en']} 2026 最新ニュース」で直近の活動を確認
2.「{artist['name_en']} discography 2026」で最新リリースを確認
3.「{artist['name_en']} tour concert 2026」でツアー/コンサート情報を確認
4.「{artist['name_en']} awards records」で受賞歴・記録を確認

【記事構成（必須H2セクション）】
1. {artist['name_ja']}とは？ — 一目でわかるプロフィール概要
2. メンバー紹介 — 全メンバーのプロフィール・役割・特徴（表形式推奨）
3. デビューから現在まで — 年表形式の活動履歴
4. ディスコグラフィー — アルバム・シングル一覧（最新作を強調）
5. ライブ・ツアー情報 — 最新のコンサート・ワールドツアー
6. 受賞歴・記録 — 主要な受賞・記録達成
7. {artist['name_ja']}の魅力 — ファンが語る3つの魅力ポイント
8. 最新ニュース — 直近の注目トピック3選
9. SNS・公式リンク — 公式アカウント一覧
10. まとめ — ファンへのメッセージ・今後の展望

【品質要件】
- 5000文字以上の充実した内容
- 正確なファクトのみ記載（推測禁止）
- メンバー表は <table> タグで作成
- 年表は西暦順で整理
- 「※本記事は{today}時点の情報です」を末尾に追記
- FAQ構造データ用に「よくある質問」セクション（3問以上）を含める

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（例：{artist['name_ja']}完全プロフィール｜メンバー・経歴・最新情報【2026年版】）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
"""


def generate_article(artist: dict, dry_run: bool = False) -> dict:
    """Claudeでアーティスト記事を生成"""
    prompt = build_prompt(artist)
    out_file = LOGS / f"artist_page_{artist['id']}.md"

    if dry_run:
        print(f"  [DRY-RUN] {artist['name_en']}: プロンプト {len(prompt)} chars")
        return {"status": "dry_run", "artist": artist["id"]}

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "--allowedTools", "WebSearch", "-p", prompt],
            capture_output=True, text=True, timeout=300
        )
        content = result.stdout.strip()
        if not content or len(content) < 500:
            return {"status": "error", "artist": artist["id"], "error": "出力が短すぎる"}

        out_file.write_text(content, encoding="utf-8")
        return {"status": "ok", "artist": artist["id"], "file": str(out_file), "length": len(content)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "artist": artist["id"], "error": "タイムアウト(300s)"}
    except Exception as e:
        return {"status": "error", "artist": artist["id"], "error": str(e)}


def post_to_wordpress(artist: dict, content_file: Path, status: str = "publish") -> dict:
    """生成した記事をWordPressに投稿"""
    text = content_file.read_text(encoding="utf-8").strip()
    lines = text.split("\n")
    title = lines[0].strip()
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else "\n".join(lines[1:]).strip()

    if not title or not body:
        return {"success": False, "error": "タイトルまたは本文が空"}

    # 既存記事チェック
    existing = check_existing_post(artist["slug"])
    if existing:
        return {
            "success": False,
            "error": f"既存記事あり (ID: {existing.get('id')}, URL: {existing.get('link', '')})",
            "existing_id": existing.get("id"),
        }

    # メタディスクリプション生成
    plain = re.sub(r"<[^>]+>", "", body)
    plain = re.sub(r"\s+", " ", plain).strip()
    meta_desc = ""
    for sent in re.split(r"[。！？]", plain):
        sent = sent.strip()
        if len(sent) >= 30:
            meta_desc = (sent + "。")[:120]
            break
    if not meta_desc:
        meta_desc = plain[:120]

    import requests
    headers = {
        "Authorization": _read_wp_auth(),
        "Content-Type": "application/json",
    }
    data = {
        "title": title,
        "content": body,
        "status": status,
        "slug": artist["slug"],
        "categories": [artist.get("wp_category_id", 1)],
        "tags": artist.get("wp_tag_ids", []),
        "excerpt": meta_desc,
        "meta": {"_aioseo_description": meta_desc},
    }

    for attempt in range(3):
        try:
            res = requests.post(f"{WP_API}/posts", headers=headers, json=data, timeout=30)
            if res.status_code == 201:
                result = res.json()
                return {
                    "success": True,
                    "post_id": result.get("id"),
                    "url": result.get("link", ""),
                }
            elif res.status_code == 429:
                time.sleep(30 * (attempt + 1))
            elif 500 <= res.status_code < 600:
                time.sleep(10 * (attempt + 1))
            else:
                return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:300]}"}
        except Exception as e:
            time.sleep(10 * (attempt + 1))

    return {"success": False, "error": "Max retries exceeded"}


def log_result(artist_id: str, result: dict):
    LOGS.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "artist": artist_id,
        **result,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="アーティスト専用ページ生成")
    parser.add_argument("--artist", help="アーティストID（例: bts, blackpink）")
    parser.add_argument("--all", action="store_true", help="全TOP20アーティスト一括生成")
    parser.add_argument("--list", action="store_true", help="対象アーティスト一覧を表示")
    parser.add_argument("--dry-run", action="store_true", help="実際の生成・投稿をスキップ")
    parser.add_argument("--status", default="publish", choices=["publish", "draft"],
                        help="投稿ステータス（default: publish）")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                        help="既存記事があればスキップ（デフォルト有効）")
    args = parser.parse_args()

    artists = load_artists()

    if args.list:
        print(f"=== TOP {len(artists)} アーティスト ===")
        for a in artists:
            slug = a["slug"]
            existing = check_existing_post(slug)
            status = f"  [既存: ID {existing['id']}]" if existing else "  [未作成]"
            print(f"  {a['id']:20s} {a['name_ja']:30s} /{slug}{status}")
        return

    targets = []
    if args.artist:
        a = get_artist(args.artist)
        if not a:
            print(f"ERROR: アーティスト '{args.artist}' が見つかりません")
            sys.exit(1)
        targets = [a]
    elif args.all:
        targets = artists
    else:
        parser.print_help()
        sys.exit(1)

    print(f"=== アーティスト専用ページ生成 ===")
    print(f"対象: {len(targets)}アーティスト / ステータス: {args.status}")
    print()

    results = {"ok": 0, "skipped": 0, "error": 0}

    for i, artist in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {artist['name_en']} ({artist['id']})")

        # 既存チェック
        if args.skip_existing and not args.dry_run:
            existing = check_existing_post(artist["slug"])
            if existing:
                print(f"  SKIP: 既存記事あり (ID: {existing.get('id')})")
                results["skipped"] += 1
                log_result(artist["id"], {"status": "skipped", "existing_id": existing.get("id")})
                continue

        # 記事生成
        gen_result = generate_article(artist, dry_run=args.dry_run)
        if gen_result["status"] != "ok":
            print(f"  {gen_result['status'].upper()}: {gen_result.get('error', '')}")
            if gen_result["status"] == "error":
                results["error"] += 1
            else:
                results["skipped"] += 1
            log_result(artist["id"], gen_result)
            continue

        content_file = Path(gen_result["file"])
        print(f"  生成完了: {gen_result['length']} chars")

        # WP投稿
        if not args.dry_run:
            wp_result = post_to_wordpress(artist, content_file, status=args.status)
            if wp_result.get("success"):
                print(f"  投稿完了: ID={wp_result['post_id']} URL={wp_result['url']}")
                results["ok"] += 1
                log_result(artist["id"], {"status": "posted", **wp_result})
            else:
                print(f"  投稿失敗: {wp_result.get('error', '')}")
                results["error"] += 1
                log_result(artist["id"], {"status": "post_failed", **wp_result})
        else:
            results["ok"] += 1

        # レート制限回避
        if i < len(targets):
            time.sleep(5)

    print()
    print(f"=== 完了 ===")
    print(f"  成功: {results['ok']} / スキップ: {results['skipped']} / エラー: {results['error']}")


if __name__ == "__main__":
    main()
