#!/usr/bin/env python3
"""
winning_pattern_db.py — 勝ちパターン構造化DB v1.0

winning_patterns.jsonl + title_performance.jsonl を SQLite に統合し、
高速クエリ・パターン分析APIを提供する。

【データソース】
  logs/winning_patterns.jsonl   : 記事パフォーマンス（win/lose/pending）
  logs/title_performance.jsonl  : タイトル特徴量（数字/固有名詞/感情語/対比）
  logs/arceus_rejections.jsonl  : arceus却下履歴

【テーブル構造】
  articles       : 記事マスタ（post_id, title, url, category, publish_hour, etc.）
  title_features : タイトル特徴量（has_number, has_emotion_word, etc.）
  performance    : パフォーマンス評価（result, eval_24h/48h/72h, ctr_score）
  x_posts        : X投稿パフォーマンス
  rejections     : arceus却下履歴

Usage:
  python3 lib/winning_pattern_db.py init          # DB初期化＆JSONLからインポート
  python3 lib/winning_pattern_db.py sync          # 差分同期（新規レコードのみ追加）
  python3 lib/winning_pattern_db.py query-wins    # 勝ちパターン分析
  python3 lib/winning_pattern_db.py query-best    # カテゴリ別ベストタイトル
  python3 lib/winning_pattern_db.py query-elements # 要素別勝率
  python3 lib/winning_pattern_db.py query-hours   # 時間帯別勝率
  python3 lib/winning_pattern_db.py export-report # 分析レポートJSON出力
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
DB_PATH = LOGS / "winning_patterns.db"
WIN_PATTERNS = LOGS / "winning_patterns.jsonl"
TITLE_PERF = LOGS / "title_performance.jsonl"
REJECTION_LOG = LOGS / "arceus_rejections.jsonl"
REPORT_OUT = LOGS / "winning_pattern_report.json"

JST = timezone(timedelta(hours=9))


# ── スキーマ定義 ────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    post_id       TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    url           TEXT,
    slug          TEXT,
    category      TEXT DEFAULT 'other',
    article_type  TEXT DEFAULT 'flow',
    publish_hour  INTEGER,
    has_thumbnail INTEGER DEFAULT 0,
    title_length  INTEGER DEFAULT 0,
    recorded_at   TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS title_features (
    post_id          TEXT PRIMARY KEY REFERENCES articles(post_id),
    has_number       INTEGER DEFAULT 0,
    has_proper_noun  INTEGER DEFAULT 0,
    has_emotion_word INTEGER DEFAULT 0,
    has_contrast     INTEGER DEFAULT 0,
    thumbnail_score  REAL DEFAULT 0,
    x_hook_score     REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS performance (
    post_id     TEXT PRIMARY KEY REFERENCES articles(post_id),
    result      TEXT DEFAULT 'pending',  -- win/lose/pending
    eval_24h    REAL,
    eval_48h    REAL,
    eval_72h    REAL,
    ctr_score   REAL DEFAULT 0,
    raw_ctr     REAL,
    impressions INTEGER DEFAULT 0,
    rewritten   INTEGER DEFAULT 0,
    updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS x_posts (
    post_id         TEXT PRIMARY KEY REFERENCES articles(post_id),
    x_posted_status TEXT DEFAULT 'not_posted',
    x_hook_score    REAL DEFAULT 0,
    indexed_status  TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS rejections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT,
    run_id          TEXT,
    attempt         INTEGER DEFAULT 1,
    rejection_line  TEXT,
    reason_text     TEXT,
    categories      TEXT,  -- JSON array
    revision_result TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_perf_result ON performance(result);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_publish_hour ON articles(publish_hour);
CREATE INDEX IF NOT EXISTS idx_rejections_categories ON rejections(categories);
"""


def get_db() -> sqlite3.Connection:
    LOGS.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA)
    conn.commit()


# ── JSONLインポート ──────────────────────────────────────────────

