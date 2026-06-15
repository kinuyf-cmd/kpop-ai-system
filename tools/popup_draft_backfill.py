#!/usr/bin/env python3
"""popup_draft_backfill.py — 滞留 popup draft の一括是正(一回限り)

背景(2026-06-15):
  kbuzzlab が Let's Encrypt 新ルートで TLS 検証落ち → 5/30 以降 popup の
  良質ソースが止まり、薄い pops-in/PRTIMES だけが draft 量産。さらに
  2026-05-26 の「一律 draft 化」で公開工程が無く、23 件が draft 滞留した。

本ツールの処理(各 draft popup に対して):
  1. popup_source_url から live で原題を取り直す(fetcher の parser を再利用)
  2. build_popup_article で固有タイトルに是正
  3. popup_quality_gate 合格 → publish へ昇格 / 不合格 → draft 据え置き
  4. タイトルが変わったら wp_posts.post_title / 本文 info_box を更新

冪等: 既に publish 済 or 固有タイトル済はスキップ。DRY_RUN=1 で確認のみ。

使い方:
  DRY_RUN=1 venv_kpi/bin/python3 tools/popup_draft_backfill.py   # 確認
  venv_kpi/bin/python3 tools/popup_draft_backfill.py             # 実行
"""
from __future__ import annotations
import os
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DRY = bool(int(os.environ.get("DRY_RUN", "0")))

# to_post モジュールを読み込み(run_mysql / build_popup_article / gate / esc_sql を再利用)
spec = importlib.util.spec_from_file_location("p2p", ROOT / "lib" / "popup_event_to_post.py")
p2p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p2p)

# fetcher の parser を再利用して source_url → signal を作る
fspec = importlib.util.spec_from_file_location("pf", ROOT / "lib" / "popup_event_fetcher.py")
pf = importlib.util.module_from_spec(fspec)
fspec.loader.exec_module(pf)


def q(sql: str) -> str:
    return p2p.run_mysql(sql)


import html as _html
import re as _re
import ssl as _ssl
import urllib.request as _ur

_CA = ROOT / "data" / "ca" / "kpop_ca_bundle.pem"
_CTX = _ssl.create_default_context(cafile=str(_CA)) if _CA.is_file() else None


def fetch_og_title(url: str) -> str:
    """source_url の詳細ページから og:title を取り、媒体サフィックスを除いて返す。

    live フィード(一覧)がローテで落ちて signal 照合できない draft の救済用。
    取得失敗時は空文字。汎用タイトル是正にのみ使う(本文/会場は既存 ACF を尊重)。
    """
    if not url:
        return ""
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        h = _ur.urlopen(req, timeout=15, context=_CTX).read().decode("utf-8", "replace")
    except Exception:
        return ""
    m = _re.search(r'og:title["\'][^>]*content=["\'](.*?)["\']', h) \
        or _re.search(r"<title>(.*?)</title>", h, _re.S)
    if not m:
        return ""
    t = _html.unescape(m.group(1)).strip()
    # 媒体サフィックス(— POPAP / | pops in / ｜... 以降)を除去
    t = _re.split(r"\s*[—\-|｜]\s*(POPAP|pops ?in|PRTIMES)", t, flags=_re.I)[0].strip()
    if len(t) > 70:
        t = t[:67] + "…"
    return t


def get_draft_popups() -> list[dict]:
    """draft 状態の popup post を ID/title/source_url 付きで返す。"""
    sql = (
        "SELECT p.ID, p.post_title, "
        "(SELECT meta_value FROM wp_postmeta WHERE post_id=p.ID AND meta_key='popup_source_url' LIMIT 1) src "
        "FROM wp_posts p "
        "JOIN wp_term_relationships tr ON tr.object_id=p.ID "
        "JOIN wp_term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id "
        "JOIN wp_terms t ON t.term_id=tt.term_id "
        "WHERE t.slug='popup' AND p.post_type='post' AND p.post_status='draft' "
        "ORDER BY p.post_date DESC;"
    )
    out = []
    for line in q(sql).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].isdigit():
            out.append({"id": int(parts[0]), "title": parts[1], "src": parts[2]})
    return out


def signal_for_url(src_url: str) -> dict | None:
    """source_url を含む live シグナルを fetcher 全体から探して返す。

    pops-in / PRTIMES / kbuzzlab を一度収集し、source_url 一致を引く。
    (個別ページ再パースより、既存のテスト済み抽出を丸ごと使うのが安全)
    """
    sigs = []
    for fn in ("parse_popsin", "parse_prtimes", "parse_kbuzzlab"):
        fnc = getattr(pf, fn, None)
        if fnc is None:
            continue
        try:
            sigs.extend(fnc())
        except Exception as e:
            print(f"  [warn] {fn} 失敗: {e}")
    for s in sigs:
        if s.get("source_url") == src_url and s.get("type") == "popup":
            return s
    return None


