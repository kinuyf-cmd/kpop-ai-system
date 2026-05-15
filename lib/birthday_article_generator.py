#!/usr/bin/env python3
"""birthday_article_generator.py — K-POPアーティスト誕生日記事自動生成

artist_master.json のメンバー誕生日を参照し、
当日 or 翌日が誕生日のメンバーの記念記事を自動生成する。

使い方:
  python3 lib/birthday_article_generator.py                  # 当日+翌日分を生成
  python3 lib/birthday_article_generator.py --date 2026-09-01 # 指定日で実行
  python3 lib/birthday_article_generator.py --check-week      # 今週の誕生日一覧
  python3 lib/birthday_article_generator.py --dry-run         # テスト実行
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config" / "artist_master.json"
LOGS = BASE / "logs"
LOG_FILE = LOGS / "birthday_articles.jsonl"
POSTED_LOG = LOGS / "birthday_posted.json"
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
JST = timezone(timedelta(hours=9))


def load_artists() -> list[dict]:
    with open(CONFIG) as f:
        return json.load(f)["artists"]


def load_posted() -> dict:
    """投稿済み誕生日記事を読み込み（年+メンバー名で重複防止）"""
    if POSTED_LOG.exists():
        try:
            return json.loads(POSTED_LOG.read_text())
        except Exception:
            pass
    return {}


def save_posted(data: dict):
    LOGS.mkdir(exist_ok=True)
    POSTED_LOG.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def find_birthdays(target_date: date) -> list[dict]:
    """指定日が誕生日のメンバーを検索"""
    artists = load_artists()
    matches = []
    mm_dd = target_date.strftime("%m-%d")

    for artist in artists:
        for member in artist.get("members", []):
            bday = member.get("birthday", "")
            if not bday:
                continue
            if bday[5:] == mm_dd:
                birth_year = int(bday[:4])
                age = target_date.year - birth_year
                matches.append({
                    "member_name": member["name"],
                    "member_name_ko": member.get("name_ko", ""),
                    "birthday": bday,
                    "age": age,
                    "role": member.get("role", ""),
                    "group_name_en": artist["name_en"],
                    "group_name_ja": artist["name_ja"],
                    "group_id": artist["id"],
                    "group_slug": artist["slug"],
                    "agency": artist.get("agency", ""),
                    "wp_category_id": artist.get("wp_category_id", 1),
                    "wp_tag_ids": artist.get("wp_tag_ids", []),
                })
    return matches


def build_birthday_prompt(member: dict, target_date: date) -> str:
    """誕生日記事生成用プロンプト"""
    today_str = target_date.strftime("%Y年%m月%d日")
    birthday_mmdd = datetime.strptime(member["birthday"], "%Y-%m-%d").strftime("%m月%d日")

    return f"""今日は{today_str}です。
以下のK-POPアーティストメンバーの誕生日記念記事を生成せよ。

【メンバー情報】
- 名前: {member['member_name']}（{member['member_name_ko']}）
- グループ: {member['group_name_ja']}（{member['group_name_en']}）
- 誕生日: {birthday_mmdd}（{member['age']}歳）
- ポジション: {member['role']}
- 所属: {member['agency']}

【WebSearchで取得すべき情報】
1.「{member['member_name']} {member['group_name_en']} birthday」で誕生日関連情報を検索
2.「{member['member_name']} {member['group_name_en']} 2026」で最新活動を確認
3.「{member['member_name']} エピソード 名場面」で印象的なエピソードを確認

【記事構成（必須H2セクション）】
1. {member['member_name']}、{member['age']}歳の誕生日！ — リード文（ファンへの祝福メッセージ風）
2. {member['member_name']}プロフィール — 基本情報まとめ表
3. {member['member_name']}の魅力5選 — パフォーマンス・性格・エピソードから5つ
4. 活動ハイライト — これまでの主要な活動・成果
5. ファンが選ぶ名場面 — SNSやステージでの印象的な瞬間3選
6. 誕生日メッセージ — ファンコミュニティの反応・お祝いムード
7. 今後の活動予定 — 直近のカムバック・ツアー情報
8. まとめ — お祝いメッセージで締め

