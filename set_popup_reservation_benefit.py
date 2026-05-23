#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""popup_detail(ACF prose)から 予約要否 / 特典 を抽出し popup_reservation / popup_benefit に冪等設定する。

抽出は lib/popup_reservation_benefit_parser.parse() に委譲(誤抽出・捏造ゼロ・verbatim)。
392/391判断 = A 丸ごと(parser出力そのまま)。Bモードのコンマ分割変換は採用しない
(オーナー決定 2026-05-23)。よって parser出力 = 格納値。

絶対方針:
  - 冪等: ON DUPLICATE KEY UPDATE。同じ prose なら何度流しても結果同一。
  - 非空のみ書く: parser が空を返したフィールドは UPDATE しない(=既存値を消さない/
    空で上書きしない)。曖昧は空 → 行非表示(テンプレ側)。
  - DB はオーナー sudo。a8/外部リンク/出典/本文は一切触らない(popup_reservation /
    popup_benefit メタの2キー限定)。

実行(www-data で。DB接続のため):
  サンプル(606/595 dry-run):  sudo -u www-data python3 set_popup_reservation_benefit.py --ids 606,595
  サンプル適用:                sudo -u www-data DRY_RUN=0 python3 set_popup_reservation_benefit.py --ids 606,595
  全 popup dry-run:            sudo -u www-data python3 set_popup_reservation_benefit.py
  全 popup 適用:               sudo -u www-data DRY_RUN=0 python3 set_popup_reservation_benefit.py

DRY_RUN は既定 1(計画表示のみ・DB書き込みなし)。--ids 省略時は category=popup の全 publish 記事。
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib.popup_event_to_post as P            # run_mysql / esc_sql / DB creds 自己ロード
from lib.popup_reservation_benefit_parser import parse

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
_HEADERS = {"ID", "meta_value", "post_title", "post_status", "term_id"}


def _mysql_rows(sql: str) -> list[str]:
    """`mysql -e` は出力時に1行目へ列名ヘッダを付ける。それを除いて値行だけ返す。"""
    out = P.run_mysql(sql)
    lines = out.splitlines()
    if lines and lines[0].strip() in _HEADERS:
        lines = lines[1:]
    return [ln for ln in lines if ln.strip()]


def popup_post_ids() -> list[int]:
    """category=popup の publish 記事 ID 一覧。"""
    sql = (
        "SELECT p.ID FROM wp_posts p "
        "JOIN wp_term_relationships tr ON tr.object_id=p.ID "
        "JOIN wp_term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id "
        "JOIN wp_terms t ON t.term_id=tt.term_id "
        "WHERE tt.taxonomy='category' AND t.slug='popup' "
        "AND p.post_type='post' AND p.post_status='publish' ORDER BY p.ID;"
    )
    return [int(x) for x in _mysql_rows(sql) if x.strip().isdigit()]


def get_meta(post_id: int, key: str) -> str:
    sql = (
        f"SELECT meta_value FROM wp_postmeta "
        f"WHERE post_id={post_id} AND meta_key='{key}' LIMIT 1;"
    )
    rows = _mysql_rows(sql)
    return rows[0] if rows else ""


def set_meta(post_id: int, key: str, val: str) -> None:
    """冪等 upsert。呼び出し側で非空を保証(空はここに来ない)。"""
    val_esc = P.esc_sql(val)
    sql = (
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) "
        f"VALUES ({post_id}, '{key}', '{val_esc}') "
        f"ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value);"
    )
    P.run_mysql(sql)


def process(post_id: int) -> dict:
    detail = get_meta(post_id, "popup_detail")
    parsed = parse(detail)                       # A 丸ごと: parser出力そのまま
    result = {"id": post_id, "detail_len": len(detail or ""), "written": [], "skipped_empty": []}
    for key in ("popup_reservation", "popup_benefit"):
        val = parsed[key]
        if not val:                              # 非空のみ書く(空で上書きしない)
            result["skipped_empty"].append(key)
            continue
        cur = get_meta(post_id, key)
        if cur == val:                           # 既に同値 → 冪等 no-op(無駄な書込回避)
            result["written"].append(f"{key}(同値・no-op)")
            continue
        if not DRY_RUN:
            set_meta(post_id, key, val)
        result["written"].append(f"{key}={val!r}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="対象 popup ID をカンマ区切りで(例 606,595)。省略時は popup 全件")
    args = ap.parse_args()

    if args.ids.strip():
        ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]
    else:
        ids = popup_post_ids()

    mode = "DRY_RUN(書込なし)" if DRY_RUN else "APPLY(DB書込)"
    print(f"=== set_popup_reservation_benefit [{mode}] 対象 {len(ids)}件 ===")
    n_written = n_empty = 0
    for pid in ids:
        r = process(pid)
        wrote = ", ".join(r["written"]) or "(書込対象なし)"
        print(f"[{pid}] detail={r['detail_len']}字 | 書込: {wrote} | 空skip: {','.join(r['skipped_empty']) or '-'}")
        n_written += len([w for w in r["written"] if "no-op" not in w])
        n_empty += len(r["skipped_empty"])
    print(f"--- 計: 書込予定 {n_written} / 空skip {n_empty} ({'適用済' if not DRY_RUN else 'dry-run・未適用'}) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