def main() -> int:
    drafts = get_draft_popups()
    print(f"draft popup: {len(drafts)} 件")
    if not drafts:
        return 0

    # source_url → signal を 1 回の収集で引けるよう、先に全シグナルを集める
    print("live シグナル収集中(pops-in / PRTIMES / kbuzzlab)…")
    allsig = {}
    for fn in ("parse_popsin", "parse_prtimes", "parse_kbuzzlab"):
        fnc = getattr(pf, fn, None)
        if not fnc:
            continue
        try:
            for s in fnc():
                if s.get("type") == "popup" and s.get("source_url"):
                    allsig[s["source_url"]] = s
        except Exception as e:
            print(f"  [warn] {fn}: {e}")
    print(f"  シグナル {len(allsig)} 件取得")

    def is_generic(title: str) -> bool:
        t = title.strip()
        return t.endswith("ポップアップストア開催決定") or t.endswith("期間限定イベント情報")

    def draft_meta(pid: int) -> tuple[str, str]:
        """既存 draft の (period_start, address) を返す。"""
        out = q(
            "SELECT "
            f"(SELECT meta_value FROM wp_postmeta WHERE post_id={pid} AND meta_key='popup_period_start' LIMIT 1), "
            f"(SELECT meta_value FROM wp_postmeta WHERE post_id={pid} AND meta_key='popup_address' LIMIT 1);"
        )
        # run_mysql は先頭にヘッダ行(列名)を含む → データ行=最終非空行を採る。
        # mysql は NULL を文字列 "NULL" で返す → 空扱いに正規化。
        lines = [l for l in out.splitlines() if l.strip()]
        parts = lines[-1].split("\t") if lines else []
        def _norm(v: str) -> str:
            v = (v or "").strip()
            return "" if v == "NULL" else v
        return (_norm(parts[0]) if len(parts) > 0 else "",
                _norm(parts[1]) if len(parts) > 1 else "")

    n_pub = n_retitle = n_skip = 0
    for d in drafts:
        sig = allsig.get(d["src"])
        if not sig:
            # live シグナル無し。タイトルが既に固有 + 会場/期間があるなら そのまま publish。
            # (5/31 以前の良質 draft や、source ページがローテで落ちた現役 popup の救済)
            pstart, addr = draft_meta(d["id"])
            if not is_generic(d["title"]) and (pstart or addr):
                print(f"  id={d['id']} : 既存固有タイトル+開催情報 → PUBLISH(live不要)")
                n_pub += 1
                if not DRY:
                    q("UPDATE wp_posts SET post_status='publish', "
                      "post_modified=UTC_TIMESTAMP(), post_modified_gmt=UTC_TIMESTAMP() "
                      f"WHERE ID={d['id']};")
            elif is_generic(d["title"]) and (pstart or addr):
                # 汎用タイトルだが会場/期間あり → 詳細ページの og:title で固有化を試みる
                og = fetch_og_title(d["src"])
                if og and og.strip() != d["title"].strip():
                    print(f"  id={d['id']} : og回収 retitle→「{og[:38]}」+ PUBLISH")
                    n_retitle += 1
                    n_pub += 1
                    if not DRY:
                        q(f"UPDATE wp_posts SET post_title='{p2p.esc_sql(og)}', "
                          "post_status='publish', post_modified=UTC_TIMESTAMP(), "
                          f"post_modified_gmt=UTC_TIMESTAMP() WHERE ID={d['id']};")
                else:
                    print(f"  SKIP id={d['id']} : og回収失敗 — draft 据え置き")
                    n_skip += 1
            else:
                print(f"  SKIP id={d['id']} : live無し + 会場/期間なし — draft 据え置き")
                n_skip += 1
            continue
        new_title, body, _slug = p2p.build_popup_article(sig)
        ok, reason = p2p.popup_quality_gate(sig, new_title)
        status = "publish" if ok else "draft"
        changed = new_title.strip() != d["title"].strip()
        action = []
        if changed:
            action.append(f"retitle→「{new_title[:40]}」")
            n_retitle += 1
        if ok:
            action.append("PUBLISH")
            n_pub += 1
        else:
            action.append(f"draft据置({reason})")
        print(f"  id={d['id']} : {' / '.join(action)}")
        if DRY:
            continue
        # 本文 info_box を最新化 + タイトル是正 + status 昇格
        sets = [
            f"post_title='{p2p.esc_sql(new_title)}'",
            f"post_content='{p2p.esc_sql(body)}'",
            f"post_status='{status}'",
            "post_modified=UTC_TIMESTAMP()",
            "post_modified_gmt=UTC_TIMESTAMP()",
        ]
        q(f"UPDATE wp_posts SET {', '.join(sets)} WHERE ID={d['id']};")

    print(f"\n=== 結果: publish昇格={n_pub} / retitle={n_retitle} / skip={n_skip} "
          f"({'DRY_RUN' if DRY else '実行済'}) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