【品質要件】
- 3000文字以上の充実した内容
- お祝いムードの温かいトーン（ファンサイトらしさ）
- ファクトのみ記載（推測禁止）
- 年齢計算は正確に（{member['birthday']}生まれ → {member['age']}歳）
- 「※本記事は{today_str}時点の情報です」を末尾に追記
- FAQ「よくある質問」2問以上を含める

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（例：{member['member_name']}（{member['group_name_en']}）誕生日！{member['age']}歳の魅力と名場面を徹底紹介【{birthday_mmdd}】）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
"""


def generate_birthday_article(member: dict, target_date: date, dry_run: bool = False) -> dict:
    """誕生日記事を生成"""
    prompt = build_birthday_prompt(member, target_date)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", member["member_name"].lower())
    out_file = LOGS / f"birthday_{member['group_id']}_{safe_name}_{target_date.year}.md"

    if dry_run:
        print(f"  [DRY-RUN] {member['member_name']} ({member['group_name_en']}): プロンプト {len(prompt)} chars")
        return {"status": "dry_run", "member": member["member_name"]}

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "--allowedTools", "WebSearch", "-p", prompt],
            capture_output=True, text=True, timeout=300
        )
        content = result.stdout.strip()
        if not content or len(content) < 300:
            return {"status": "error", "member": member["member_name"], "error": "出力が短すぎる"}

        out_file.write_text(content, encoding="utf-8")
        return {"status": "ok", "member": member["member_name"], "file": str(out_file), "length": len(content)}
    except subprocess.TimeoutExpired:
        return {"status": "error", "member": member["member_name"], "error": "タイムアウト"}
    except Exception as e:
        return {"status": "error", "member": member["member_name"], "error": str(e)}


def _read_wp_auth() -> str:
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


def post_birthday_article(member: dict, content_file: Path, target_date: date, status: str = "publish") -> dict:
    """誕生日記事をWordPressに投稿"""
    text = content_file.read_text(encoding="utf-8").strip()
    lines = text.split("\n")
    title = lines[0].strip()
    body = "\n".join(lines[2:]).strip() if len(lines) > 2 else "\n".join(lines[1:]).strip()

    if not title or not body:
        return {"success": False, "error": "タイトルまたは本文が空"}

    safe_name = re.sub(r"[^a-zA-Z0-9]", "-", member["member_name"].lower()).strip("-")
    slug = f"{safe_name}-birthday-{target_date.year}"

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
        "slug": slug,
        "categories": [member.get("wp_category_id", 1)],
        "tags": member.get("wp_tag_ids", []),
        "excerpt": meta_desc,
        "meta": {"_aioseo_description": meta_desc},
    }

    # Pre-publish factcheck
    try:
        from lib.pre_publish_gate import pre_publish_gate
        gate_result = pre_publish_gate(
            title, body, post_type='post', kind='birthday',
            slug=slug, status=status,
            categories=data.get('categories'),
            excerpt=meta_desc,
        )
        if gate_result.get('verdict') == 'BLOCK':
            print(f"  [pre-publish] BLOCKED: {gate_result.get('block_reasons', [])}")
            data['status'] = 'draft'
        elif gate_result.get('verdict') == 'WARN':
            print(f"  [pre-publish] WARN: {gate_result.get('warnings', [])}")
    except Exception as e:
        print(f"  [pre-publish] gate error (continuing): {e}")

    # 2026-05-15: cluster dedup gate (project_cluster_dedup_gaps_2026_05_14 残置)
    # 同じ誕生日記事を 24h 内に複数回 publish させない (retry の二重投稿対策)
    if data.get('status') == 'publish':
        try:
            from lib.cluster_dedup import cluster_dedup_check
            is_dup, matched = cluster_dedup_check(
                title, hours=24, source='birthday_article_generator',
                candidate_body=body,
            )
            if is_dup:
                print(f"  [cluster_dedup] dup of '{matched[:60]}' → status=draft")
                data['status'] = 'draft'
        except Exception as e:
            print(f"  [cluster_dedup] err (continuing): {e}")

    for attempt in range(3):
        try:
            res = requests.post(f"{WP_API}/posts", headers=headers, json=data, timeout=30)
            if res.status_code == 201:
                result = res.json()
                post_id = result.get("id")
                # cluster dedup buffer 追記 (publish 経路のみ)
                if data.get('status') == 'publish':
                    try:
                        from lib.cluster_dedup import record_publish
                        record_publish(title, post_id=post_id,
                                       source='birthday_article_generator',
                                       body=body)
                    except Exception:
                        pass
                # Post-publish hook
                try:
                    from lib.post_publish_hook import run_post_publish
                    run_post_publish(post_id, post_type='post')
                except Exception as hook_e:
                    print(f"  [post-publish] hook error: {hook_e}")
                return {"success": True, "post_id": post_id, "url": result.get("link", "")}
            elif res.status_code == 429:
                time.sleep(30 * (attempt + 1))
            elif 500 <= res.status_code < 600:
                time.sleep(10 * (attempt + 1))
            else:
                return {"success": False, "error": f"HTTP {res.status_code}: {res.text[:300]}"}
        except Exception:
            time.sleep(10 * (attempt + 1))

    return {"success": False, "error": "Max retries exceeded"}


def log_result(entry: dict):
    LOGS.mkdir(exist_ok=True)
    entry["timestamp"] = datetime.now(JST).isoformat()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="K-POP誕生日記事自動生成")
    parser.add_argument("--date", help="対象日（YYYY-MM-DD形式、デフォルト=今日）")
    parser.add_argument("--check-week", action="store_true", help="今週の誕生日一覧を表示")
    parser.add_argument("--check-month", action="store_true", help="今月の誕生日一覧を表示")
    parser.add_argument("--dry-run", action="store_true", help="テスト実行")
    parser.add_argument("--status", default="publish", choices=["publish", "draft"])
    parser.add_argument("--include-tomorrow", action="store_true", default=True,
                        help="翌日分も事前生成（デフォルト有効）")
    args = parser.parse_args()

    if args.date:
        base_date = date.fromisoformat(args.date)
    else:
        base_date = datetime.now(JST).date()

    # 週間/月間一覧モード
    if args.check_week or args.check_month:
        days = 7 if args.check_week else 31
        label = "今週" if args.check_week else "今月"
        print(f"=== {label}の誕生日 ===")
        found_any = False
        for d in range(days):
            check_date = base_date + timedelta(days=d)
            matches = find_birthdays(check_date)
            for m in matches:
                found_any = True
                print(f"  {check_date.strftime('%m/%d')} {m['member_name']:15s} ({m['group_name_en']:15s}) {m['age']}歳")
        if not found_any:
            print("  該当なし")
        return

    # 生成対象の日付リスト
    target_dates = [base_date]
    if args.include_tomorrow:
        target_dates.append(base_date + timedelta(days=1))

    posted = load_posted()
    results = {"ok": 0, "skipped": 0, "error": 0}

    for target_date in target_dates:
        matches = find_birthdays(target_date)
        if not matches:
            print(f"{target_date.strftime('%Y-%m-%d')}: 誕生日該当なし")
            continue

        print(f"=== {target_date.strftime('%Y-%m-%d')} の誕生日 ({len(matches)}名) ===")

        for member in matches:
            key = f"{target_date.year}_{member['group_id']}_{member['member_name']}"
            print(f"  {member['member_name']} ({member['group_name_en']}) - {member['age']}歳")

            # 重複チェック
            if key in posted and not args.dry_run:
                print(f"    SKIP: 今年度投稿済み (ID: {posted[key].get('post_id', '?')})")
                results["skipped"] += 1
                continue

            # 記事生成
            gen_result = generate_birthday_article(member, target_date, dry_run=args.dry_run)
            if gen_result["status"] != "ok":
                print(f"    {gen_result['status'].upper()}: {gen_result.get('error', '')}")
                if gen_result["status"] == "error":
                    results["error"] += 1
                continue

            content_file = Path(gen_result["file"])
            print(f"    生成完了: {gen_result['length']} chars")

            # WP投稿
            if not args.dry_run:
                wp_result = post_birthday_article(member, content_file, target_date, status=args.status)
                if wp_result.get("success"):
                    print(f"    投稿完了: ID={wp_result['post_id']} URL={wp_result['url']}")
                    posted[key] = {
                        "post_id": wp_result["post_id"],
                        "url": wp_result["url"],
                        "date": target_date.isoformat(),
                    }
                    save_posted(posted)
                    results["ok"] += 1
                    log_result({
                        "action": "posted",
                        "member": member["member_name"],
                        "group": member["group_name_en"],
                        "age": member["age"],
                        **wp_result,
                    })
                else:
                    print(f"    投稿失敗: {wp_result.get('error', '')}")
                    results["error"] += 1
                    log_result({
                        "action": "post_failed",
                        "member": member["member_name"],
                        "group": member["group_name_en"],
                        "error": wp_result.get("error", ""),
                    })
            else:
                results["ok"] += 1

            time.sleep(3)

    print()
    print(f"=== 完了 ===")
    print(f"  成功: {results['ok']} / スキップ: {results['skipped']} / エラー: {results['error']}")


if __name__ == "__main__":
    main()
