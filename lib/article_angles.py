#!/usr/bin/env python3
"""article_angles.py — 探索フェーズ用の「記事の角度」生成

owner方針(2026-08-18): しばらくは幅広にいろんな角度から記事を作成し、
データを集めて当たり筋を見つける。聖地巡礼は放映後に効いてくる。

なぜ必要か(実測):
  config/auto_directives.json の focus_themes 295件が **全て**
  source='breaking_followup' / category_suggest='深掘り' だった。
  直近14日の公開223本を切り口で分類しても OST/ロケ地/文化解説/相関図は **0本**。
  「速報の深掘り」1本槍で、探索になっていなかった。

  切り口別のCTR実測(28d)には明確な差がある:
    主題歌/OST  CTR 8.33%  (imp  156 — 記事が少ないだけで筋は良い)
    声優/吹替   CTR 1.78%  (imp 5730 — 実写韓ドラマに限ると 1.34% と特に弱い)
    相関図      CTR 1.59%  (imp 9001 — 競合多数)
    ロケ地      pos13〜44  (記事が無くて拾えていない = 競合不在の空白地帯)
  どの角度が効くかは**出してみないと分からない**ので、まず角度を出し分ける。

使い方:
    from lib.article_angles import build_angle_themes
    themes = build_angle_themes(title, artist, is_drama=True, days_since_release=30)
    # -> focus_themes に追記できる dict のリスト

CLI:
    python3 lib/article_angles.py --title "『恋は飴模様』配信開始" --drama --days 30
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 「聖地巡礼(ロケ地)は放映後に効いてくる」(owner 2026-08-18)。
# 配信直後は作品そのものの検索が中心で、ロケ地需要はまだ立たない。
# 実測でも「恋は飴模様ロケ地」は pos16.5 / imp2 と、需要も供給もこれからの段階。
LOCATION_MIN_DAYS = 14

# 角度の定義。key はテーマの source に使う(angle:<key>)。
# lifetime_days: テーマの寿命。速報の深掘りは3日で腐るが、OSTやロケ地は腐らない。
ANGLES = [
    {
        "key": "ost",
        "label": "主題歌・OST",
        "category_suggest": "音楽",
        "drama_only": True,
        "lifetime_days": 120,
        "hint": ("作品の主題歌・OST・挿入歌を曲ごとに整理する記事。"
                 "歌手名、K-POPアーティストの参加、どの場面で流れるか、"
                 "配信で聴ける場所まで書く。"
                 "実測: OST系クエリはCTR8.33%と当サイトで最も高い(相関図の5倍)"),
    },
    {
        "key": "location",
        "label": "ロケ地・聖地巡礼",
        "category_suggest": "旅行",
        "drama_only": True,
        "min_days_since_release": LOCATION_MIN_DAYS,
        "lifetime_days": 365,
        "hint": ("作品のロケ地・撮影地をまとめ、行き方とあわせて紹介する記事。"
                 "住所・最寄駅・作中のどの場面かを対応づける。"
                 "実測: 競合記事が存在せず(検索しても別作品しか出ない)、"
                 "当サイトもpos16〜44で拾えていない空白地帯。放映後に効く"),
    },
    {
        "key": "culture",
        "label": "文化・用語解説",
        "category_suggest": "解説",
        "drama_only": False,
        "lifetime_days": 365,
        "hint": ("作品や話題に出てくる韓国文化・用語・慣習を解説する記事。"
                 "『リアクティべーティッド 意味』のように、意味を知りたい検索が"
                 "実際にpos7で発生している(ただし当サイトは0クリック=拾えていない)"),
    },
    {
        "key": "actor",
        "label": "主演俳優・人物",
        "category_suggest": "人物",
        "drama_only": False,
        "lifetime_days": 180,
        "hint": ("主演俳優・アーティストの経歴、代表作、次回作、プロフィールをまとめる記事。"
                 "作品から入った読者が『この人は誰?』と辿る導線を作る"),
    },
    {
        "key": "food",
        "label": "グルメ・食文化",
        "category_suggest": "グルメ",
        "drama_only": False,
        "lifetime_days": 365,
        "hint": ("作中に出てくる料理や、韓国の食文化を紹介する記事。"
                 "日本で食べられる店や再現レシピまで書けると回遊しやすい"),
    },
    {
        "key": "chart",
        "label": "チャート・記録",
        "category_suggest": "データ",
        "drama_only": False,
        "lifetime_days": 60,
        "hint": ("チャート順位・再生数・記録を数字で整理する記事。"
                 "数字は他と比較して初めて意味が出るので、必ず歴代や同時期作品と並べる"),
    },
    {
        "key": "howto",
        "label": "視聴・参加ガイド",
        "category_suggest": "ガイド",
        "drama_only": False,
        "lifetime_days": 180,
        "hint": ("視聴方法・配信スケジュール・チケット取得など、読者が『次に何をすればいいか』"
                 "に答える実務的な記事。当サイトの当たり記事はこの型が多い"),
    },
    {
        "key": "background",
        "label": "背景・比較",
        "category_suggest": "深掘り",
        "drama_only": False,
        "lifetime_days": 30,
        "hint": ("なぜ話題になっているのかを、過去の事例や他アーティストと比較して解く記事。"
                 "既存のbreaking_followupと同系だが、必ず比較対象を置く点が違う"),
    },
]


# 角度テーマの保持上限。速報は日15本出ており、1本あたり6〜7角度を注入すると
# 14日で約1,300件になる。消費は日2本(DAILY_CAP)なので大半が死蔵するうえ、
# focus_themes は X 投稿側(lib/x_conversation_starter)も読むため肥大が波及する。
# 過去に focus_themes が295件溜まって期限切れ258件を掴んだ事故もある
# ([[x-conversation-topic-supply-not-prompt]])。
ANGLE_THEME_CAP = 60


def cap_angle_themes(themes: list[dict]) -> list[dict]:
    """角度テーマを上限まで間引く。期限切れを落としてから、新しい順に残す。

    ただし探索が目的なので **角度の多様性を保つ**。単純な新しい順だと、
    たまたま多く注入された角度(OST等)が全枠を埋め、希少な角度
    (ロケ地は放映14日後にしか出ない)が消える。角度ごとに均等枠を配ってから、
    余った枠を新しい順で埋める。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    alive = [t for t in themes if (t.get("expires_at") or "9999") >= today]
    if len(alive) <= ANGLE_THEME_CAP:
        return alive
    by_angle: dict[str, list[dict]] = {}
    for t in alive:
        by_angle.setdefault(str(t.get("source", "")), []).append(t)
    for v in by_angle.values():
        v.sort(key=lambda t: t.get("added_at", ""), reverse=True)
    # 角度ごとに均等枠(最低1件)を配る
    per = max(1, ANGLE_THEME_CAP // max(1, len(by_angle)))
    kept, leftovers = [], []
    for v in by_angle.values():
        kept.extend(v[:per])
        leftovers.extend(v[per:])
    leftovers.sort(key=lambda t: t.get("added_at", ""), reverse=True)
    kept.extend(leftovers[:max(0, ANGLE_THEME_CAP - len(kept))])
    kept.sort(key=lambda t: t.get("added_at", ""), reverse=True)
    return kept[:ANGLE_THEME_CAP]


def _clean_title(title: str) -> str:
    """テーマ名に使うため、見出しから**作品名だけ**を抜く。

    ニュース見出しをそのまま使うと「『恋は飴模様』Netflixで配信開始の主題歌・OST」
    のように冗長で不自然になる。作品名は鉤括弧に入っていることが多いので優先し、
    無ければ最初の句読点までを作品名と見なす。
    """
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    t = re.split(r"[|｜]", t)[0].strip()
    # 『』「」で囲まれた最初の塊を作品名として採る(括弧ごと残す)
    m = re.search(r"[『「]([^』」]{1,30})[』」]", t)
    if m:
        return m.group(0)
    # 鉤括弧が無ければ、最初の句読点・助詞の手前までを作品名と見なす
    t = re.split(r"[、,。]", t)[0].strip()
    return t[:20].strip()


def pick_angles_for(title: str, artist: str = "", is_drama: bool = False,
                    days_since_release: int = 0) -> list[dict]:
    """この題材に出してよい角度を返す。

    ロケ地は放映後に効くため、配信から min_days_since_release 日経つまで出さない。
    """
    out = []
    for a in ANGLES:
        if a.get("drama_only") and not is_drama:
            continue
        need = a.get("min_days_since_release")
        if need is not None and days_since_release < need:
            continue
        out.append(a)
    return out


def build_angle_themes(title: str, artist: str = "", is_drama: bool = False,
                       days_since_release: int = 0,
                       buzz_score: float = 8.0) -> list[dict]:
    """focus_themes に追記できる形式でテーマを組む。

    既存の breaking_followup と区別できるよう source を 'angle:<key>' にする。
    どの角度が効いたかを後から集計するための鍵になる。
    """
    now = datetime.now()
    name = _clean_title(title)
    if not name:
        return []
    out = []
    for a in pick_angles_for(title, artist, is_drama, days_since_release):
        out.append({
            "topic": f"{name}の{a['label']}",
            "hint": (f"{a['hint']}。対象: {name}"
                     + (f"(関連: {artist})" if artist else "")),
            "category_suggest": a["category_suggest"],
            "added_at": now.strftime("%Y-%m-%d"),
            "source": f"angle:{a['key']}",
            "buzz_score": buzz_score,
            "expires_at": (now + timedelta(days=a["lifetime_days"])).strftime("%Y-%m-%d"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--artist", default="")
    ap.add_argument("--drama", action="store_true")
    ap.add_argument("--days", type=int, default=0, help="配信/公開からの経過日数")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    themes = build_angle_themes(args.title, args.artist, args.drama, args.days)
    if args.json:
        print(json.dumps(themes, ensure_ascii=False, indent=2))
    else:
        print(f"=== 出せる角度 {len(themes)}件 ===")
        for t in themes:
            print(f"  [{t['source']:18s}] {t['topic']}")
            print(f"     期限 {t['expires_at']} / cat={t['category_suggest']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