def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def import_winning_patterns(conn: sqlite3.Connection) -> int:
    """winning_patterns.jsonl からDBにインポート"""
    records = _load_jsonl(WIN_PATTERNS)
    imported = 0
    for r in records:
        pid = str(r.get("post_id", ""))
        if not pid:
            continue
        try:
            conn.execute("""
                INSERT OR REPLACE INTO articles
                (post_id, title, url, slug, category, article_type, publish_hour,
                 has_thumbnail, title_length, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("title", ""), r.get("url", ""), r.get("slug", ""),
                r.get("category", "other"), r.get("article_type", "flow"),
                r.get("publish_hour"), 1 if r.get("has_thumbnail") else 0,
                r.get("title_length", 0), r.get("recorded_at", ""),
            ))

            conn.execute("""
                INSERT OR REPLACE INTO title_features
                (post_id, has_number, has_proper_noun, has_emotion_word,
                 has_contrast, thumbnail_score, x_hook_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pid,
                1 if r.get("has_number") else 0,
                1 if r.get("has_proper_noun") else 0,
                1 if r.get("has_emotion_word") else 0,
                1 if r.get("has_contrast") else 0,
                r.get("thumbnail_score", 0),
                r.get("x_hook_score", 0),
            ))

            conn.execute("""
                INSERT OR REPLACE INTO performance
                (post_id, result, eval_24h, eval_48h, eval_72h, ctr_score,
                 raw_ctr, impressions, rewritten)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid, r.get("result", "pending"),
                r.get("eval_24h"), r.get("eval_48h"), r.get("eval_72h"),
                r.get("ctr_score", 0), r.get("raw_ctr"),
                r.get("impressions", 0), 1 if r.get("rewritten") else 0,
            ))

            conn.execute("""
                INSERT OR REPLACE INTO x_posts
                (post_id, x_posted_status, x_hook_score, indexed_status)
                VALUES (?, ?, ?, ?)
            """, (
                pid, r.get("x_posted_status", "not_posted"),
                r.get("x_hook_score", 0), r.get("indexed_status", "unknown"),
            ))
            imported += 1
        except Exception as e:
            print(f"  WARN: post_id={pid} import error: {e}", file=sys.stderr)

    conn.commit()
    return imported


def import_rejections(conn: sqlite3.Connection) -> int:
    """arceus_rejections.jsonl からインポート"""
    records = _load_jsonl(REJECTION_LOG)
    imported = 0
    for r in records:
        try:
            conn.execute("""
                INSERT INTO rejections
                (timestamp, run_id, attempt, rejection_line, reason_text,
                 categories, revision_result)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                r.get("timestamp", ""), r.get("run_id", ""),
                r.get("attempt", 1), r.get("rejection_line", ""),
                r.get("reason_text", ""),
                json.dumps(r.get("categories", []), ensure_ascii=False),
                r.get("revision_result", ""),
            ))
            imported += 1
        except Exception:
            pass
    conn.commit()
    return imported


# ── クエリAPI ────────────────────────────────────────────────────

