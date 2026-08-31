#!/usr/bin/env python3
"""wp_aioseo_posts.description が欠落している公開記事にメタ説明を一括生成する。

post_audit.sh [3] と同一の生成ロジック（ノイズ除去 → 文境界で110-130字整形）を
使い、記事本文には一切触れず wp_aioseo_posts のみを更新する。

REST の meta._aioseo_description は register_meta されておらず書き込みが
黙殺されるため、DB経由でしか設定できない（post_audit.sh の修正と同じ理由）。

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
    cmd = (RW if write else RO) + ["db", "query", sql]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def fetch_b64(sql):
    """base64値を1カラムだけ取得する。

    wp-ro の出力はヘッダ行が付き、長い値は折り返される。ヘッダを除いた
    全行を連結し、base64の文字集合以外を落としてからデコードする
    （複数カラムを同時に取ると折返しでタブ境界が壊れるため必ず1カラム）。
    """
    out = db_query(sql).splitlines()[1:]
    raw = "".join(out)
    # 折返しはリテラルの \n（バックスラッシュ+n）で入る。先に落とさないと
    # 'n' がbase64文字として残りデコードが壊れる
    raw = raw.replace("\\n", "")
    raw = re.sub(r'[^A-Za-z0-9+/=]', '', raw)
    return base64.b64decode(raw).decode("utf-8", "replace")


def build_description(content, title):
    """post_audit.sh [3] と同じ整形規則でメタ説明を組み立てる。"""
    content = re.sub(r'(?is)<(figcaption|script|style|table)[^>]*>.*?</\1>', ' ', content)
    text = re.sub(r'<[^>]+>', ' ', content)
    text = re.sub(r'&[a-z]+;|&#\d+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # 定型ラベルは先頭だけでなく本文の途中にも現れる（関連記事見出しの残骸など）
    text = re.sub(
        r'(画像[:：][^。]{0,30}?より|出典[:：][^。]{0,40}|参考[:：][^。]{0,40}'
        r'|この記事の\d*行?まとめ|目次|関連記事)\s*', ' ', text)
    # 本文冒頭がタイトルの繰り返しなら落とす（メタ説明での重複を避ける）
    t = title.strip()
    if t and text.startswith(t):
        text = text[len(t):]
    text = re.sub(r'\s+', ' ', text).strip()

    # 文単位で積み上げ、110字に届くまで足す
    sentences = [s.strip() for s in re.split(r'(?<=[。！？])', text) if s.strip()]
    out = ''
    for s in sentences:
        if len(out) >= 110:
            break
        if len(out) + len(s) > 130:
            continue          # 長すぎる文は飛ばし、後続の短い文で110字を狙う
        out += s
    # 文単位で110字に届かない場合は素朴に切り詰めて字数を確保する
    if len(out) < 110 and len(text) >= 110:
        out = text[:129] + '…'
    if len(out) < 50:
        out = title
    return out[:130]


def set_description_for_post(pid, desc: str | None = None) -> dict:
    """1記事のメタ説明を wp_aioseo_posts に書き、DB実値で検証して返す。

    2026-08-16: 公開直後にも同じ経路を使えるよう main() から切り出した。
    unified_publisher の REST(`meta._aioseo_description`)経由は AIOSEO が
    register_meta しないため黙って破棄され、しかも HTTP 200 が返るので
    「成功」に見えてしまう([[aioseo-desc-write-traps]] 罠1)。書き込みは必ず
    このDB経路を通し、戻り値でなく**DBから読み直した実値**で成否を判定する。
    """
    pid = int(pid)
    if desc is None:
        # desc 未指定なら本文から生成する。呼び出し側が用途特化の文面を
        # 持っている場合(チャート記事など本文が順位表で自動生成に向かない)は
        # それを渡してもらう。
        content = fetch_b64(f"SELECT TO_BASE64(post_content) FROM wp_posts WHERE ID={pid}")
        title = fetch_b64(f"SELECT TO_BASE64(post_title) FROM wp_posts WHERE ID={pid}")
        desc = build_description(content, title)
    if len(desc) < 50:
        return {"ok": False, "reason": f"生成失敗(短すぎ len={len(desc)})", "post_id": pid}

    # post_id は非UNIQUE のため行の有無で分岐(UPSERTは発火せず重複行を作る。罠2)
    exists = db_query(
        f"SELECT COUNT(*) FROM wp_aioseo_posts WHERE post_id={pid}"
    ).splitlines()[1].strip()
    # 値は base64 で渡し MySQL 側で復号する(クォート置換だけでは \' で閉じられる。罠3)
    b64 = base64.b64encode(desc.encode("utf-8")).decode("ascii")
    val = f"CONVERT(FROM_BASE64('{b64}') USING utf8mb4)"
    if exists != "0":
        q = (f"UPDATE wp_aioseo_posts SET description={val}, updated=NOW() "
             f"WHERE post_id={pid}")
    else:
        q = ("INSERT INTO wp_aioseo_posts (post_id,description,og_object_type,"
             "og_image_type,twitter_card,robots_default,created,updated) VALUES "
             f"({pid},{val},'default','default','default',1,NOW(),NOW())")
    db_query(q, write=True)

    # 書き込み後にDB実値を読み直して検証(HTTPやreturncodeを成功判定に使わない)
    actual = fetch_b64(
        f"SELECT TO_BASE64(COALESCE(description,'')) FROM wp_aioseo_posts WHERE post_id={pid}"
    )
    if len(actual) < 50:
        return {"ok": False, "reason": f"書込後のDB実値が短い(len={len(actual)})", "post_id": pid}
    return {"ok": True, "length": len(actual), "post_id": pid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sql = ("SELECT p.ID FROM wp_posts p LEFT JOIN wp_aioseo_posts a ON a.post_id=p.ID "
           "WHERE p.post_status='publish' AND p.post_type='post' "
           "AND (a.post_id IS NULL OR COALESCE(CHAR_LENGTH(a.description),0)<50) "
           "ORDER BY p.post_date DESC")
    if args.limit:
        sql += f" LIMIT {args.limit}"
    ids = [l.strip() for l in db_query(sql).splitlines()[1:] if l.strip().isdigit()]
    print(f"対象: {len(ids)}件 (apply={args.apply})", flush=True)

    ok = skipped = failed = 0
    for i, pid in enumerate(ids, 1):
        try:
            content = fetch_b64(f"SELECT TO_BASE64(post_content) FROM wp_posts WHERE ID={pid}")
            title = fetch_b64(f"SELECT TO_BASE64(post_title) FROM wp_posts WHERE ID={pid}")
            desc = build_description(content, title)

            if len(desc) < 50:
                skipped += 1
                print(f"[{i}/{len(ids)}] SKIP {pid} 生成失敗(短すぎ len={len(desc)})", flush=True)
                continue

            if args.apply:
                # post_id は非UNIQUEのため行の有無で分岐（重複行を作らない）
                exists = db_query(
                    f"SELECT COUNT(*) FROM wp_aioseo_posts WHERE post_id={pid}"
                ).splitlines()[1].strip()
                # 記事本文は外部ソース由来。sql_mode に NO_BACKSLASH_ESCAPES が
                # 無いため "'" の '' 置換だけでは \' で文字列を閉じられてしまう。
                # base64で渡しMySQL側で復号する（値が構文に影響しない）。
                b64 = base64.b64encode(desc.encode("utf-8")).decode("ascii")
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
            if i % 50 == 0 or i == len(ids):
                print(f"[{i}/{len(ids)}] ok={ok} skip={skipped} fail={failed}", flush=True)
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(ids)}] FAIL {pid}: {e}", flush=True)

    print(json.dumps({"total": len(ids), "ok": ok, "skipped": skipped,
                      "failed": failed, "applied": args.apply}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
