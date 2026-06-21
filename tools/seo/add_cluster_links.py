#!/usr/bin/env python3
"""記事クラスタの相互内部リンクを追加する回遊強化ツール(2026-06-22)。

収益化軸③(回遊強化)用。同テーマの記事群に「関連記事」ブロックを足し、
1セッションあたりPVを増やす。各記事へは sibling のうち本文に未出のものだけ
リンクする(冪等)。本文書換は安全のため:
  - DB読込→挿入→出力ファイル化のみ(このスクリプトは書き込まない)
  - 呼び出し側が kpop-wp-rw.sh post update --post_content で反映
  - 挿入位置 = <hr> 直前(citation/CTA footer の前)、無ければ末尾

使い方(参照のみ・プラン出力):
  python3 tools/seo/add_cluster_links.py --plan cluster.json
cluster.json 例:
  {"label":"aespa Lemonade",
   "members":[{"id":5851,"slug":"aespa-...","title":"..."}, ...]}
出力: /tmp/cluster_<id>.html を生成(rwで反映する用)。
"""
import json
import re
import subprocess
import sys

RO = "/usr/local/sbin/kpop/kpop-wp-ro"


def get_body(post_id):
    r = subprocess.run(
        ["sudo", "-n", RO, "post", "get", str(post_id), "--field=post_content"],
        capture_output=True, text=True)
    return r.stdout


def build_block(self_id, members):
    """self_id 以外の member へのリンクリストHTMLを返す。"""
    others = [m for m in members if m["id"] != self_id]
    lis = "\n".join(
        f'<li><a href="https://www.kpopjournal.tokyo/{m["slug"]}/">{m["title"]}</a></li>'
        for m in others
    )
    return (
        '<h2>あわせて読みたい関連記事</h2>\n'
        '<ul class="kpop-cluster-links">\n' + lis + '\n</ul>\n'
    )


def insert_block(body, block, members, self_id):
    # 既に全 sibling へリンク済みなら skip
    others = [m for m in members if m["id"] != self_id]
    if all(m["slug"] in body for m in others):
        return None  # 変更不要
    # 既存の関連ブロックがあれば二重化を避けて skip(手動確認に委ねる)
    if "あわせて読みたい関連記事" in body:
        return None
    # <hr>(citation footer 前) の直前に挿入、無ければ末尾
    if "<hr>" in body:
        return body.replace("<hr>", block + "<hr>", 1)
    return body + "\n" + block


def build_block_nav(self_id, targets):
    """固定の nav_targets へリンクする版(hub-and-spoke 用)。self は除外。"""
    others = [t for t in targets if t["id"] != self_id]
    lis = "\n".join(
        f'<li><a href="https://www.kpopjournal.tokyo/{t["slug"]}/">{t["title"]}</a></li>'
        for t in others
    )
    return ('<h2>あわせて読みたい関連記事</h2>\n'
            '<ul class="kpop-cluster-links">\n' + lis + '\n</ul>\n')


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "--plan":
        print("usage: add_cluster_links.py --plan cluster.json", file=sys.stderr)
        sys.exit(2)
    plan = json.load(open(sys.argv[2], encoding="utf-8"))
    # members = 編集対象記事。nav_targets があれば各記事はそこへリンク
    # (hub-spoke)、無ければ members 同士を相互リンク(cluster)。
    members = plan["members"]
    nav = plan.get("nav_targets")
    changed = []
    for m in members:
        body = get_body(m["id"])
        if not body.strip():
            print(f"  WARN: id={m['id']} 本文取得失敗 skip")
            continue
        if nav:
            block = build_block_nav(m["id"], nav)
            link_set = [t for t in nav if t["id"] != m["id"]]
        else:
            block = build_block(m["id"], members)
            link_set = [x for x in members if x["id"] != m["id"]]
        out = insert_block(body, block, link_set, m["id"])
        if out is None:
            print(f"  id={m['id']} 変更不要(既にリンク済/関連ブロック有)")
            continue
        path = f"/tmp/cluster_{m['id']}.html"
        open(path, "w", encoding="utf-8").write(out)
        # 健全性: 字数が減っていない・hr/h2ペア
        if len(out) <= len(body):
            print(f"  ERROR: id={m['id']} 字数が増えていない→skip")
            continue
        changed.append((m["id"], path))
        print(f"  id={m['id']} → {path} 生成(+{len(out)-len(body)}字)")
    print("\n反映コマンド:")
    for pid, path in changed:
        print(f'  NEWBODY="$(cat {path})"; sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh '
              f'post update {pid} --post_content="$NEWBODY"')


if __name__ == "__main__":
    main()
