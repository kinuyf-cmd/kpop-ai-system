#!/usr/bin/env python3
"""idol_artist(Idol Wiki)のAIOSEOメタ説明を ACF データから生成する。

Idol Wiki は本文(post_content)が0字でACF表示のため、Googleがスニペットを
作れる説明文が存在しない。直近28日で imp2,110を獲得しながらCTR0.38%と
低いのはこれが主因。

生成の優先順:
  1. ACF `artist_summary`（122/123組にある良質な要約）を文境界で110-130字に整形
  2. 無い場合のみ 名前/所属/デビュー日/メンバー数 からテンプレ合成

書き込みは wp_aioseo_posts へ直接。REST の meta 経由は register_meta されて
おらず黙殺されるため使えない（詳細は post_audit.sh [3] と同じ理由）。
値はbase64で渡しMySQL側で復号する（SQLインジェクション対策）。

  --limit N   処理件数の上限
  --apply     実際に書き込む（既定はdry-run）
"""
import argparse
import base64
import json
import re
import subprocess
import sys

RO = ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro"]
RW = ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-rw.sh"]


def db_query(sql, write=False):
    r = subprocess.run((RW if write else RO) + ["db", "query", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def fetch_b64(sql):
    """base64値を1カラムだけ取得する。

    wp-ro の出力はヘッダ行付きで、長い値は「リテラルの \\n」で折り返される。
    先にそれを落とさないと 'n' がbase64文字として残りデコードが壊れる。
    複数カラムを同時に取るとタブ境界が壊れるので必ず1カラム。
    """
    out = db_query(sql).splitlines()[1:]
    raw = "".join(out).replace("\\n", "")
    raw = re.sub(r'[^A-Za-z0-9+/=]', '', raw)
    if not raw:
        return ""
    return base64.b64decode(raw).decode("utf-8", "replace")


def meta(pid, key):
    return fetch_b64(
        f"SELECT TO_BASE64(meta_value) FROM wp_postmeta "
        f"WHERE post_id={pid} AND meta_key='{key}' LIMIT 1").strip()


def trim_to_range(text, lo=110, hi=130):
    """文境界で lo-hi 字に収める。届かなければ切り詰めで字数を確保する。"""
    text = re.sub(r'\s+', ' ', text).strip()
    out = ''
    for s in [s.strip() for s in re.split(r'(?<=[。！？])', text) if s.strip()]:
        if len(out) >= lo:
            break
        if len(out) + len(s) > hi:
            continue
        out += s
    if len(out) < lo and len(text) >= lo:
        out = text[:hi - 1] + '…'
    return out[:hi]


def build(pid, title):
    """artist_summary 優先、無ければACFからテンプレ合成。"""
    summary = meta(pid, "artist_summary")
    if len(summary) >= 50:
        d = trim_to_range(summary)
        if len(d) >= 50:
            return d, "summary"

    # フォールバック: 実データのみでテンプレ合成（推測は入れない）
    name_ja = meta(pid, "name_ja") or title
    agency = meta(pid, "agency")
    debut = meta(pid, "debut_date")
    members = meta(pid, "members")
    gtype = {"girl": "ガールズグループ", "boy": "ボーイズグループ"}.get(
        meta(pid, "group_type"), "アーティスト")

    parts = [f"{name_ja}のプロフィール。"]
    if re.fullmatch(r'\d{8}', debut or ''):
        y, m, dd = debut[:4], int(debut[4:6]), int(debut[6:])
        head = f"{agency}所属、" if agency else ""
        n = f"{members}人組" if (members or '').isdigit() and int(members) > 1 else ""
        parts.append(f"{head}{y}年{m}月{dd}日にデビューした{n}{gtype}。")
    elif agency:
        parts.append(f"{agency}所属の{gtype}。")
    parts.append("メンバー構成やデビュー以降のリリース履歴、出演作品、"
                 "ファンダム名などの基本情報をまとめて紹介します。")
    return trim_to_range("".join(parts)), "template"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sql = ("SELECT p.ID FROM wp_posts p LEFT JOIN wp_aioseo_posts a ON a.post_id=p.ID "
           "WHERE p.post_type='idol_artist' AND p.post_status='publish' "
           "AND (a.post_id IS NULL OR COALESCE(CHAR_LENGTH(a.description),0)<50) ORDER BY p.ID")
    if args.limit:
        sql += f" LIMIT {args.limit}"
    ids = [l.strip() for l in db_query(sql).splitlines()[1:] if l.strip().isdigit()]
    print(f"対象: {len(ids)}件 (apply={args.apply})", flush=True)

    ok = failed = 0
    src_count = {}
    for i, pid in enumerate(ids, 1):
        try:
            title = fetch_b64(f"SELECT TO_BASE64(post_title) FROM wp_posts WHERE ID={pid}")
            desc, src = build(pid, title)
            src_count[src] = src_count.get(src, 0) + 1
            if len(desc) < 50:
                failed += 1
                print(f"[{i}] SKIP {pid} 生成失敗 len={len(desc)}", flush=True)
                continue
            if not args.apply:
                print(f"[{i}] {pid} ({len(desc)}字/{src}) {title[:16]}: {desc[:60]}", flush=True)
            else:
                exists = db_query(
                    f"SELECT COUNT(*) FROM wp_aioseo_posts WHERE post_id={pid}"
                ).splitlines()[1].strip()
                b64 = base64.b64encode(desc.encode()).decode()
                val = f"CONVERT(FROM_BASE64('{b64}') USING utf8mb4)"
                if exists != "0":
                    q = (f"UPDATE wp_aioseo_posts SET description={val}, updated=NOW() "
                         f"WHERE post_id={pid}")
                else:
                    q = ("INSERT INTO wp_aioseo_posts (post_id,description,og_object_type,"
                         "og_image_type,twitter_card,robots_default,created,updated) VALUES "
                         f"({pid},{val},'default','default','default',1,NOW(),NOW())")
                db_query(q, write=True)
            ok += 1
        except Exception as e:
            failed += 1
            print(f"[{i}] FAIL {pid}: {e}", flush=True)

    print(json.dumps({"total": len(ids), "ok": ok, "failed": failed,
                      "sources": src_count, "applied": args.apply}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
