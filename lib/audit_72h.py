#!/usr/bin/env python3
"""
72時間再監査スクリプト (audit_72h.py) v3.0
Usage: python3 lib/audit_72h.py [--hours 72]

出力: 総合スコア、TOP10課題、パイプライン詳細、サムネ供給源、X投稿監査、GSC監査、重複記事候補、スラッグ監査

v3.0 (2026-08-10): 全面書き換え。
  v2.0 は 2026-04 時点のハードコード課題レジストリ(記事ID 2441-2581)と
  4月で更新停止した死にログ(pipeline.jsonl / gardevoir_hook.jsonl /
  thumbnail_performance.jsonl)を読み続け、TOP10 とスコアが凍結していた。
  v3.0 は現役ログのみを窓内集計する:
    - logs/unified_publish.jsonl      (公開試行と成否・サムネ供給源)
    - logs/pre_publish_gate.jsonl     (品質ゲート verdict / block 内訳)
    - data/gsc_indexing_log.jsonl     (GSC 送信の成否)
    - logs/x_post.log + tweet_id_db.tsv (X投稿。長期停止中は減点しない)
  互換契約(変更禁止):
    - 出力に「総合スコア: NN/100  グレード: X」行を含む(audit_daily/weekly/monthly が grep 抽出)
    - audit_gsc() は logs/gsc_tracking.json を list[entry] 形式で書き出す
      (auto_rewriter / post_publish_evaluator / winning_pattern_tracker が消費)
    - audit_thumbnails / audit_x_posts は import 可能な dict 返し
      (run_daily_optimization.sh が使用)
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
DATA = SCRIPT_DIR / "data"
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

# ── ゲート BLOCK の分類 ──────────────────────────────────────────────────────
# benign = ゲートが設計どおり弾いた(品質劣化ではない)ブロック。dedup・非K-POP除外など。
# それ以外は生成品質の劣化シグナルとして quality 側に数える。
BENIGN_BLOCK_TYPES = {
    "duplicate_title", "duplicate_phrase", "non_kpop_topic",
    "stale_date", "no_source_no_signal",
}


def _is_benign_block(btype: str) -> bool:
    return btype in BENIGN_BLOCK_TYPES or btype.startswith("dup")


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


def _in_window(ts_str, cutoff):
    dt = _parse_dt(ts_str)
    return dt is not None and dt >= cutoff


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
    """公開パイプライン: unified_publish.jsonl + pre_publish_gate.jsonl の窓内集計"""
    cutoff = _cutoff(hours)
    days = max(hours / 24.0, 0.001)

    pub_recs = [r for r in _load_jsonl(LOGS / "unified_publish.jsonl")
                if _in_window(r.get("ts", ""), cutoff)]
    attempts = len(pub_recs)
    published = [r for r in pub_recs if r.get("success") is True]

    gate_recs = [r for r in _load_jsonl(LOGS / "pre_publish_gate.jsonl")
                 if _in_window(r.get("ts", ""), cutoff)]
    verdicts = {"PASS": 0, "WARN": 0, "BLOCK": 0}
    block_types = {}
    blocked_titles = {}
    for r in gate_recs:
        v = r.get("verdict", "?")
        if v in verdicts:
            verdicts[v] += 1
        if v == "BLOCK":
            t = (r.get("title") or "")[:40]
            blocked_titles[t] = blocked_titles.get(t, 0) + 1
        for issue in r.get("issues", []):
            if issue.get("severity") == "block":
                bt = issue.get("type", "unknown")
                block_types[bt] = block_types.get(bt, 0) + 1

    benign_blocks = sum(n for t, n in block_types.items() if _is_benign_block(t))
    quality_blocks = sum(n for t, n in block_types.items() if not _is_benign_block(t))
    # 品質ブロック率: 公開1本に対して品質理由のブロック(=矯正リトライ)が
    # どれだけ発生したか。0.5 までは矯正リトライ設計の正常域とみなす。
    q_denom = quality_blocks + len(published)
    quality_block_ratio = quality_blocks / q_denom if q_denom else 0.0

    return {
        "attempts": attempts,
        "published": len(published),
        "published_per_day": len(published) / days,
        "gate_pass": verdicts["PASS"],
        "gate_warn": verdicts["WARN"],
        "gate_block": verdicts["BLOCK"],
        "block_types": dict(sorted(block_types.items(), key=lambda kv: -kv[1])),
        "benign_blocks": benign_blocks,
        "quality_blocks": quality_blocks,
        "quality_block_ratio": quality_block_ratio,
        "top_blocked_titles": sorted(blocked_titles.items(), key=lambda kv: -kv[1])[:5],
    }


def audit_gsc(hours=72):
    """GSCインデックス状況: gsc_index_check.jsonl + indexing_api_sends.jsonlを両方読む

    注意: この2ログは更新が止まっていることがある(鮮度は main() で表示)。
    出力の logs/gsc_tracking.json は auto_rewriter 等が消費する互換契約なので
    形式・生成ロジックは v2.0 から変更しない。
    """
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
    except Exception:
        pass  # 書き出し失敗は無視して続行

    # 照合ログの鮮度(日): 最終更新からの経過。7日超は「停止中」扱いで表示。
    stale_days = None
    try:
        stale_days = (datetime.now() - datetime.fromtimestamp(gsc_log.stat().st_mtime)).days
    except OSError:
        pass

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
        "check_log_stale_days": stale_days,
    }


def audit_gsc_submissions(hours=72):
    """GSC 送信の現役ログ(data/gsc_indexing_log.jsonl)の窓内集計"""
    cutoff = _cutoff(hours)
    recs = [r for r in _load_jsonl(DATA / "gsc_indexing_log.jsonl")
            if _in_window(r.get("timestamp", ""), cutoff)]
    by_status = {}
    for r in recs:
        st = r.get("status", "?")
        by_status[st] = by_status.get(st, 0) + 1
    total = len(recs)
    errors = sum(n for st, n in by_status.items()
                 if st not in ("ok", "success", "skipped_dup"))
    return {
        "total": total,
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "errors": errors,
        "error_rate": errors / total if total else 0.0,
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

    total_activity = len(posted) + failed + skipped + plan_only
    return {
        "tweets_sent": len(posted),
        "posted": posted,
        "failures": failed,
        "skipped": skipped,
        "plan_only": plan_only,
        # 窓内の活動ゼロ = 自動投稿の意図的停止(シャドウバン対応)とみなし減点しない
        "paused": total_activity == 0,
    }


def audit_thumbnails(hours=72):
    """サムネイル供給源: unified_publish.jsonl の thumb_source を窓内集計

    v2.0 の固定「既知問題レジストリ」(2026-04 の記事ID)は廃止。
    dalle3 比率が高い = 本人写真取得が失敗している劣化シグナル
    (背景: memory thumbnail-dalle-overuse-rootcause-cache-fix)。
    """
    cutoff = _cutoff(hours)
    sources = {}
    for r in _load_jsonl(LOGS / "unified_publish.jsonl"):
        if r.get("success") is not True or not _in_window(r.get("ts", ""), cutoff):
            continue
        src = r.get("thumb_source") or "unknown"
        sources[src] = sources.get(src, 0) + 1
    known = sum(n for s, n in sources.items() if s != "unknown")
    dalle = sources.get("dalle3", 0)
    return {
        "records": sum(sources.values()),
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
        "dalle_rate": dalle / known if known else 0.0,
    }


def detect_duplicates(posts=None):
    """
    重複記事検出: タイトルのトークンオーバーラップ率 > 0.7 でフラグ

    posts: [{"post_id": int, "title": str, "slug": str}, ...]
    """
    if not posts:
        return []

    detected = []
    existing_pairs = set()

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
            problems.append("スラッグ重複 (他の記事と衝突)")

        if problems:
            issues.append({
                "post_id": pid,
                "current_slug": slug,
                "problems": problems,
                "proposed_slug": proposed,
                "title": title[:50],
            })

    return issues


def score_overall(pipe, gsc_sub, x, thumbs):
    """総合スコア(100点)。全て窓内の現役ログ実測から算出する。

    - 公開スループット 30点: 15本/日で満点(実測ベースライン 22本/日)
    - 品質ブロック率   25点: 0.5 以下で満点、1.0 で 0点
      (dedup 等の benign block は数えない。公開1本あたり品質矯正1回までは正常域)
    - サムネ供給源     20点: dalle3 率 20% 以下で満点、80% で 0点
    - GSC送信          15点: 窓内送信あり かつ エラー率 10% 未満で満点、50% で 0点
    - X投稿            10点: 失敗 3件超で 0点。意図的停止(活動ゼロ)は減点しない
    """
    breakdown = {}

    ppd = pipe["published_per_day"]
    breakdown["throughput"] = round(min(30.0, ppd / 15.0 * 30.0), 1)

    q = pipe["quality_block_ratio"]
    if q <= 0.5:
        breakdown["quality"] = 25.0
    else:
        breakdown["quality"] = round(max(0.0, 25.0 * (1 - (q - 0.5) / 0.5)), 1)

    d = thumbs["dalle_rate"]
    if d <= 0.2:
        breakdown["thumbnail"] = 20.0
    else:
        breakdown["thumbnail"] = round(max(0.0, 20.0 * (1 - (d - 0.2) / 0.6)), 1)

    if gsc_sub["total"] == 0:
        breakdown["gsc"] = 0.0
    else:
        er = gsc_sub["error_rate"]
        if er < 0.10:
            breakdown["gsc"] = 15.0
        else:
            breakdown["gsc"] = round(max(0.0, 15.0 * (1 - (er - 0.10) / 0.40)), 1)

    if x["failures"] > 3:
        breakdown["x"] = 0.0
    else:
        breakdown["x"] = 10.0

    return int(round(sum(breakdown.values()))), breakdown


def top10_issues(pipe, gsc, gsc_sub, x, thumbs):
    """窓内実測から動的に課題を組み立てる(固定文言のレジストリは持たない)"""
    issues = []

    ppd = pipe["published_per_day"]
    if ppd < 5:
        issues.append({
            "priority": "P0", "severity": "CRITICAL",
            "title": f"公開スループット低下: {ppd:.1f}本/日(基準15本/日)",
            "action": "unified_publish.jsonl の失敗ログと cron 稼働を確認",
        })
    elif ppd < 10:
        issues.append({
            "priority": "P1", "severity": "HIGH",
            "title": f"公開スループット注意: {ppd:.1f}本/日(基準15本/日)",
            "action": "速報ソース量とゲートblock内訳を確認",
        })

    q = pipe["quality_block_ratio"]
    if q > 0.5:
        top_types = [f"{t}x{n}" for t, n in list(pipe["block_types"].items())
                     if not _is_benign_block(t)][:3]
        issues.append({
            "priority": "P1" if q > 0.7 else "P2",
            "severity": "HIGH" if q > 0.7 else "MEDIUM",
            "title": f"品質ブロック率 {q:.0%}(正常域<=50%): {';'.join(top_types)}",
            "action": "生成品質の劣化。上位blockタイプの発生源(翻訳/サムネ/本文長)を調査",
        })

    d = thumbs["dalle_rate"]
    if d > 0.3:
        issues.append({
            "priority": "P1", "severity": "HIGH",
            "title": f"サムネDALL-E依存率 {d:.0%}(基準<=20%)",
            "action": "本人写真取得の失敗。Unsplashキー設定と fetch_safe_image の fallback を確認",
        })

    if gsc_sub["total"] == 0:
        issues.append({
            "priority": "P1", "severity": "HIGH",
            "title": "GSC送信が窓内ゼロ(data/gsc_indexing_log.jsonl)",
            "action": "gsc_indexing.py の cron 稼働を確認",
        })
    elif gsc_sub["error_rate"] >= 0.10:
        issues.append({
            "priority": "P1", "severity": "HIGH",
            "title": f"GSC送信エラー率 {gsc_sub['error_rate']:.0%}: {gsc_sub['by_status']}",
            "action": "認証(トークン失効)とAPIクォータを確認",
        })

    if x["failures"] > 3:
        issues.append({
            "priority": "P2", "severity": "MEDIUM",
            "title": f"X投稿失敗 {x['failures']}件",
            "action": "x_post.log のエラー内容を確認",
        })

    stale = gsc.get("check_log_stale_days")
    if stale is not None and stale > 7:
        issues.append({
            "priority": "P2", "severity": "LOW",
            "title": f"GSC照合ログ(gsc_index_check.jsonl)が{stale}日間更新停止",
            "action": "gsc_tracking.json の鮮度に影響。照合バッチの稼働を確認"
                      "(ローカル限定GSC認証: memory gsc-index-watch-cron)",
        })

    for i, issue in enumerate(issues, 1):
        issue["rank"] = i
    return issues[:10]


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
    print(f"  72時間再監査レポート v3.0  ({now_str} / 窓={hours}h)")
    print(f"{'='*65}")

    # ── データ収集 ──────────────────────────────────────────────────
    pipe = audit_pipeline(hours)
    gsc = audit_gsc(hours)
    gsc_sub = audit_gsc_submissions(hours)
    x = audit_x_posts(hours)
    thumbs = audit_thumbnails(hours)

    total_score, breakdown = score_overall(pipe, gsc_sub, x, thumbs)
    grade = "A" if total_score >= 85 else "B" if total_score >= 70 else "C" if total_score >= 55 else "D"

    # ── [1] 総合スコア ───────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  総合スコア: {total_score}/100  グレード: {grade}")
    print(f"{'─'*65}")
    print(f"  内訳: スループット{breakdown['throughput']}/30"
          f"  品質{breakdown['quality']}/25"
          f"  サムネ{breakdown['thumbnail']}/20"
          f"  GSC{breakdown['gsc']}/15"
          f"  X{breakdown['x']}/10")
    print(f"  公開: {pipe['published']}件 ({pipe['published_per_day']:.1f}本/日)"
          f"  試行: {pipe['attempts']}件")
    print(f"  ゲート: PASS {pipe['gate_pass']} / WARN {pipe['gate_warn']}"
          f" / BLOCK {pipe['gate_block']}"
          f" (benign {pipe['benign_blocks']} / quality {pipe['quality_blocks']}"
          f" → 品質ブロック率 {pipe['quality_block_ratio']:.0%})")

    # ── [2] TOP10 重要課題 ───────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  TOP10 重要課題(窓内実測ベース)")
    print(f"{'─'*65}")
    issues = top10_issues(pipe, gsc, gsc_sub, x, thumbs)
    if issues:
        for issue in issues:
            icon = "❌" if issue["priority"] == "P0" else "⚠️" if issue["priority"] == "P1" else "📌"
            print(f"\n  #{issue['rank']} [{issue['priority']}/{issue['severity']}] {icon} {issue['title']}")
            print(f"       対応: {issue['action']}")
    else:
        print("  重大課題なし")

    # ── [3] ゲート BLOCK 内訳 ────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  品質ゲート BLOCK 内訳(窓内)")
    print(f"{'─'*65}")
    if pipe["block_types"]:
        for bt, n in pipe["block_types"].items():
            tag = "benign " if _is_benign_block(bt) else "quality"
            print(f"  [{tag}] {bt}: {n}件")
        if pipe["top_blocked_titles"]:
            print("  BLOCK 頻出タイトル(最大5件):")
            for t, n in pipe["top_blocked_titles"]:
                print(f"    {n}回: {t}")
    else:
        print("  BLOCK なし")

    # ── [4] サムネイル供給源 ─────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  サムネイル供給源(窓内・公開成功分)")
    print(f"{'─'*65}")
    if thumbs["sources"]:
        for src, n in thumbs["sources"].items():
            print(f"  {src}: {n}件")
        print(f"  DALL-E率: {thumbs['dalle_rate']:.0%} (基準<=20%)")
    else:
        print("  データなし")

    # ── [5] X投稿監査 ────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  X投稿監査(窓内)")
    print(f"{'─'*65}")
    if x["paused"]:
        print("  活動なし — 自動投稿は意図的に長期停止中(シャドウバン対応)。減点対象外")
    else:
        print(f"  投稿済: {x['tweets_sent']}件  スキップ: {x['skipped']}件  "
              f"DRY-RUN: {x['plan_only']}件  失敗: {x['failures']}件")
        if x["posted"]:
            print(f"  最近の投稿（最大5件）:")
            for rec in x["posted"][-5:]:
                print(f"    post_id={rec['post_id']} tweet_id={rec['tweet_id']}"
                      f" [{rec['posted_at'][:16]}] {rec['title'][:40]}")

    # ── [6] GSC監査 ──────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print("  GSC送信(現役ログ: data/gsc_indexing_log.jsonl・窓内)")
    print(f"{'─'*65}")
    if gsc_sub["total"]:
        for st, n in gsc_sub["by_status"].items():
            print(f"  {st}: {n}件")
        print(f"  エラー率: {gsc_sub['error_rate']:.0%}")
    else:
        print("  窓内の送信記録なし")

    stale = gsc.get("check_log_stale_days")
    stale_note = f"(最終更新 {stale}日前・停止中)" if stale is not None and stale > 7 else ""
    print(f"\n  照合ログ(gsc_index_check.jsonl){stale_note}:")
    print(f"  登録済み:      {gsc['indexed']}件  {gsc['indexed_ids'][:5]}")
    print(f"  送信済未反映:  {gsc['submitted_pending']}件  {gsc['submitted_pending_ids'][:5]}")
    print(f"  URL不明:       {gsc['url_unknown']}件  {gsc['url_unknown_ids'][:5]}")
    print(f"  URLエラー:     {gsc['url_error']}件  {gsc['url_error_ids'][:5]}")
    print(f"  gsc_tracking.json 書き出し: {gsc['gsc_tracking_written']}件")

    print(f"\n{'='*65}")
    print("  監査完了")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
