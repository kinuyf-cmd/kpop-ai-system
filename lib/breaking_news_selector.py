#!/usr/bin/env python3
"""ストリーム4 速報候補抽出パイプライン (Day12)

trend_signals.jsonl(soompi signal)から複合スコアで速報候補 上位N件を抽出する。
記事生成・投稿はしない(抽出と候補リスト出力のみ)。citation skill / post_to_wp.py は別工程。

複合スコア:
    score = urgency_weight + engagement_normalized
      - urgency_weight: high=+3, normal=+0
      - engagement_normalized: engagement_score を候補集合内で 0-3 に min-max 正規化
    同点は engagement_score の生値で tiebreak。

既出除外:
    - logs/article_index.json(既出記事 title/url) と soompi URL/タイトルを照合
    - 同一 soompi URL の重複も除外

使い方:
    python3 lib/breaking_news_selector.py            # 上位5件を stdout + ログ
    python3 lib/breaking_news_selector.py --top 5 --json out.json
"""
import argparse
import html
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNALS = os.path.join(BASE, "data", "trend_signals.jsonl")
ARTICLE_INDEX = os.path.join(BASE, "logs", "article_index.json")
BREAKING_DRAFTS = os.path.join(BASE, "reports", "breaking_drafts")
LOG = os.path.join(BASE, "logs", "breaking_selector.log")

URGENCY_WEIGHT = {"high": 3.0, "normal": 0.0}


def _log(msg):
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_signals(path=SIGNALS):
    sigs = []
    if not os.path.exists(path):
        return sigs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sigs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sigs


def _soompi_id(url):
    """soompi記事URLから安定IDを抽出。/article/<digits>wpp/... → '<digits>'。
    EN signal title ⇄ JA 公開title の照合不能を回避する確実な dedup キー。"""
    m = re.search(r"/article/(\d+)", url or "")
    return m.group(1) if m else ""


def _source_id(url):
    """全ソース対応の安定ID抽出 (2026-05-30: soompi以外もカバー)。
    soompi /article/<digits>, osen /article/<id>, allkpop /article/.../<slug> 等。
    soompi記事IDがあればそれを優先(従来互換)、無ければ host+末尾パスをキー化。
    別ソースでも同一記事を取りこぼさないための補助キー。"""
    if not url:
        return ""
    sid = _soompi_id(url)
    if sid:
        return f"soompi:{sid}"
    m = re.search(r"https?://(?:www\.)?([^/]+)/.*?([A-Za-z0-9_-]{4,})/?$", url)
    if m:
        host = m.group(1).split(".")[0]
        return f"{host}:{m.group(2)}".lower()
    return ""


