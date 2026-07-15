#!/usr/bin/env python3
"""verify_releases.py — リリース候補を Wikipedia + web検索で非破壊照合する(G4)。

2段照合(精度改善 2026-06-03):
  1. 日本語 Wikipedia 記事に「作品名」「年」が両方出現 → verified(無料・速い)。
  2. Wikipedia で引けない場合のみ、web検索LLMで信頼メディアに「アーティスト+作品名+年」が
     裏取れるか照合 → 取れれば verified。新作・韓国語タイトル(Wikipedia未反映)を救う。
  3. どちらでも取れない → unverifiable(reject でなく review 行き。誤報告しない)。
  - 作品名はあるが年が違う → year_mismatch(要レビュー)。
書き込みは一切しない(候補キューの status と verify_note を更新するのみ)。

Usage:
    venv_kpi/bin/python3 tools/idol_wiki/releases/verify_releases.py            # 照合
    venv_kpi/bin/python3 tools/idol_wiki/releases/verify_releases.py --no-web   # Wikipediaのみ
    venv_kpi/bin/python3 tools/idol_wiki/releases/verify_releases.py --dry-run
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # 同ディレクトリの _queue_io
BASE = Path(__file__).resolve().parents[3]
try:
    from dotenv import load_dotenv
    load_dotenv(str(BASE / ".env"))  # ANTHROPIC_API_KEY(web照合LLM用)
except ImportError:
    pass
CANDIDATES = BASE / "data" / "idol_wiki_release_candidates.jsonl"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"
UA = {"User-Agent": "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"}


def _web_verify(artist: str, title: str, year: str) -> tuple[bool, str]:
    """web検索LLMで「アーティスト+作品名+年」を信頼メディアに照合(G4第2段)。

    Returns (confirmed, note)。KPJ_TEST_MODE / cost_guard 非許可 / 例外時は (False, 理由)。
    誤報告を避けるため、LLMには「確実に裏取れた場合のみ true」と厳命する。
    """
    if os.environ.get("KPJ_TEST_MODE"):
        return False, "web照合skip(test mode)"
    try:
        from lib.anthropic_cost_guard import guard_before_call, log_usage
        if not guard_before_call("idol_wiki_release_verify"):
            return False, "web照合skip(cost guard)"
    except ImportError:
        log_usage = None  # type: ignore
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            f"K-POPアーティスト「{artist}」が{year}年に「{title}」という音楽作品"
            f"(アルバム/シングル/EP)をリリースした事実が、信頼できるメディアで確認できますか?\n"
            f"web_searchで確認し、JSONのみ返す: "
            f'{{"confirmed": true/false, "evidence": "確認できた媒体名と要点(なければ空)"}}\n'
            f"確実に裏が取れた場合のみ confirmed:true。曖昧・別作品・別年なら false。"
        )
        resp = client.messages.create(
            # 2026-07-15: Sonnet 5 移行。web_search裏取り+JSON判定タスクで思考不要のため
            # thinking を明示 disabled。
            model="claude-sonnet-5",
            max_tokens=500,
            thinking={"type": "disabled"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}],
        )
        if log_usage:
            try:
                log_usage("idol_wiki_release_verify", model="claude-sonnet-5", usage=resp.usage)
            except Exception:
                pass
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return False, "web照合: 判定不能"
        d = json.loads(m.group(0))
        if d.get("confirmed"):
            return True, f"web照合で確認: {d.get('evidence', '')[:80]}"
        return False, "web照合でも裏取れず"
    except Exception as e:
        return False, f"web照合エラー: {e}"


def fetch_wikitext(page: str) -> str | None:
    """ja.wikipedia の wikitext を取得(verify_birthdays_wikipedia.py と同実装)。"""
    try:
        url = ("https://ja.wikipedia.org/w/api.php?action=parse&page="
               + urllib.parse.quote(page)
               + "&prop=wikitext&format=json&formatversion=2&redirects=1")
        d = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25))
        return d.get("parse", {}).get("wikitext")
    except Exception:
        return None


def _run_wp(args: list[str]) -> str:
    return subprocess.run(["sudo", "-n", WP_RO] + args,
                          capture_output=True, text=True, check=False).stdout


def _title_variants(c: dict) -> list[str]:
    """作品名の照合バリアント(原語 + 英数字部分)。"""
    t = c["release_title"]
    variants = {t, t.strip()}
    # 括弧除去版
    variants.add(re.sub(r"[\(（].*?[\)）]", "", t).strip())
    # 英数字のみ抽出(ハングル作品名のローマ字併記対策は弱いが、英題はこれで拾う)
    asc = re.sub(r"[^A-Za-z0-9 ]", "", t).strip()
    if len(asc) >= 2:
        variants.add(asc)
    return [v for v in variants if len(v) >= 2]


def _wiki_page_candidates(pid: int) -> list[str]:
    """idol_artist の name_ja/en/ko から Wikipedia ページ名候補を作る。"""
    pages = []
    for mk in ("name_ja", "name_en", "name_ko"):
        v = _run_wp(["post", "meta", "get", str(pid), mk]).strip()
        if v:
            # 括弧内補足を落とす
            pages.append(re.sub(r"[\(（].*?[\)）]", "", v).strip())
    # post_title も
    t = _run_wp(["post", "get", str(pid), "--field=post_title"]).strip()
    if t:
        pages.append(t)
    seen, out = set(), []
    for p in pages:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def verify(dry_run: bool, use_web: bool = True) -> dict:
    if not CANDIDATES.exists():
        print("候補キューなし")
        return {}
    lines = [json.loads(l) for l in CANDIDATES.read_text().splitlines() if l.strip()]
    wt_cache: dict[int, str | None] = {}
    stats = {"checked": 0, "verified": 0, "year_mismatch": 0, "unverifiable": 0}

    for c in lines:
        if c.get("status") != "pending":  # dedup後にfreshだったものだけpending
            continue
        stats["checked"] += 1
        pid = c["idol_post_id"]
        if pid not in wt_cache:
            wt = None
            for page in _wiki_page_candidates(pid):
                wt = fetch_wikitext(page)
                if wt:
                    break
            wt_cache[pid] = wt
        wt = wt_cache[pid]

        if not wt:
            c["status"] = "unverifiable"
            c["verify_note"] = "Wikipedia記事を取得できず — 要人手確認"
            stats["unverifiable"] += 1
            continue

        # 作品名が記事中にあるか
        title_hit = any(v in wt for v in _title_variants(c))
        year_hit = c["release_year"] in wt

        if title_hit and year_hit:
            c["status"] = "verified"
            c["verify_note"] = f"Wikipedia に作品名・年({c['release_year']})の記載を確認"
            stats["verified"] += 1
        elif title_hit and not year_hit:
            c["status"] = "year_mismatch"
            c["verify_note"] = f"作品名はあるが年{c['release_year']}が一致せず — 要レビュー"
            stats["year_mismatch"] += 1
        else:
            # Wikipediaで引けない → web検索で信頼メディア照合(新作・韓国語タイトルを救う)
            confirmed = False
            web_note = ""
            if use_web:
                confirmed, web_note = _web_verify(
                    c["artist_canonical"], c["release_title"], c["release_year"])
            if confirmed:
                c["status"] = "verified"
                c["verify_note"] = web_note
                stats["verified"] += 1
                stats["verified_by_web"] = stats.get("verified_by_web", 0) + 1
            else:
                c["status"] = "unverifiable"
                c["verify_note"] = f"Wikipedia/web で確認できず — 要人手確認({web_note})"
                stats["unverifiable"] += 1

    if dry_run:
        print("[dry-run] 照合結果(キュー未更新):")
        for c in lines:
            if c.get("verify_note"):
                print(f"  [{c['status']}] pid{c['idol_post_id']} {c['artist_canonical']}: "
                      f"{c['release_year']}「{c['release_title']}」 — {c['verify_note']}")
    else:
        from _queue_io import merge_update  # flock+candidate_id マージで並行書込安全化
        merge_update(lines)
        print(f"キュー更新済 → {CANDIDATES.name}")
    print(f"統計: {stats}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-web", action="store_true", help="web検索フォールバックを無効化(Wikipediaのみ)")
    args = ap.parse_args()
    verify(args.dry_run, use_web=not args.no_web)
