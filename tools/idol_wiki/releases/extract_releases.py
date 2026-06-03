#!/usr/bin/env python3
"""extract_releases.py — 速報ニュースから Idol Wiki 用「リリース事実」を構造抽出する。

logs/breaking_articles.jsonl の速報タイトルから、新譜/シングル/アルバム等の
**リリース事実のみ**を LLM で構造化し、候補キューに積む。ゴシップ・活動・憶測は除外。
Idol Wiki(正本)汚染を避けるため、ここでは書き込まない(候補生成のみ)。

パイプライン: breaking → 冪等フィルタ → artist_resolver で pid 解決 → LLM 抽出 →
  data/idol_wiki_release_candidates.jsonl (status=pending) へ append。

Usage:
    python3 tools/idol_wiki/releases/extract_releases.py --artist aespa,RIIZE --dry-run
    python3 tools/idol_wiki/releases/extract_releases.py --artist aespa     # 候補をキューに追加
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))
try:
    from dotenv import load_dotenv
    load_dotenv(str(BASE / ".env"))  # ANTHROPIC_API_KEY を .env から読む(factcheck_v2 と同作法)
except ImportError:
    pass
from lib.artist_resolver import resolve  # noqa: E402

BREAKING_LOG = BASE / "logs" / "breaking_articles.jsonl"
CANDIDATES = BASE / "data" / "idol_wiki_release_candidates.jsonl"
PROCESSED = BASE / "data" / "processed_breaking.jsonl"

# 憶測・未確定を示す語。タイトルにこれを含むものは release として採らない(G1)。
SPECULATION_RE = re.compile(
    r"(噂|うわさ|か\?|か？|予定|見込み|の可能性|説|疑惑|とみられ|か検討|するか|なるか|計画)")
# リリースを示唆する語。これが無いタイトルは release ではない可能性が高い。
RELEASE_HINT_RE = re.compile(
    r"(発売|発表|公開|リリース|カムバック|カムバ|新曲|新譜|アルバム|シングル|EP|"
    r"ミニアルバム|正規|集|タイトル曲|収録|MV|ミュージックビデオ|配信|ドロップ)")


def _norm_title(s: str) -> str:
    """リリースタイトルの重複判定用の弱正規化。"""
    s = (s or "").lower().strip()
    s = re.sub(r"[\s\-_.,'\"「」『』()（）]+", "", s)
    return s


def _candidate_id(pid: int, rel_title: str, year: str) -> str:
    raw = f"{pid}|{_norm_title(rel_title)}|{year}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _load_processed() -> set:
    seen = set()
    if PROCESSED.exists():
        for line in PROCESSED.read_text(errors="replace").splitlines():
            try:
                pid = json.loads(line).get("post_id")
                if pid is not None:   # None を入れると post_id 欠落の速報を全スキップしてしまう
                    seen.add(pid)
            except Exception:
                pass
    return seen


def _load_candidate_ids() -> set:
    ids = set()
    if CANDIDATES.exists():
        for line in CANDIDATES.read_text(errors="replace").splitlines():
            try:
                ids.add(json.loads(line).get("candidate_id"))
            except Exception:
                pass
    return ids


def _llm_extract(title: str, year_hint: str) -> dict | None:
    """1件の速報タイトルから release 構造を抽出。release でなければ None。

    KPJ_TEST_MODE / cost_guard 非許可時は None(skip)。
    """
    if os.environ.get("KPJ_TEST_MODE"):
        return None
    try:
        from lib.anthropic_cost_guard import guard_before_call, log_usage
        if not guard_before_call("idol_wiki_release_extract"):
            return None
    except ImportError:
        log_usage = None  # type: ignore

    import anthropic
    client = anthropic.Anthropic()
    prompt = f"""次のK-POP速報タイトルから「公式の音楽リリース事実」だけを抽出してください。

タイトル: {title}
（このニュースの年: {year_hint}）

ルール:
- リリース(シングル/アルバム/ミニアルバム/EP/正規アルバム/タイトル曲)の発表・発売・公開のみ対象。
- ファンミ/ツアー/受賞/ゴシップ/熱愛/SNS/コラボ出演/予告のみ、は対象外 → release:false。
- 憶測・未確定(噂/予定/可能性/〜か)は対象外 → release:false。
- 作品名がタイトルから明確に読み取れない場合は release:false。
- 推測で作品名や年を補わない。タイトルに無い情報は書かない。

