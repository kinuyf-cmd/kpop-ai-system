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


def load_published():
    """既出記事の (正規化タイトル集合, 既出 soompi記事ID集合) を返す。

    タイトルは EN signal ⇄ JA 公開title で一致しないため、主キーは
    速報draft meta(reports/breaking_drafts/*.meta.json)の source_url から
    取り出した soompi記事IDとする。article_index のタイトルは補助。
    """
    titles, src_ids = set(), set()
    # 補助: article_index の JA タイトル(JA signal が来た場合のみ効く)
    if os.path.exists(ARTICLE_INDEX):
        try:
            data = json.load(open(ARTICLE_INDEX, encoding="utf-8"))
            for a in data.get("articles", []):
                t = _norm(a.get("title", ""))
                if t:
                    titles.add(t)
        except (json.JSONDecodeError, OSError):
            pass
    # 主キー: 速報draft meta の source_url → soompi記事ID(既に記事化済み)
    if os.path.isdir(BREAKING_DRAFTS):
        for fn in os.listdir(BREAKING_DRAFTS):
            if not fn.endswith(".meta.json"):
                continue
            try:
                meta = json.load(open(os.path.join(BREAKING_DRAFTS, fn), encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sid = _soompi_id(meta.get("source_url", ""))
            if sid:
                src_ids.add(sid)
    return titles, src_ids


def _norm(s):
    """タイトル照合用の正規化: HTMLエンティティ解除・記号除去・小文字化。"""
    s = html.unescape(s or "")
    s = re.sub(r"[\s　【】\[\]｜|・,.!?\"'’“”—\-]+", "", s)
    return s.lower()


def is_duplicate(sig, pub_titles, pub_src_ids, seen_ids):
    url = (sig.get("url") or "").rstrip("/")
    sid = _soompi_id(url)
    # 主キー: soompi記事ID(EN/JA タイトル不一致を回避)
    if sid and sid in seen_ids:
        return True, "同一バッチ内ID重複"
    if sid and sid in pub_src_ids:
        return True, "既出(soompi記事ID一致)"
    title_norm = _norm(sig.get("title", ""))
    # 補助: 既出タイトル完全一致(JA signal のときのみ効く。部分一致は誤検知多く不使用)
    if title_norm and title_norm in pub_titles:
        return True, "既出タイトル一致"
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
    pub_titles, pub_src_ids = load_published()
    _log(f"既出照合元: title {len(pub_titles)} / soompi記事ID {len(pub_src_ids)}")

    # 既出除外(主キー=soompi記事ID)
    seen_ids = set()
    candidates, excluded = [], []
    for s in sigs:
        dup, reason = is_duplicate(s, pub_titles, pub_src_ids, seen_ids)
        if dup:
            excluded.append((s.get("title", "")[:50], reason))
            continue
        sid = _soompi_id((s.get("url") or "").rstrip("/"))
        if sid:
            seen_ids.add(sid)
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
