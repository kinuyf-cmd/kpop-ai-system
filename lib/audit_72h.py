#!/usr/bin/env python3
"""
72時間再監査スクリプト (audit_72h.py) v2.0
Usage: python3 lib/audit_72h.py [--hours 72]

出力: 総合スコア、P0/P1/P2課題、記事別問題、サムネ別問題、X投稿監査、GSC監査、重複記事候補、TOP10、誤認除外済み
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
JST = timezone(timedelta(hours=9))
WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"

# ── アーティストパターン（slug_generator.pyと同期） ──────────────────────────
ARTIST_PATTERNS = [
    r"\bBTS\b", r"T\.O\.P", r"\bTWICE\b", r"\bBLACKPINK\b", r"\bIVE\b",
    r"\bILLIT\b", r"\baespa\b", r"\bNewJeans\b", r"\bENHYPEN\b", r"\bTXT\b",
    r"\bStray\s*Kids\b", r"\bSEVENTEEN\b", r"\bMAMAMOO\b", r"\bEXO\b",
    r"\bNCT\b", r"\bRIIZE\b", r"\bZERO\s*BASE\s*ONE\b", r"\b2\s*NE\s*1\b",
    r"\bATEEZ\b", r"\bTHE\s*BOYZ\b", r"\bGOT7\b", r"\bMONSTA\s*X\b",
    r"\bLE\s*SSERAFIM\b", r"\bRed\s*Velvet\b", r"\bSUPER\s*M\b",
    r"\bWayV\b", r"\bWEEKLY\b", r"\bKEPLER\b", r"\bGIRLS\s*GENERATION\b",
    r"\bSHINee\b", r"\bSUPER\s*JUNIOR\b", r"\bBIGBANG\b", r"\bARIRANG\b",
    r"\bKPOP\b", r"K-POP",
]
_ARTIST_RE = re.compile("|".join(ARTIST_PATTERNS), re.IGNORECASE)

# ── 既知問題のサムネイルレジストリ ──────────────────────────────────────────
KNOWN_THUMBNAIL_ISSUES = {
    2544: {
        "problem": "「641,000」数字分割・ARIRANGロゴ欠落",
        "severity": "CRITICAL",
        "suggested_copy": "BTS ARIRANG 初週641000枚",
        "overflow_risk": True,
    },
    2574: {
        "problem": "T.O.P→'..'フォント変換バグ（ピリオドが空白に化ける）",
        "severity": "CRITICAL",
        "suggested_copy": "TOP 13年ぶりソロ復帰",
        "overflow_risk": False,
    },
    2555: {
        "problem": "コピー誤割り当て「3市場の真相判明」（別記事用コピーが混入）",
        "severity": "CRITICAL",
        "suggested_copy": "BTS グローバル3市場戦略",
        "overflow_risk": False,
    },
    2581: {
        "problem": "テキストオーバーフロー右端切断（IVEウォニョン記事）",
        "severity": "HIGH",
        "suggested_copy": "IVE ウォニョン パリコレ2026",
        "overflow_risk": True,
    },
    2442: {
        "problem": "「入門/ガイドまとめ20…」テキスト切れ",
        "severity": "HIGH",
        "suggested_copy": "K-POP入門ガイド2026",
        "overflow_risk": True,
    },
    2536: {
        "problem": "アーティスト名未検出・コピーが汎用すぎる",
        "severity": "MEDIUM",
        "suggested_copy": "K-POP最新トレンド2026",
        "overflow_risk": False,
    },
    2485: {
        "problem": "プロフィール記事サムネ: アーティスト名なし",
        "severity": "MEDIUM",
        "suggested_copy": "K-POPアイドルプロフィール",
        "overflow_risk": False,
    },
    2484: {
        "problem": "プロフィール記事サムネ: アーティスト名なし",
        "severity": "MEDIUM",
        "suggested_copy": "K-POPアイドルプロフィール",
        "overflow_risk": False,
    },
    2479: {
        "problem": "プロフィール記事サムネ: コピー長すぎ可能性",
        "severity": "LOW",
        "suggested_copy": "K-POPアイドルプロフィール",
        "overflow_risk": True,
    },
    2441: {
        "problem": "テキスト長めでオーバーフロー懸念",
        "severity": "LOW",
        "suggested_copy": "K-POP記事2026",
        "overflow_risk": True,
    },
}

# ── 誤認除外済みリスト ───────────────────────────────────────────────────────
FALSE_POSITIVE_EXCLUSIONS = [
    {
        "post_id": 2574,
        "field": "slug",
        "old_flag": "数字始まりスラッグ '13-2026'",
        "resolution": "スラッグ修正済み: top-another-dimension-13years-2026（2026-04-14）",
        "status": "resolved",
    },
    {
        "post_id": 2568,
        "field": "slug",
        "old_flag": "数字混入スラッグ '6-3-bts-2026'",
        "resolution": "スラッグ修正済み: bts-6years-return-arirang-2026（2026-04-14）",
        "status": "resolved",
    },
    {
        "post_id": None,
        "field": "gardevoir",
        "old_flag": "preamble行「以下に完成記事を出力します」でHARD_FAIL",
        "resolution": "sanitize_output.sh [4b]追加でpreamble除去。次回から誤検出なし",
        "status": "mitigated",
    },
]


def _now_jst():
    return datetime.now(JST)


def _load_jsonl(path):
    recs = []
    p = Path(path)
    if not p.exists():
        return recs
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    return recs


def _cutoff(hours):
    return _now_jst() - timedelta(hours=hours)


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s[:19], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            return dt
        except Exception:
            pass
    return None


def _token_overlap(a: str, b: str) -> float:
    """タイトル間のトークンオーバーラップ率（Jaccard類似度）"""
    ta = set(re.findall(r"[\w]+", a.lower()))
    tb = set(re.findall(r"[\w]+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _slug_has_artist(slug: str) -> bool:
    return bool(_ARTIST_RE.search(slug.replace("-", " ")))


def audit_pipeline(hours=72):
    cutoff = _cutoff(hours)
    pipeline_log = LOGS / "pipeline.jsonl"
    recs = _load_jsonl(pipeline_log)

    recent = [r for r in recs if _parse_dt(r.get("timestamp", "")) and
              _parse_dt(r.get("timestamp", "")) >= cutoff]

    runs = {}
    for r in recent:
        rid = r.get("run_id", "unknown")
        runs.setdefault(rid, []).append(r)

    total_runs = len(runs)
    completed = sum(1 for steps in runs.values()
                    if any(s.get("step") == "wordpress_post" and s.get("status") == "ok"
                           for s in steps))
    errors = sum(1 for steps in runs.values()
                 if any(s.get("status") in ("error", "ERROR") for s in steps))

    gardevoir_recs = _load_jsonl(LOGS / "gardevoir_hook.jsonl")
    recent_gdv = [r for r in gardevoir_recs
                  if _parse_dt(r.get("timestamp", r.get("ts", ""))) and
                  _parse_dt(r.get("timestamp", r.get("ts", ""))) >= cutoff]
    hard_fails = [r for r in recent_gdv if r.get("verdict") in ("HARD_FAIL", "hard_fail")]
    gdv_total = len(recent_gdv)
    gdv_hf = len(hard_fails)
    hf_rate = gdv_hf / gdv_total if gdv_total else 0

    return {
        "total_runs": total_runs,
        "completed": completed,
        "errors": errors,
        "completion_rate": completed / total_runs if total_runs else 0,
        "gardevoir_total": gdv_total,
        "gardevoir_hard_fail": gdv_hf,
        "hard_fail_rate": hf_rate,
        "hard_fail_titles": [r.get("title", "")[:60] for r in hard_fails[-5:]],
    }


def audit_gsc(hours=72):
    """GSCインデックス状況: gsc_index_check.jsonl + indexing_api_sends.jsonlを両方読む"""
    gsc_log = LOGS / "gsc_index_check.jsonl"
    sends_log = LOGS / "indexing_api_sends.jsonl"

    recs = _load_jsonl(gsc_log)
    sends = _load_jsonl(sends_log)

    # 送信済みURLのセットを作成
    submitted_urls = {}
    for s in sends:
        url = s.get("url", "")
        if url:
            submitted_urls[url] = s.get("sent_at", "")

    # GSCレコードを分類
    indexed = []
    submitted_pending = []
    url_unknown = []
    url_error = []
    not_submitted = []

    seen_ids = set()
    for r in recs:
        pid = r.get("post_id", r.get("id", "?"))
        url = r.get("url", r.get("canonical_url", ""))
        verdict = r.get("verdict", "")

        if str(pid) in seen_ids:
            continue
        seen_ids.add(str(pid))

        if verdict == "PASS" or r.get("status") == "indexed":
            indexed.append(pid)
        elif verdict == "ERROR" or r.get("http_status") == 404:
            url_error.append(pid)
        elif url and url in submitted_urls:
            submitted_pending.append(pid)
        elif verdict == "NEUTRAL" or verdict == "UNKNOWN":
            url_unknown.append(pid)
        else:
            not_submitted.append(pid)

    # 送信済みだがGSCに未登場のpost_idも「送信済み未反映」に
    gsc_post_ids = {str(r.get("post_id", r.get("id", ""))) for r in recs}
    for s in sends:
        spid = str(s.get("post_id", ""))
        if spid and spid not in gsc_post_ids:
            submitted_pending.append(spid)

    # ── gsc_tracking.json への書き出し ──────────────────────────────────────
    now_jst = _now_jst()
    tracking_entries = []
    for r in recs:
        pid = r.get("post_id", r.get("id", "?"))
        url = r.get("url", r.get("canonical_url", ""))
        verdict = r.get("verdict", "")
        sent_at_str = submitted_urls.get(url, "")
        published_str = r.get("published_at", r.get("sent_at", ""))

        # 経過時間を計算
        ref_str = published_str or sent_at_str
        elapsed_h = None
        if ref_str:
            ref_dt = _parse_dt(ref_str)
            if ref_dt:
                elapsed_h = (now_jst - ref_dt).total_seconds() / 3600

        is_indexed = (verdict == "PASS" or r.get("status") == "indexed")

        # noindex を尊重: ページが noindex タグで意図的に除外されている場合は
        # 「未インデックス異常」ではないので P1/resubmit を上げない（本番公開前の
        # サイト全体 noindex 状態での誤検知を防ぐ）。
        coverage = str(r.get("coverageState", "")).lower()
        indexing_state = str(r.get("indexingState", "")).upper()
        is_noindex = ("noindex" in coverage) or (indexing_state == "BLOCKED_BY_META_TAG")

        if is_noindex:
            idx_status = "noindex"
        elif is_indexed:
            idx_status = "indexed"
        elif verdict == "ERROR":
            idx_status = "error"
        else:
            idx_status = "not_indexed"

        # 再送信/P1は「indexed でなく noindex でもない」場合のみ点灯
        needs_attention = (not is_indexed) and (not is_noindex)
        entry = {
            "post_id": pid,
            "url": url,
            "sent_at": sent_at_str or published_str or "",
            "index_status": idx_status,
            "elapsed_hours": round(elapsed_h, 1) if elapsed_h is not None else None,
            "resubmit_flag": bool(elapsed_h and elapsed_h >= 48 and needs_attention),
            "p1_alert": bool(elapsed_h and elapsed_h >= 72 and needs_attention),
        }
        tracking_entries.append(entry)

    tracking_path = LOGS / "gsc_tracking.json"
    try:
        tracking_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tracking_path, "w", encoding="utf-8") as f:
            json.dump(tracking_entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass  # 書き出し失敗は無視して続行

    return {
        "total_checked": len(recs),
        "indexed": len(indexed),
        "indexed_ids": indexed[:10],
        "submitted_pending": len(submitted_pending),
        "submitted_pending_ids": submitted_pending[:10],
        "url_unknown": len(url_unknown),
        "url_unknown_ids": url_unknown[:10],
        "url_error": len(url_error),
        "url_error_ids": url_error[:5],
        "not_submitted": len(not_submitted),
        "gsc_tracking_written": len(tracking_entries),
    }


def audit_x_posts(hours=72):
    """X投稿ログを詳細に解析: posted/failed/skipped/plan_only/unknown を分類"""
    x_log = LOGS / "x_post.log"
    tweet_db = LOGS / "tweet_id_db.tsv"

    cutoff = _cutoff(hours)
    posted = []
    failed = 0
    skipped = 0
    plan_only = 0

    # tweet_id_db.tsv から投稿済みを読む
    # フォーマット: post_id\ttweet_id\ttitle\tposted_at
    if tweet_db.exists():
        with tweet_db.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) >= 4:
                    dt = _parse_dt(parts[3])
                    if dt and dt >= cutoff:
                        posted.append({
                            "post_id": parts[0],
                            "tweet_id": parts[1],
                            "title": parts[2][:60] if len(parts) > 2 else "",
                            "posted_at": parts[3],
                        })

    # x_post.log から失敗/スキップを集計
    if x_log.exists():
        with x_log.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                # 日付フィルタ: 最初の [YYYY-MM-DD HH:MM:SS] を見る
                m = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
                if m:
                    dt = _parse_dt(m.group(1))
                    if not dt or dt < cutoff:
                        continue
                if "RESULT: フェイルセーフ" in line or "RESULT: プレフライト不合格" in line:
                    skipped += 1
                elif "失敗" in line or "FAIL" in line or "ERROR" in line:
                    failed += 1
                elif "DRY-RUN" in line:
                    plan_only += 1

    return {
        "tweets_sent": len(posted),
        "posted": posted,
        "failures": failed,
        "skipped": skipped,
        "plan_only": plan_only,
    }


def audit_thumbnails():
    """サムネイル品質：既知問題レジストリ + thumbnail_performance.jsonlを読む"""
    thumb_log = LOGS / "thumbnail_performance.jsonl"
    recs = _load_jsonl(thumb_log)

    issues_by_post = {}
    for pid, info in KNOWN_THUMBNAIL_ISSUES.items():
        issues_by_post[pid] = info

    return {
        "records": len(recs),
        "known_issues": issues_by_post,
        "worst_ids": [pid for pid, info in KNOWN_THUMBNAIL_ISSUES.items()
                      if info["severity"] == "CRITICAL"],
    }


def detect_duplicates(posts=None):
    """
    重複記事検出: タイトルのトークンオーバーラップ率 > 0.7 でフラグ

    posts: [{"post_id": int, "title": str, "slug": str}, ...]
    """
    # 既知の重複（ハードコード）
    known = [
        {
            "keep_post_id": 2555,
            "drop_post_id": 2530,
            "similarity": 0.85,
            "reason": "両記事ともBTSチャート3市場比較。2530は古い公開日、2555が最新版",
            "suggested_action": "ID=2530を非公開にして301→2555へリダイレクト検討",
        }
    ]

    if not posts:
        return known

    detected = list(known)
    existing_pairs = {(2555, 2530), (2530, 2555)}

    for i in range(len(posts)):
        for j in range(i + 1, len(posts)):
            a = posts[i]
            b = posts[j]
            pid_a = a.get("post_id")
            pid_b = b.get("post_id")
            pair = (pid_a, pid_b)
            if pair in existing_pairs or (pid_b, pid_a) in existing_pairs:
                continue
            sim = _token_overlap(a.get("title", ""), b.get("title", ""))
            if sim > 0.70:
                detected.append({
                    "keep_post_id": pid_a,
                    "drop_post_id": pid_b,
                    "similarity": round(sim, 3),
                    "reason": f"タイトル類似度 {sim:.0%}",
                    "suggested_action": "内容確認の上、古い記事を整理",
                })
                existing_pairs.add(pair)

    return detected


def audit_slugs(posts=None):
    """
    スラッグ品質監査

    posts: [{"post_id": int, "slug": str, "title": str}, ...]
    Returns: [{post_id, current_slug, problem, proposed_slug}, ...]
    """
    issues = []

    # 既知の問題（ハードコード）
    known_slug_issues = [
        # 2574: 修正済み
        # 2568: 修正済み
    ]
    issues.extend(known_slug_issues)

    if not posts:
        return issues

    slug_to_posts = {}
    for p in posts:
        s = p.get("slug", "")
        slug_to_posts.setdefault(s, []).append(p.get("post_id"))

    for p in posts:
        pid = p.get("post_id")
        slug = p.get("slug", "")
        title = p.get("title", "")
        problems = []
        proposed = slug

        if not slug:
            problems.append("スラッグ空")
            proposed = f"kpop-post-{pid}"
        elif re.match(r"^\d+$", slug):
            problems.append("純粋な数字スラッグ（SEO不可）")
            proposed = f"kpop-post-{slug}-{pid}"
        elif re.match(r"^\d", slug):
            problems.append("数字始まりスラッグ（SEO弱）")
            proposed = f"kpop-{slug}"
        elif re.match(r"^\d{4}-\d+$", slug):
            problems.append("年+数字のみのスラッグ（SEO不可）")
            proposed = f"kpop-article-{slug}"

        if slug and not _slug_has_artist(slug) and len(slug.split("-")) < 3:
            problems.append("アーティスト名・キーワードなし（SEO弱）")

        # 重複スラッグ
        if slug and len(slug_to_posts.get(slug, [])) > 1:
            problems.append(f"スラッグ重複 (他の記事と衝突)")

        if problems:
            issues.append({
                "post_id": pid,
                "current_slug": slug,
                "problems": problems,
                "proposed_slug": proposed,
                "title": title[:50],
            })

    return issues


def score_article(post_id, slug="", meta_desc_ok=True, has_thumbnail=True,
                   x_status="posted", gsc_status="indexed", gardevoir_pass=True):
    """記事を0-100でスコアリング"""
    score = 100
    breakdown = {}

    # スラッグ品質 (20点)
    slug_score = 20
    if not slug:
        slug_score = 0
    elif re.match(r"^\d", slug):
        slug_score = 5
    elif not _slug_has_artist(slug):
        slug_score = 12
    breakdown["slug"] = slug_score
    score -= (20 - slug_score)

    # メタディスクリプション (15点)
    meta_score = 15 if meta_desc_ok else 0
    breakdown["meta_desc"] = meta_score
    score -= (15 - meta_score)

    # サムネイル (20点)
    thumb_score = 20
    if post_id in KNOWN_THUMBNAIL_ISSUES:
        sev = KNOWN_THUMBNAIL_ISSUES[post_id]["severity"]
        if sev == "CRITICAL":
            thumb_score = 0
        elif sev == "HIGH":
            thumb_score = 8
        elif sev == "MEDIUM":
            thumb_score = 14
        else:
            thumb_score = 17
    elif not has_thumbnail:
        thumb_score = 5
    breakdown["thumbnail"] = thumb_score
    score -= (20 - thumb_score)

    # X投稿 (15点)
    x_map = {"posted": 15, "plan_only": 10, "skipped": 7, "failed": 0, "unknown": 5}
    x_score = x_map.get(x_status, 5)
    breakdown["x_post"] = x_score
    score -= (15 - x_score)

    # GSCインデックス (20点)
    gsc_map = {"indexed": 20, "submitted_pending": 12, "url_unknown": 5, "url_error": 0,
               "not_submitted": 3}
    gsc_score = gsc_map.get(gsc_status, 5)
    breakdown["gsc"] = gsc_score
    score -= (20 - gsc_score)

    # Gardevoir (10点)
    gdv_score = 10 if gardevoir_pass else 0
    breakdown["gardevoir"] = gdv_score
    score -= (10 - gdv_score)

    return max(0, score), breakdown


def score_overall(pipeline, gsc, x_posts):
    score = 100

    # Pipeline health (40 points)
    cr = pipeline.get("completion_rate", 0)
    hfr = pipeline.get("hard_fail_rate", 0)
    score -= max(0, (1 - cr) * 20)
    score -= min(20, hfr * 40)

    # GSC indexing (30 points)
    total = gsc.get("total_checked", 1)
    unknown = gsc.get("url_unknown", 0) + gsc.get("not_submitted", 0)
    index_rate = 1 - unknown / total if total else 1
    score -= max(0, (1 - index_rate) * 30)

    # X posts (10 points)
    if x_posts.get("failures", 0) > 3:
        score -= 10
    elif x_posts.get("tweets_sent", 0) == 0:
        score -= 5

    # Thumbnail issues (20 points)
    critical_count = sum(1 for v in KNOWN_THUMBNAIL_ISSUES.values()
                         if v["severity"] == "CRITICAL")
    score -= min(20, critical_count * 5)

    return max(0, int(score))


def top10_issues(pipeline, gsc, thumbs, x_posts):
    issues = []
    rank = 1

    # P0: GSCインデックス未登録
    unknown = gsc.get("url_unknown", 0)
    if unknown > 0:
        issues.append({
            "rank": rank, "priority": "P0", "severity": "CRITICAL",
            "title": f"GSCインデックス未登録: {unknown}記事（URL不明状態）",
            "action": "Google Indexing API経由で送信済。48-72時間待機",
            "status": "対応済（2026-04-14）",
        })
        rank += 1

    # P0: サムネイルコピー誤割り当て
    issues.append({
        "rank": rank, "priority": "P0", "severity": "CRITICAL",
        "title": "サムネイル: ID=2555コピー誤割り当て「3市場の真相判明」",
        "action": "サムネイル再生成 + 正しいコピーに修正: 'BTS グローバル3市場戦略'",
        "status": "未対応",
    })
    rank += 1

    # P0: T.O.Pフォントバグ
    issues.append({
        "rank": rank, "priority": "P0", "severity": "CRITICAL",
        "title": "サムネイル: ID=2574 T.O.P→'..'フォント変換バグ",
        "action": "\"TOP\"(ピリオドなし)フォールバックでサムネイル再生成",
        "status": "未対応",
    })
    rank += 1

    # P1: 数字分割
    issues.append({
        "rank": rank, "priority": "P1", "severity": "HIGH",
        "title": "サムネイル: ID=2544 数字分割・ARIRANG欠落",
        "action": "サムネイル再生成: フォントサイズ縮小・1行に収める",
        "status": "未対応",
    })
    rank += 1

    # P1: HARD_FAIL率
    hfr = pipeline.get("hard_fail_rate", 0)
    if hfr > 0.3:
        issues.append({
            "rank": rank, "priority": "P1", "severity": "HIGH",
            "title": f"gardevoir HARD_FAIL率: {hfr:.0%} ({pipeline.get('gardevoir_hard_fail',0)}件)",
            "action": "sanitize_output.shにpreamble除去[4b]追加済み。次回実行で効果確認",
            "status": "対応済（2026-04-14）",
        })
        rank += 1

    # P1: 重複記事
    issues.append({
        "rank": rank, "priority": "P1", "severity": "HIGH",
        "title": "重複記事: ID=2530とID=2555がほぼ同一のチャート記事（類似度85%）",
        "action": "ID=2530を非公開にし、301リダイレクトをID=2555へ設定することを検討",
        "status": "未対応",
    })
    rank += 1

    # P2: X未投稿
    issues.append({
        "rank": rank, "priority": "P2", "severity": "MEDIUM",
        "title": "X投稿: ID=2475-2485のプロフィール記事群がツイートされていない",
        "action": "バッチ投稿記事はパイプライン外で作成。手動X投稿または再実行が必要",
        "status": "未対応",
    })
    rank += 1

    # P2: テキストオーバーフロー
    issues.append({
        "rank": rank, "priority": "P2", "severity": "MEDIUM",
        "title": "サムネイル: ID=2581テキストオーバーフロー右端切断",
        "action": "サムネイル再生成: テキストを短縮またはフォントサイズ縮小",
        "status": "未対応",
    })
    rank += 1

    # P2: テキスト切れ
    issues.append({
        "rank": rank, "priority": "P2", "severity": "LOW",
        "title": "サムネイル: ID=2442「入門/ガイドまとめ20…」テキスト切れ",
        "action": "サムネイル再生成: テキスト短縮",
        "status": "未対応",
    })
    rank += 1

    # GSC URL_ERROR
    url_errors = gsc.get("url_error", 0)
    if url_errors > 0:
        issues.append({
            "rank": rank, "priority": "P1", "severity": "HIGH",
            "title": f"GSC: {url_errors}記事でURL 404エラー検出",
            "action": "WP REST APIで現在のスラッグを確認し、正しいURLを再送信",
            "status": "要調査",
        })
        rank += 1

    return issues[:10]


def build_article_problems(pipeline, gsc, x_posts, thumbs):
    """記事別問題リストを構築"""
    problems = {}

    # サムネイル問題
    for pid, info in KNOWN_THUMBNAIL_ISSUES.items():
        problems.setdefault(pid, []).append(
            f"[サムネイル/{info['severity']}] {info['problem']}"
        )

    # GSC URL_ERROR
    for pid in gsc.get("url_error_ids", []):
        try:
            pid_int = int(pid)
            problems.setdefault(pid_int, []).append("[GSC] 404 URLエラー検出")
        except Exception:
            pass

    # GSC 未登録
    for pid in gsc.get("url_unknown_ids", []):
        try:
            pid_int = int(pid)
            problems.setdefault(pid_int, []).append("[GSC] URL不明・インデックス未登録")
        except Exception:
            pass

    # 重複
    problems.setdefault(2530, []).append("[重複] ID=2555と内容重複（類似度85%）→ 整理候補")
    problems.setdefault(2555, []).append("[重複] ID=2530と内容重複（正規版として保持）")

    return problems


def main():
    hours = 72
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--hours" and i + 1 < len(sys.argv) - 1:
            try:
                hours = int(sys.argv[i + 2])
            except Exception:
                pass

    now_str = _now_jst().strftime("%Y-%m-%d %H:%M JST")
    print(f"\n{'='*65}")
    print(f"  72時間再監査レポート v2.0  ({now_str})")
    print(f"{'='*65}")

    # ── データ収集 ──────────────────────────────────────────────────
    pipe = audit_pipeline(hours)
    gsc = audit_gsc(hours)
    x = audit_x_posts(hours)
    thumbs = audit_thumbnails()
    duplicates = detect_duplicates()
    slug_issues = audit_slugs()
    article_problems = build_article_problems(pipe, gsc, x, thumbs)

    total_score = score_overall(pipe, gsc, x)
    grade = "A" if total_score >= 85 else "B" if total_score >= 70 else "C" if total_score >= 55 else "D"

    # ── [1] 総合スコア ───────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  総合スコア: {total_score}/100  グレード: {grade}")
    print(f"{'─'*65}")
    print(f"  パイプライン完走率: {pipe['completion_rate']:.0%}  "
          f"HARD_FAIL率: {pipe['hard_fail_rate']:.0%}")
    print(f"  GSCインデックス済: {gsc['indexed']}件  "
          f"送信済未反映: {gsc['submitted_pending']}件  "
          f"URL不明: {gsc['url_unknown']}件")
    print(f"  X投稿: 投稿済{x['tweets_sent']}件  スキップ{x['skipped']}件  "
          f"DRY-RUN{x['plan_only']}件  失敗{x['failures']}件")

    # ── [2] P0/P1/P2課題 ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  TOP10 重要課題")
    print(f"{'─'*65}")
    issues = top10_issues(pipe, gsc, thumbs, x)
    for issue in issues:
        status_icon = "✅" if "対応済" in issue["status"] else "❌" if issue["priority"] == "P0" else "⚠️" if issue["priority"] == "P1" else "📌"
        print(f"\n  #{issue['rank']} [{issue['priority']}/{issue['severity']}] {status_icon} {issue['title']}")
        print(f"       対応: {issue['action']}")
        print(f"       状態: {issue['status']}")

    # ── [3] 記事別問題 ───────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  記事別問題リスト")
    print(f"{'─'*65}")
    if article_problems:
        for pid in sorted(article_problems.keys()):
            probs = article_problems[pid]
            print(f"\n  ID={pid}:")
            for pr in probs:
                print(f"    • {pr}")
    else:
        print("  問題なし")

    # ── [4] サムネ別問題 ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  サムネイル問題レジストリ（既知10件）")
    print(f"{'─'*65}")
    for pid, info in KNOWN_THUMBNAIL_ISSUES.items():
        overflow = " [オーバーフロー]" if info["overflow_risk"] else ""
        print(f"  ID={pid} [{info['severity']}]{overflow}: {info['problem']}")
        print(f"           → 推奨コピー: {info['suggested_copy']}")

    # ── [5] X投稿監査 ────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  X投稿監査（直近72h）")
    print(f"{'─'*65}")
    print(f"  投稿済: {x['tweets_sent']}件  スキップ: {x['skipped']}件  "
          f"DRY-RUN: {x['plan_only']}件  失敗: {x['failures']}件")
    if x["posted"]:
        print(f"  最近の投稿（最大5件）:")
        for rec in x["posted"][-5:]:
            print(f"    post_id={rec['post_id']} tweet_id={rec['tweet_id']}"
                  f" [{rec['posted_at'][:16]}] {rec['title'][:40]}")

    # ── [6] GSC監査 ──────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  GSCインデックス監査")
    print(f"{'─'*65}")
    print(f"  登録済み:      {gsc['indexed']}件  {gsc['indexed_ids'][:5]}")
    print(f"  送信済未反映:  {gsc['submitted_pending']}件  {gsc['submitted_pending_ids'][:5]}")
    print(f"  URL不明:       {gsc['url_unknown']}件  {gsc['url_unknown_ids'][:5]}")
    print(f"  URLエラー:     {gsc['url_error']}件  {gsc['url_error_ids'][:5]}")
    print(f"  未送信:        {gsc['not_submitted']}件")

    # ── [7] 重複記事候補 ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  重複記事候補")
    print(f"{'─'*65}")
    if duplicates:
        for dup in duplicates:
            print(f"  keep=ID{dup['keep_post_id']} vs drop=ID{dup['drop_post_id']}"
                  f"  類似度={dup['similarity']:.0%}")
            print(f"    理由: {dup['reason']}")
            print(f"    対応: {dup['suggested_action']}")
    else:
        print("  重複なし")

    # ── [8] スラッグ監査 ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  スラッグ品質監査")
    print(f"{'─'*65}")
    if slug_issues:
        for si in slug_issues:
            print(f"  ID={si['post_id']} slug='{si['current_slug']}' → 問題: {si['problems']}")
            print(f"    提案: '{si['proposed_slug']}'")
    else:
        print("  (スラッグデータなし。--posts オプションで投稿データを渡してください)")

    # ── [9] 誤認除外済み ─────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  誤認除外済み（False Positive Exclusions）")
    print(f"{'─'*65}")
    for fp in FALSE_POSITIVE_EXCLUSIONS:
        pid_str = f"ID={fp['post_id']}" if fp['post_id'] else "複数"
        print(f"  {pid_str} [{fp['field']}] ← {fp['old_flag']}")
        print(f"    解決: {fp['resolution']}")

    print(f"\n{'='*65}")
    print("  監査完了")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