JSONのみ返す:
{{"release": true/false, "release_title": "作品名(原語表記優先)", "release_type": "シングル|ミニアルバム(EP)|正規アルバム|デジタルシングル|タイトル曲 のいずれか", "release_year": "YYYY", "evidence": "タイトル中の根拠語句", "confidence": 0.0-1.0}}"""
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        if log_usage:
            try:
                log_usage("idol_wiki_release_extract", model="claude-sonnet-4-6", usage=resp.usage)
            except Exception:
                pass
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        return json.loads(m.group(0))
    except Exception as e:
        print(f"  [extract] LLM err: {e}", file=sys.stderr)
        return None


def extract(artists: list[str], dry_run: bool, max_llm: int = 0) -> dict:
    """max_llm>0 のとき、1回の実行での LLM 呼び出し回数を上限で打ち切る
    (日次cronでコスト集中を防ぐ。未処理分は次回に回る=冪等marker未記録なので再処理される)。"""
    processed = _load_processed()
    existing_cands = _load_candidate_ids()
    want = {resolve(a)["post_id"] for a in artists if resolve(a)} if artists else None

    llm_calls = 0
    new_cands = []
    new_processed = []
    stats = {"scanned": 0, "skipped_processed": 0, "unresolved": 0, "llm_capped": 0,
             "not_release": 0, "speculation": 0, "no_hint": 0, "candidates": 0, "dup": 0}

    for line in BREAKING_LOG.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        pid_breaking = d.get("post_id")
        title = d.get("title", "")
        artist = d.get("artist", "")
        year_hint = (d.get("date") or "")[:4]

        # 冪等: 既処理の速報はスキップ
        if pid_breaking in processed:
            stats["skipped_processed"] += 1
            continue

        # アーティスト解決(G0)
        r = resolve(artist)
        if not r:
            stats["unresolved"] += 1
            # unresolved は marker に残さない: 後で artist_resolver の索引を再構築
            # (idol_artist 追加 / 別名追加)すれば再処理できるようにする。
            continue
        idol_pid = r["post_id"]
        if want is not None and idol_pid not in want:
            continue  # 対象アーティスト外(検証スコープ)

        stats["scanned"] += 1

        # 安価な事前フィルタ(G1の一部) — LLM呼び出し前に明らかな非リリースを弾く
        if SPECULATION_RE.search(title):
            stats["speculation"] += 1
            new_processed.append({"post_id": pid_breaking, "outcome": "speculation"})
            continue
        if not RELEASE_HINT_RE.search(title):
            stats["no_hint"] += 1
            new_processed.append({"post_id": pid_breaking, "outcome": "no_release_hint"})
            continue

        # 日次上限: LLM呼び出し回数が上限に達したら、この速報は marker を残さず打ち切る
        # (次回実行で再処理される)。事前フィルタを通った=LLM対象のものだけを数える。
        if max_llm and llm_calls >= max_llm:
            stats["llm_capped"] += 1
            continue

        # LLM 構造抽出
        llm_calls += 1
        ext = _llm_extract(title, year_hint)
        if not ext or not ext.get("release"):
            stats["not_release"] += 1
            new_processed.append({"post_id": pid_breaking, "outcome": "not_release"})
            continue
        rel_title = (ext.get("release_title") or "").strip()
        rel_year = str(ext.get("release_year") or year_hint).strip()[:4]
        if not rel_title or not re.match(r"^\d{4}$", rel_year):
            stats["not_release"] += 1
            new_processed.append({"post_id": pid_breaking, "outcome": "incomplete"})
            continue

        cid = _candidate_id(idol_pid, rel_title, rel_year)
        if cid in existing_cands:
            stats["dup"] += 1
            new_processed.append({"post_id": pid_breaking, "outcome": "dup_candidate"})
            continue
        existing_cands.add(cid)

        cand = {
            "candidate_id": cid,
            "idol_post_id": idol_pid,
            "artist_canonical": r["canonical"],
            "release_title": rel_title,
            "release_type": ext.get("release_type", ""),
            "release_year": rel_year,
            "evidence": ext.get("evidence", ""),
            "confidence": ext.get("confidence", 0),
            "source_breaking_post_id": pid_breaking,
            "source_title": title,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        new_cands.append(cand)
        new_processed.append({"post_id": pid_breaking, "outcome": "extracted"})
        stats["candidates"] += 1

    # 書き込み(dry-run なら表示のみ)
    if dry_run:
        print(f"[dry-run] 候補 {len(new_cands)}件(キュー未書込):")
        for c in new_cands:
            print(f"  pid{c['idol_post_id']} {c['artist_canonical']}: "
                  f"{c['release_year']} 「{c['release_title']}」 [{c['release_type']}] "
                  f"conf={c['confidence']} ← {c['source_title'][:40]}")
    else:
        with CANDIDATES.open("a") as f:
            for c in new_cands:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        with PROCESSED.open("a") as f:
            now = datetime.now(timezone.utc).isoformat()
            for p in new_processed:
                f.write(json.dumps({**p, "processed_at": now}, ensure_ascii=False) + "\n")
        print(f"候補 {len(new_cands)}件をキューに追加 → {CANDIDATES.name}")

    print(f"統計: {stats}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist", default="", help="対象アーティスト(カンマ区切り、空=全件)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="1回のLLM呼び出し上限(0=無制限)")
    args = ap.parse_args()
    artists = [a.strip() for a in args.artist.split(",") if a.strip()]
    extract(artists, args.dry_run, max_llm=args.max)
