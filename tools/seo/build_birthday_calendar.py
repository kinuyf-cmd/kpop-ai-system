#!/usr/bin/env python3
"""K-POPアイドル誕生日カレンダー記事を生成(切り口C: DB資産再利用)。

Idol Wiki 123組の members_N_member_* メタから誕生日を集約し、月別の
誕生日一覧HTMLを生成する。検索需要(kpop 誕生日 4月/3月... = 月別)に直撃。
新規取材ゼロ・既存構造化データの再利用。

出力: /tmp/birthday_calendar.html(rwで post create する用)
読み取りは sudo -n kpop-wp-ro post meta list(www-data所有DBを安全参照)。
"""
import subprocess
import sys

RO = "/usr/local/sbin/kpop/kpop-wp-ro"
MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月",
          "7月", "8月", "9月", "10月", "11月", "12月"]


def ro(*args):
    return subprocess.run(["sudo", "-n", RO, *args],
                          capture_output=True, text=True).stdout


def meta_all(pid):
    """post meta を {key: value} で取得。

    既定の tab 区切り出力は3カラム: post_id<TAB>meta_key<TAB>meta_value。
    (CSV だと値内のカンマで崩れるため tab を使う。)
    """
    out = ro("post", "meta", "list", str(pid))
    d = {}
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        key, val = cols[1].strip(), cols[2].strip()
        if key in ("meta_key",):  # ヘッダ行
            continue
        d[key] = val
    return d


def main():
    ids = [s for s in sys.argv[1:] if s.isdigit()]
    if not ids:
        print("usage: build_birthday_calendar.py <id> [id...]", file=sys.stderr)
        sys.exit(2)

    # by_month[month_index] = list of (day, member, group)
    by_month = {i: [] for i in range(12)}
    total = 0
    for pid in ids:
        m = meta_all(pid)
        group = ro("post", "get", pid, "--field=post_title").strip()
        try:
            n = int(m.get("members", "0") or 0)
        except ValueError:
            n = 0
        for i in range(n):
            name = m.get(f"members_{i}_member_name", "").strip()
            bday = m.get(f"members_{i}_member_birthday", "").strip()
            if not name or len(bday) != 8 or not bday.isdigit():
                continue
            mm = int(bday[4:6])
            dd = int(bday[6:8])
            if not (1 <= mm <= 12 and 1 <= dd <= 31):
                continue
            by_month[mm - 1].append((dd, name, group))
            total += 1

    # HTML 組み立て
    parts = []
    parts.append(
        "<p>「推しの誕生日はいつ?」「今月が誕生日のK-POPアイドルは誰?」——"
        "そんな疑問に答える、K-POPアイドルの誕生日カレンダーです。"
        "当サイトのアイドルWikiに掲載するグループのメンバーを、誕生日の月別に"
        "一覧にまとめました。推しの誕生日のお祝い準備や、同じ誕生日のアイドル探しに"
        "お使いください。</p>")

    parts.append("<h2>K-POPアイドル誕生日カレンダーとは?使い方</h2>")
    parts.append(
        "<p>このページは、K-POPに詳しくない初心者の方でも「いつ誰の誕生日か」が"
        "ひと目で分かるようにまとめた早見表です。月ごとにメンバーの誕生日(日付)と"
        "所属グループを掲載しているので、推しの誕生日チェックはもちろん、"
        f"「自分と同じ誕生日のアイドルは?」という探し方もできます。現在およそ{total}名分の"
        "誕生日を掲載しており、データは随時更新していきます。</p>")
    parts.append(
        "<p>誕生日は、推し活の中でも特別なイベント。ファンダムでは誕生日に合わせて"
        "カフェイベント(センイルカフェ)や広告出稿などのお祝いが行われることもあります。"
        "まずはこのカレンダーで推しの誕生日を確認し、お祝いの準備に役立ててください。</p>")

    # 月別セクション
    parts.append("<h2>月別K-POPアイドル誕生日一覧</h2>")
    parts.append("<p>各月の誕生日を、日付順に並べています。気になる月をチェックしてみてください。</p>")
    for mi in range(12):
        rows = sorted(by_month[mi], key=lambda x: x[0])
        if not rows:
            continue
        parts.append(f"<h3>{MONTHS[mi]}生まれのK-POPアイドル</h3>")
        parts.append(f'<table>\n<caption>{MONTHS[mi]}が誕生日のK-POPアイドル</caption>')
        parts.append('<thead>\n<tr><th scope="col">誕生日</th>'
                     '<th scope="col">メンバー</th><th scope="col">グループ</th></tr>\n</thead>\n<tbody>')
        for dd, name, group in rows:
            parts.append(f"<tr><td>{MONTHS[mi]}{dd}日</td><td>{name}</td><td>{group}</td></tr>")
        parts.append("</tbody>\n</table>")

    # ペルソナ② ファン向け + 内部リンク
    parts.append("<h2>推しの誕生日をもっと楽しむには</h2>")
    parts.append(
        "<p>推しの誕生日が分かったら、プロフィールやメンバー構成もチェックしてみましょう。"
        "当サイトの<a href=\"https://www.kpopjournal.tokyo/artists/\">アイドルWiki</a>では、"
        "各グループのデビュー日・事務所・ファンダム名・メンバー一覧などの基本情報を"
        "まとめています。誕生日とあわせてプロフィールを押さえると、推し活がさらに深まります。</p>")
    parts.append(
        "<p>韓国でセンイルイベントやカフェ巡りを計画するなら、"
        "<a href=\"https://www.kpopjournal.tokyo/seoul-kpop-pilgrimage-guide-spring-2026-cafes-popups-spots/\">"
        "ソウルK-POP聖地巡礼ガイド</a>も参考になります。</p>")

    parts.append("<h2>まとめ｜誕生日カレンダーで推し活の予定を立てよう</h2>")
    parts.append(
        "<p>K-POPアイドルの誕生日を月別にまとめたカレンダーを紹介しました。"
        "推しの誕生日のお祝い準備や、同じ誕生日のアイドル探しにぜひご活用ください。"
        "掲載メンバーは順次追加していく予定です。各グループの詳しいプロフィールは"
        "アイドルWikiで確認できます。</p>")

    html = "\n".join(parts)
    open("/tmp/birthday_calendar.html", "w", encoding="utf-8").write(html)
    import re
    plain = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html))
    print(f"生成完了: /tmp/birthday_calendar.html")
    print(f"  掲載メンバー数: {total} / 本文字数: {len(plain)} / H2: {html.count('<h2>')} / 表: {html.count('<table>')}")


if __name__ == "__main__":
    main()