def load_published(with_topic=False):
    """既出記事の (正規化タイトル集合, 既出 source_id集合) を返す。

    タイトルは EN signal ⇄ JA 公開title で一致しないため、主キーは
    速報draft meta(reports/breaking_drafts/*.meta.json)の source_url から
    取り出した source_id とする。article_index のタイトルは補助。

    with_topic=True のとき、3要素目に「アーティスト+トピック」キー集合を返す
    (2026-05-30: 別ソースの同一事案 dedup 用)。既存呼び出し互換のため既定 False。
    """
    titles, src_ids, topic_keys = set(), set(), set()
    # 補助: article_index の JA タイトル(JA signal が来た場合のみ効く)
    if os.path.exists(ARTICLE_INDEX):
        try:
            data = json.load(open(ARTICLE_INDEX, encoding="utf-8"))
            for a in data.get("articles", []):
                raw = a.get("title", "")
                t = _norm(raw)
                if t:
                    titles.add(t)
                tk = _topic_key(raw)
                if tk:
                    topic_keys.add(tk)
                # 公開済み記事のURLも source_id 集合へ(本体記事も既出扱い)
                gid = _source_id(a.get("url", ""))
                if gid:
                    src_ids.add(gid)
        except (json.JSONDecodeError, OSError):
            pass
    # 主キー: 速報draft meta の source_url → source_id(既に記事化済み)
    if os.path.isdir(BREAKING_DRAFTS):
        for fn in os.listdir(BREAKING_DRAFTS):
            if not fn.endswith(".meta.json"):
                continue
            try:
                meta = json.load(open(os.path.join(BREAKING_DRAFTS, fn), encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            url = meta.get("source_url", "")
            sid = _soompi_id(url)
            if sid:
                src_ids.add(sid)
            gid = _source_id(url)
            if gid:
                src_ids.add(gid)
            tk = _topic_key(meta.get("title", "") or meta.get("ja_title", ""))
            if tk:
                topic_keys.add(tk)
    if with_topic:
        return titles, src_ids, topic_keys
    return titles, src_ids


def _norm(s):
    """タイトル照合用の正規化: HTMLエンティティ解除・記号除去・小文字化。"""
    s = html.unescape(s or "")
    s = re.sub(r"[\s　【】\[\]｜|・,.!?\"'’“”—\-]+", "", s)
    return s.lower()


# 2026-05-30: 同一事案が別ソース(soompi/osen/allkpop等)で来た場合の取りこぼし対策。
# タイトルから「アーティスト名 + トピック語」の組を抽出して dedup 補助キーにする。
# 完全一致主義(誤検知回避)を維持しつつ、ソース非依存で同一事案を捉える。
# トピック語 → 正規化カテゴリ。同義の表記揺れ(活動再開/復帰 等)を同一カテゴリに寄せ、
# 別ソース・別表記でも同一事案を捉える。各カテゴリの語はいずれか1つ含めば該当。
_TOPIC_GROUPS = {
    "return": ("活動再開", "復帰", "活動復帰", "カムバック", "comeback", "活動を再開"),
    "hiatus": ("活動休止", "活動中断", "活動停止", "一時中断"),
    "leave": ("脱退", "卒業", "解散", "契約終了", "契約満了"),
    "military": ("入隊", "除隊", "兵役"),
    "dating": ("熱愛", "交際"),
    "marriage": ("結婚", "入籍"),
    "rename": ("改名",),
    "win": ("1位", "受賞", "優勝"),
    "death": ("死去", "逝去", "訃報"),
    "legal": ("逮捕", "起訴", "書類送検"),
    "apology": ("謝罪", "炎上", "物議"),
}


def _topic_key(title):
    """タイトルから (アーティスト名 + トピックカテゴリ) の正規化キーを作る。
    別ソース・別表記でも同一事案なら一致するよう、トピックは同義語をカテゴリに寄せる。
    抽出できない場合は空文字(=この補助キーでは判定しない)。"""
    t = html.unescape(title or "")
    tl = t.lower()
    cats = sorted({cat for cat, words in _TOPIC_GROUPS.items()
                   if any(w.lower() in tl for w in words)})
    if not cats:
        return ""
    # アーティスト名候補: ラテン文字連続 or カタカナ連続(2文字以上)
    names = re.findall(r"[A-Za-z][A-Za-z0-9&.\- ]{1,}|[ァ-ヶー]{2,}", t)
    # トピック語自身(カムバック/comeback等)を名前候補から除外。
    # 除外しないと「アイブがカムバック」で main が"カムバック"になり、
    # 別グループ(エスパがカムバック)と同一キー化して誤って重複排除される。
    _topic_norms = {_norm(w) for words in _TOPIC_GROUPS.values() for w in words}
    names = [_norm(n) for n in names if len(_norm(n)) >= 2 and _norm(n) not in _topic_norms]
    # アーティスト名が特定できなければ判定しない(別グループ誤排除を防ぐ安全側)。
    if not names:
        return ""
    # 最長の固有名 + トピックカテゴリ(ソート)で安定キー化
    main = sorted(names, key=len, reverse=True)[0]
    return main + "|" + "|".join(cats)


def is_duplicate(sig, pub_titles, pub_src_ids, seen_ids,
                 pub_topic_keys=None, seen_topic_keys=None):
    url = (sig.get("url") or "").rstrip("/")
    sid = _soompi_id(url)
    # 主キー: soompi記事ID(EN/JA タイトル不一致を回避)
    if sid and sid in seen_ids:
        return True, "同一バッチ内ID重複"
    if sid and sid in pub_src_ids:
        return True, "既出(soompi記事ID一致)"
    # 補助キー1: 全ソース対応の source_id (osen/allkpop等)
    gid = _source_id(url)
    if gid and seen_ids is not None and gid in seen_ids:
        return True, "同一バッチ内source_id重複"
    if gid and gid in pub_src_ids:
        return True, "既出(source_id一致)"
    title_norm = _norm(sig.get("title", ""))
    # 補助キー2: 既出タイトル完全一致(JA signal のときのみ効く)
    if title_norm and title_norm in pub_titles:
        return True, "既出タイトル一致"
    # 補助キー3: アーティスト+トピック (別ソースの同一事案を捉える)
    tkey = _topic_key(sig.get("title", ""))
    if tkey and seen_topic_keys is not None and tkey in seen_topic_keys:
        return True, "同一バッチ内トピック重複"
    if tkey and pub_topic_keys and tkey in pub_topic_keys:
        return True, "既出(アーティスト+トピック一致)"
    return False, ""


def score_signals(sigs):
    """候補に複合スコアを付与。engagement は候補集合内で min-max 正規化。"""
    if not sigs:
        return []
    eng = [float(s.get("engagement_score") or 0) for s in sigs]
    lo, hi = min(eng), max(eng)
    span = (hi - lo) or 1.0  # 全部同値なら正規化は0扱い

    scored = []
    for s in sigs:
        e = float(s.get("engagement_score") or 0)
        eng_norm = (e - lo) / span * 3.0
        uw = URGENCY_WEIGHT.get(str(s.get("urgency", "normal")), 0.0)
        total = uw + eng_norm
        scored.append({
            "title": html.unescape(s.get("title", "")),
            "url": s.get("url", ""),
            "source_id": s.get("source_id", ""),
            "keyword": s.get("keyword", ""),
            "urgency": s.get("urgency", "normal"),
            "engagement_score": e,
            "score_breakdown": {
                "urgency_weight": round(uw, 3),
                "engagement_norm": round(eng_norm, 3),
                "total": round(total, 3),
            },
            "_total": total,
            "_eng": e,
        })
    # 複合スコア降順 → 同点は engagement 生値降順
    scored.sort(key=lambda x: (x["_total"], x["_eng"]), reverse=True)
    return scored


def select(top=5, high_only=False):
    sigs = load_signals()
    _log(f"signal 読込: {len(sigs)}件")
    if high_only:
        before = len(sigs)
        sigs = [s for s in sigs if str(s.get("urgency")) == "high"]
        _log(f"high-only フィルタ: {before} → {len(sigs)}件 "
             f"(engagement_score が urgency と完全相関のため、速報は質重視で high のみ採用)")
    pub_titles, pub_src_ids, pub_topic_keys = load_published(with_topic=True)
    _log(f"既出照合元: title {len(pub_titles)} / source_id {len(pub_src_ids)} "
         f"/ topic_key {len(pub_topic_keys)}")

    # 既出除外(主キー=source_id / 補助=タイトル・アーティスト+トピック)
    seen_ids, seen_topic_keys = set(), set()
    candidates, excluded = [], []
    for s in sigs:
        dup, reason = is_duplicate(s, pub_titles, pub_src_ids, seen_ids,
                                   pub_topic_keys, seen_topic_keys)
        if dup:
            excluded.append((s.get("title", "")[:50], reason))
            continue
        url = (s.get("url") or "").rstrip("/")
        sid = _soompi_id(url)
        if sid:
            seen_ids.add(sid)
        gid = _source_id(url)
        if gid:
            seen_ids.add(gid)
        tk = _topic_key(s.get("title", ""))
        if tk:
            seen_topic_keys.add(tk)
        candidates.append(s)
    _log(f"既出/重複除外: {len(excluded)}件 → 候補 {len(candidates)}件")
    for t, r in excluded:
        _log(f"  除外[{r}]: {t}")

    scored = score_signals(candidates)
    picked = scored[:top]

    _log(f"=== 速報候補 上位{len(picked)}件 (複合スコア) ===")
    for i, c in enumerate(picked, 1):
        b = c["score_breakdown"]
        _log(f"  #{i} score={b['total']} (urgency+{b['urgency_weight']} / eng+{b['engagement_norm']}) "
             f"[{c['urgency']}] {c['title'][:55]}")

    # 内部キーを落として返す
    for c in picked:
        c.pop("_total", None)
        c.pop("_eng", None)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="抽出件数")
    ap.add_argument("--high-only", action="store_true",
                    help="urgency=high のみ採用(速報は質重視)")
    ap.add_argument("--json", help="候補を JSON ファイルに保存")
    args = ap.parse_args()

    picked = select(top=args.top, high_only=args.high_only)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(picked, f, ensure_ascii=False, indent=2)
        _log(f"候補を保存: {args.json}")

    if not picked:
        _log("⚠️ 候補0件")
        sys.exit(0)


if __name__ == "__main__":
    main()