def query_win_patterns(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """勝ちパターン分析: 勝ち記事の共通特徴"""
    rows = conn.execute("""
        SELECT a.title, a.category, a.publish_hour, a.title_length,
               tf.has_number, tf.has_proper_noun, tf.has_emotion_word, tf.has_contrast,
               p.eval_72h, p.raw_ctr, p.impressions
        FROM articles a
        JOIN title_features tf ON a.post_id = tf.post_id
        JOIN performance p ON a.post_id = p.post_id
        WHERE p.result = 'win'
        ORDER BY COALESCE(p.eval_72h, p.eval_48h, p.eval_24h, 0) DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def query_best_by_category(conn: sqlite3.Connection) -> list[dict]:
    """カテゴリ別ベストタイトル"""
    rows = conn.execute("""
        SELECT a.category,
               a.title,
               COALESCE(p.eval_72h, p.eval_48h, p.eval_24h, 0) as score,
               a.title_length,
               tf.has_number, tf.has_emotion_word
        FROM articles a
        JOIN performance p ON a.post_id = p.post_id
        JOIN title_features tf ON a.post_id = tf.post_id
        WHERE p.result = 'win'
        GROUP BY a.category
        HAVING score = MAX(score)
        ORDER BY score DESC
    """).fetchall()
    return [dict(r) for r in rows]


def query_element_win_rates(conn: sqlite3.Connection) -> dict:
    """タイトル要素別の勝率"""
    elements = ["has_number", "has_proper_noun", "has_emotion_word", "has_contrast"]
    result = {}
    for elem in elements:
        rows = conn.execute(f"""
            SELECT
                SUM(CASE WHEN p.result = 'win' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN p.result = 'lose' THEN 1 ELSE 0 END) as loses,
                COUNT(*) as total
            FROM title_features tf
            JOIN performance p ON tf.post_id = p.post_id
            WHERE tf.{elem} = 1 AND p.result IN ('win', 'lose')
        """).fetchone()
        wins = rows["wins"] or 0
        loses = rows["loses"] or 0
        total = wins + loses
        result[elem] = {
            "wins": wins,
            "loses": loses,
            "total": total,
            "win_rate": round(wins / max(total, 1), 3),
        }
    return result


def query_hour_win_rates(conn: sqlite3.Connection) -> list[dict]:
    """公開時間帯別の勝率"""
    rows = conn.execute("""
        SELECT a.publish_hour,
               SUM(CASE WHEN p.result = 'win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN p.result = 'lose' THEN 1 ELSE 0 END) as loses,
               COUNT(*) as total
        FROM articles a
        JOIN performance p ON a.post_id = p.post_id
        WHERE p.result IN ('win', 'lose') AND a.publish_hour IS NOT NULL
        GROUP BY a.publish_hour
        ORDER BY a.publish_hour
    """).fetchall()
    return [
        {
            "hour": r["publish_hour"],
            "wins": r["wins"],
            "loses": r["loses"],
            "total": r["total"],
            "win_rate": round(r["wins"] / max(r["total"], 1), 3),
        }
        for r in rows
    ]


def query_category_stats(conn: sqlite3.Connection) -> list[dict]:
    """カテゴリ別統計"""
    rows = conn.execute("""
        SELECT a.category,
               COUNT(*) as total,
               SUM(CASE WHEN p.result = 'win' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN p.result = 'lose' THEN 1 ELSE 0 END) as loses,
               AVG(a.title_length) as avg_title_length,
               AVG(COALESCE(p.eval_72h, 0)) as avg_score
        FROM articles a
        JOIN performance p ON a.post_id = p.post_id
        WHERE p.result IN ('win', 'lose')
        GROUP BY a.category
        ORDER BY wins DESC
    """).fetchall()
    return [
        {
            "category": r["category"],
            "total": r["total"],
            "wins": r["wins"],
            "loses": r["loses"],
            "win_rate": round(r["wins"] / max(r["total"], 1), 3),
            "avg_title_length": round(r["avg_title_length"] or 0, 1),
            "avg_score": round(r["avg_score"] or 0, 2),
        }
        for r in rows
    ]


def export_full_report(conn: sqlite3.Connection) -> dict:
    """全分析結果をまとめたレポートを生成"""
    report = {
        "generated_at": datetime.now(JST).isoformat(),
        "db_path": str(DB_PATH),
        "total_articles": conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
        "total_wins": conn.execute("SELECT COUNT(*) FROM performance WHERE result='win'").fetchone()[0],
        "total_loses": conn.execute("SELECT COUNT(*) FROM performance WHERE result='lose'").fetchone()[0],
        "total_pending": conn.execute("SELECT COUNT(*) FROM performance WHERE result='pending'").fetchone()[0],
        "element_win_rates": query_element_win_rates(conn),
        "hour_win_rates": query_hour_win_rates(conn),
        "category_stats": query_category_stats(conn),
        "best_by_category": query_best_by_category(conn),
        "top_wins": query_win_patterns(conn, limit=10),
    }
    total = report["total_wins"] + report["total_loses"]
    report["overall_win_rate"] = round(report["total_wins"] / max(total, 1), 3)
    return report


# ── CLI ──────────────────────────────────────────────────────────

def cmd_init(args):
    print(f"[winning_pattern_db] DB初期化: {DB_PATH}")
    conn = get_db()
    init_schema(conn)
    n1 = import_winning_patterns(conn)
    n2 = import_rejections(conn)
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    print(f"  winning_patterns: {n1}件インポート")
    print(f"  rejections: {n2}件インポート")
    print(f"  DB総記事数: {total}")


def cmd_sync(args):
    print(f"[winning_pattern_db] 差分同期")
    conn = get_db()
    init_schema(conn)
    existing = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    n1 = import_winning_patterns(conn)
    n2 = import_rejections(conn)
    new_total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    print(f"  既存: {existing} → 新合計: {new_total} (差分: {new_total - existing})")


def cmd_query_wins(args):
    conn = get_db()
    wins = query_win_patterns(conn, limit=args.limit)
    conn.close()
    print(f"\n=== 勝ちパターン TOP-{args.limit} ===")
    for i, w in enumerate(wins, 1):
        elems = []
        if w.get("has_number"):
            elems.append("数字")
        if w.get("has_proper_noun"):
            elems.append("固有名詞")
        if w.get("has_emotion_word"):
            elems.append("感情語")
        if w.get("has_contrast"):
            elems.append("対比")
        print(f"  {i}. [{w['category']}] {w['title'][:55]}")
        print(f"     score={w.get('eval_72h') or '-'} CTR={w.get('raw_ctr') or '-'} 要素={'+'.join(elems)}")


def cmd_query_best(args):
    conn = get_db()
    best = query_best_by_category(conn)
    conn.close()
    print(f"\n=== カテゴリ別ベストタイトル ===")
    for b in best:
        print(f"  [{b['category']}] score={b['score']}")
        print(f"    {b['title'][:60]}")


def cmd_query_elements(args):
    conn = get_db()
    rates = query_element_win_rates(conn)
    conn.close()
    print(f"\n=== タイトル要素別勝率 ===")
    for elem, data in sorted(rates.items(), key=lambda x: -x[1]["win_rate"]):
        label = elem.replace("has_", "")
        bar = "#" * int(data["win_rate"] * 20)
        print(f"  {label:<15} {data['win_rate']:.0%} ({data['wins']}W/{data['loses']}L) {bar}")


def cmd_query_hours(args):
    conn = get_db()
    hours = query_hour_win_rates(conn)
    conn.close()
    print(f"\n=== 公開時間帯別勝率 ===")
    for h in hours:
        bar = "#" * int(h["win_rate"] * 20)
        print(f"  {h['hour']:2d}時 {h['win_rate']:.0%} ({h['wins']}W/{h['loses']}L) {bar}")


def cmd_export_report(args):
    conn = get_db()
    report = export_full_report(conn)
    conn.close()
    REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[winning_pattern_db] レポート出力: {REPORT_OUT}")
    print(f"  総記事: {report['total_articles']} 勝率: {report['overall_win_rate']:.0%}")
    print(f"  勝ち: {report['total_wins']} 負け: {report['total_loses']} 待機: {report['total_pending']}")


def main():
    parser = argparse.ArgumentParser(description="勝ちパターン構造化DB v1.0")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="DB初期化＆JSONLからフルインポート")
    sub.add_parser("sync", help="差分同期（新規レコードのみ追加）")

    p_wins = sub.add_parser("query-wins", help="勝ちパターン分析")
    p_wins.add_argument("--limit", type=int, default=10)

    sub.add_parser("query-best", help="カテゴリ別ベストタイトル")
    sub.add_parser("query-elements", help="要素別勝率")
    sub.add_parser("query-hours", help="時間帯別勝率")
    sub.add_parser("export-report", help="分析レポートJSON出力")

    args = parser.parse_args()
    dispatch = {
        "init": cmd_init, "sync": cmd_sync,
        "query-wins": cmd_query_wins, "query-best": cmd_query_best,
        "query-elements": cmd_query_elements, "query-hours": cmd_query_hours,
        "export-report": cmd_export_report,
    }
    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
