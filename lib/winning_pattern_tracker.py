#!/usr/bin/env python3
"""
winning_pattern_tracker.py — 勝ちパターン学習ログ記録

Usage:
  python3 lib/winning_pattern_tracker.py           # kpi_posts.jsonl全件処理
  python3 lib/winning_pattern_tracker.py --post-id 2555  # 特定記事のみ

出力: logs/winning_patterns.jsonl
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
JST = timezone(timedelta(hours=9))

ARTIST_RE = re.compile(
    r'BTS|BLACKPINK|BIGBANG|aespa|BABYMONSTER|ILLIT|IVE|SEVENTEEN|TWICE|'
    r'Stray\s*Kids|NewJeans|LE\s*SSERAFIM|NCT|RIIZE|PLAVE|TXT|ENHYPEN|'
    r'ITZY|NMIXX|RED\s*VELVET|EXO|SHINee|G-DRAGON|ZEROBASEONE|'
    r'ATEEZ|GOT7|MAMAMOO|JIMIN|ジミン|ジョングク|テヒョン|TOP',
    re.IGNORECASE
)
EMOTION_RE = re.compile(
    r'衝撃|異常|ついに|判明|速報|まさか|爆発|炎上|暴露|激白|騒然|完全|神|伝説|'
    r'歴史的|奇跡|待望|号泣|鳥肌|やばい|ヤバい|バグ|尊い|真相|解禁|初公開|大反響|'
    r'復帰|制覇|快挙|1位|首位|電撃'
)
CONTRAST_RE = re.compile(
    r'→|vs|VS|から|でも|なのに|なぜ|なのか|空白|一転|激変|崩壊|異常|[0-9]+年ぶり|'
    r'急落|急騰|脱退|解散|復帰'
)

def _load_jsonl(path):
    if not Path(path).exists():
        return []
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    return recs

def _now_jst():
    return datetime.now(JST).isoformat()

def extract_features(title: str, thumb_text: str = "", x_hook: str = "") -> dict:
    """タイトル・サムネ・Xフックから特徴量を抽出"""
    combined = f"{title} {thumb_text} {x_hook}"
    return {
        "has_number":      bool(re.search(r'[0-9]', combined)),
        "has_proper_noun": bool(ARTIST_RE.search(combined)),
        "has_emotion_word": bool(EMOTION_RE.search(combined)),
        "has_contrast":    bool(CONTRAST_RE.search(combined)),
        "title_length":    len(title),
    }

def score_thumb(text: str) -> int:
    """score_thumbnail_text.py を呼ばずにインライン採点（依存なし）"""
    if not text:
        return 0
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return 0
    score = 0
    combined = " ".join(lines)
    if re.search(r'[0-9]', combined):         score += 25
    if ARTIST_RE.search(combined):             score += 25
    if CONTRAST_RE.search(combined):           score += 20
    if EMOTION_RE.search(combined):            score += 15
    if len(lines) == 2 and all(len(l) <= 15 for l in lines):
        score += 15
    return min(score, 100)

def score_x_hook(text: str) -> int:
    """Xフックスコア（インライン版）"""
    if not text:
        return 0
    lines = [l for l in text.strip().split('\n')
             if l.strip() and not l.strip().startswith('#')
             and not re.match(r'https?://', l.strip())]
    body = '\n'.join(lines)
    score = 0
    if re.search(r'[0-9]', body):             score += 25
    if ARTIST_RE.search(body):                 score += 25
    if EMOTION_RE.search(body):                score += 20
    if CONTRAST_RE.search(body):               score += 20
    total_len = len(text.strip())
    if 120 <= total_len <= 150:                score += 10
    return min(score, 100)

def infer_category(categories: list, title: str) -> str:
    """カテゴリIDとタイトルからジャンル文字列を推定"""
    cat_map = {
        71: "chart", 3: "comeback", 6: "comeback",
        12: "beauty", 11: "travel", 5: "live", 30: "fashion",
        7: "breaking", 4: "analysis", 14: "rumor",
        111: "guide", 112: "profile", 113: "guide",
    }
    for cid in (categories or []):
        g = cat_map.get(int(cid) if str(cid).isdigit() else 0)
        if g:
            return g
    title_l = title.lower()
    if any(w in title_l for w in ['チャート','ランキング','1位','billboard']): return "chart"
    if any(w in title_l for w in ['カムバック','新曲','mv']): return "comeback"
    if any(w in title_l for w in ['コスメ','スキンケア','美容']): return "beauty"
    if any(w in title_l for w in ['速報','緊急','炎上','騒動']): return "breaking"
    if any(w in title_l for w in ['ライブ','コンサート','ツアー']): return "live"
    if any(w in title_l for w in ['入門','ガイド','始め方']): return "guide"
    if any(w in title_l for w in ['プロフィール','メンバー']): return "profile"
    return "other"

def build_pattern(rec: dict, gsc_recs: list, x_recs: list) -> dict:
    """KPIレコードから1パターンエントリを構築"""
    post_id = str(rec.get("post_id", ""))
    title   = rec.get("title", "")
    url     = rec.get("url", "")
    slug    = rec.get("slug", "")
    cats    = rec.get("categories", [])
    pub_ts  = rec.get("timestamp", "")
    has_thumb = rec.get("has_thumbnail", False)

    # 公開時刻
    pub_hour = None
    try:
        dt = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
        pub_hour = dt.hour
    except Exception:
        pass

    # GSC状態
    gsc_map = {str(g.get("post_id","")): g for g in gsc_recs}
    gsc_entry = gsc_map.get(post_id, {})
    indexed_status = "unknown"
    if gsc_entry.get("p1_alert"):      indexed_status = "unindexed_p1"
    elif gsc_entry.get("resubmit_flag"): indexed_status = "unindexed_48h"
    elif gsc_entry.get("status") in ("indexed", "PASS"): indexed_status = "indexed"

    # X投稿状態
    x_map = {str(x.get("post_id","")): x for x in x_recs}
    x_entry = x_map.get(post_id, {})
    x_posted = bool(x_entry) and x_entry.get("status") not in ("", "SKIP", "BLOCKED_HOOK_CTR", "BLOCKED_QUALITY")
    x_hook_score = x_entry.get("hook_score", x_entry.get("score", 0))
    x_hook_text  = x_entry.get("tweet_text", x_entry.get("hook", ""))

    # 特徴量
    feats = extract_features(title)
    thumb_score  = score_thumb(rec.get("thumb_title", ""))
    if thumb_score == 0 and has_thumb:
        thumb_score = 50  # サムネあるが文言不明→中立

    category = infer_category(cats, title)

    # 評価値（現時点スコアを記録; 時系列更新は post_publish_evaluator が担当）
    pattern = {
        "post_id":        post_id,
        "title":          title,
        "url":            url,
        "slug":           slug,
        "category":       category,
        "article_type":   rec.get("article_type", "unknown"),
        "publish_hour":   pub_hour,
        "has_thumbnail":  has_thumb,

        # 特徴量
        "has_number":      feats["has_number"],
        "has_proper_noun": feats["has_proper_noun"],
        "has_emotion_word":feats["has_emotion_word"],
        "has_contrast":    feats["has_contrast"],
        "title_length":    feats["title_length"],

        # スコア
        "thumbnail_score": thumb_score,
        "x_hook_score":    x_hook_score,

        # 状態
        "indexed_status":  indexed_status,
        "x_posted_status": "posted" if x_posted else "not_posted",

        # メタ
        "recorded_at":    _now_jst(),
        "eval_24h":  None,
        "eval_48h":  None,
        "eval_72h":  None,
    }
    return pattern

def run(post_id_filter=None):
    kpi_path  = LOGS / "kpi_posts.jsonl"
    gsc_path  = LOGS / "gsc_tracking.json"
    x_path    = LOGS / "x_post_results.jsonl"
    out_path  = LOGS / "winning_patterns.jsonl"

    kpi_recs = _load_jsonl(kpi_path)
    gsc_recs = []
    if gsc_path.exists():
        try:
            gsc_recs = json.loads(gsc_path.read_text(encoding="utf-8"))
            if isinstance(gsc_recs, dict):
                gsc_recs = gsc_recs.get("entries", [])
        except Exception:
            pass
    x_recs = _load_jsonl(x_path)

    # 既存パターンのpost_idセット（重複スキップ）
    existing_ids = set()
    if out_path.exists():
        for r in _load_jsonl(out_path):
            existing_ids.add(str(r.get("post_id","")))

    written = 0
    skipped = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for rec in kpi_recs:
            if rec.get("event") != "post_published":
                continue
            pid = str(rec.get("post_id",""))
            if not pid:
                continue
            if post_id_filter and pid != str(post_id_filter):
                continue
            if pid in existing_ids:
                skipped += 1
                continue
            pattern = build_pattern(rec, gsc_recs, x_recs)
            f.write(json.dumps(pattern, ensure_ascii=False) + "\n")
            existing_ids.add(pid)
            written += 1

    print(json.dumps({
        "status": "ok",
        "written": written,
        "skipped": skipped,
        "output": str(out_path),
    }, ensure_ascii=False))

if __name__ == "__main__":
    pid = None
    if "--post-id" in sys.argv:
        idx = sys.argv.index("--post-id")
        pid = sys.argv[idx+1] if idx+1 < len(sys.argv) else None
    run(pid)
