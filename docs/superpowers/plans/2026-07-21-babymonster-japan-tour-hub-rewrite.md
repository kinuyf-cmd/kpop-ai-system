# BABYMONSTER 日本ツアーハブ記事(ID 415)リライト強化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存ハブ記事 ID 415 に日本ツアー全11公演の日程セクションを注入し、進行中ステータス・タイトル/メタ・クラスタ内部リンクを整えて「BABYMONSTER 日本 ツアー」検索意図に一致させる。

**Architecture:** WordPress本番DBの post_content を直接リライトする(新規記事は作らずカニバリ回避)。会場データはTEC全11公演のDB本文から機械抽出。書込は `kpop-wp-rw.sh`、検証は `kpop-wp-ro` + 本番curl 実レンダ。TDD形式ではなく「各タスク末尾に実測検証ゲート」を置く運用計画。

**Tech Stack:** WordPress (wp-cli via sudo wrapper), Python3, `lib/internal_links.py`, `lib/gsc_indexing.py`, curl(本番実レンダ検証)

## Global Constraints

- 対象は本番 post **ID 415** slug `babymonster-3-rd-15-6-20260414`。**slug は変更しない**(index/被リンク維持・404回避)。
- 本文の正解ソースは **DB本文**。curl抽出本文は破壊されるので書込元に使わない(`wp-body-source-of-truth-is-db-not-curl`)。
- `wp post update --post_content=-` によるstdin渡しは**禁止**(データ消失事故 `wp-post-update-stdin-piping-data-loss`)。本文は一時ファイル経由で直接渡す。
- 書込は `sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh <wpサブコマンド>`。読取検証は `sudo -n /usr/local/sbin/kpop/kpop-wp-ro <wpサブコマンド>`。OS系(rm/nginx等)のみowner。
- 内部リンク注入は**テキストノード限定**(img属性破壊バグ `autolink-injector-corrupts-img-attrs`)。
- **公開/更新のたび GSC 申請必須**: `venv_kpi/bin/python3 lib/gsc_indexing.py --url <URL>`(`always-gsc-submit-after-publish`)。
- 書込後は必ず**本番curlで実レンダ検証**(コード確認だけで結論しない `verify-rendered-output-not-just-code`)。本番URLは `https://www.kpopjournal.tokyo/`(www)。
- 会場の確定データは設計書の11公演テーブルを正とする。手入力しない。

## 確定データ：全11公演

| # | 公演日 | 会場 | 都市 | TEC ID |
|---|--------|------|------|--------|
| 1 | 2026-07-08 | GLION ARENA KOBE | 神戸 | 2886 |
| 2 | 2026-07-09 | GLION ARENA KOBE | 神戸 | 2907 |
| 3 | 2026-07-28 | マリンメッセ福岡A館 | 福岡 | 2908 |
| 4 | 2026-07-29 | マリンメッセ福岡A館 | 福岡 | 2909 |
| 5 | 2026-08-01 | ぴあアリーナMM | 横浜 | 2911 |
| 6 | 2026-08-02 | ぴあアリーナMM | 横浜 | 2910 |
| 7 | 2026-08-11 | LaLa arena TOKYO-BAY | 千葉/東京ベイ | 2912 |
| 8 | 2026-08-12 | LaLa arena TOKYO-BAY | 千葉/東京ベイ | 2913 |
| 9 | 2026-08-16 | IGアリーナ | 愛知 | 2914 |
| 10 | 2026-09-22 | 京セラドーム大阪 | 大阪 | 2906 |
| 11 | 2026-09-23 | 京セラドーム大阪 | 大阪 | 2915 |

## File Structure

- `scratchpad/babymonster_tour_schedule.py` (Create) — TEC 11公演DB本文から日付/会場を機械抽出し、日程表HTMLセクションを生成する使い捨てスクリプト。
- `scratchpad/id415_body_original.html` (Create) — 書込前のDB本文バックアップ(ロールバック用)。
- `scratchpad/id415_body_new.html` (Create) — 注入後の新本文(書込元ファイル)。
- 本番 post 415 post_content / post_title (Modify) — DB書込。
- 本番 wp_aioseo_posts の 415 メタ (Modify) — AIOSEO title/description。
- 本番 post 12039, 9760 post_content (Modify) — ハブへの逆リンク注入。

---

### Task 1: 現本文バックアップ + 日程表HTML生成スクリプト

**Files:**
- Create: `scratchpad/babymonster_tour_schedule.py`
- Create: `scratchpad/id415_body_original.html`

**Interfaces:**
- Produces: 標準出力に日程表セクションHTML(`<h2>…</h2><table>…</table>`)。後続タスクがこれを本文へ挿入する。

- [ ] **Step 1: 現本文をバックアップ**

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get 415 --field=post_content > scratchpad/id415_body_original.html
wc -c scratchpad/id415_body_original.html   # 6480前後であること
```

- [ ] **Step 2: 日程表生成スクリプトを書く**

会場の確定データは本計画の11公演テーブルをスクリプト内に定数で持つ(TEC本文抽出は設計時に検証済みのため、実行時は確定データを正とする)。ステータスは今日と公演日の比較で決める。

```python
# scratchpad/babymonster_tour_schedule.py
import datetime, html

TODAY = datetime.date.today()

SHOWS = [
    ("2026-07-08", "GLION ARENA KOBE", "神戸"),
    ("2026-07-09", "GLION ARENA KOBE", "神戸"),
    ("2026-07-28", "マリンメッセ福岡A館", "福岡"),
    ("2026-07-29", "マリンメッセ福岡A館", "福岡"),
    ("2026-08-01", "ぴあアリーナMM", "横浜"),
    ("2026-08-02", "ぴあアリーナMM", "横浜"),
    ("2026-08-11", "LaLa arena TOKYO-BAY", "千葉(東京ベイ)"),
    ("2026-08-12", "LaLa arena TOKYO-BAY", "千葉(東京ベイ)"),
    ("2026-08-16", "IGアリーナ", "愛知"),
    ("2026-09-22", "京セラドーム大阪", "大阪"),
    ("2026-09-23", "京セラドーム大阪", "大阪"),
]

def status(d):
    day = datetime.date.fromisoformat(d)
    return "開催済" if day < TODAY else "チケット情報あり"

rows = []
for d, venue, city in SHOWS:
    dt = datetime.date.fromisoformat(d)
    wd = "月火水木金土日"[dt.weekday()]
    rows.append(
        f"<tr><td>{dt.month}月{dt.day}日({wd})</td>"
        f"<td>{html.escape(venue)}</td><td>{html.escape(city)}</td>"
        f"<td>{status(d)}</td></tr>"
    )

section = (
    '<p class="section-hook">日本ツアー、全公演の日程をここで一気に確認できます。</p>\n'
    "<h2>BABYMONSTER 日本ツアー2026 全公演日程｜神戸から大阪ドームまで全11公演</h2>\n"
    "<p>BABYMONSTERのワールドツアー日本公演は、"
    "<strong>2026年7月8日の神戸(GLION ARENA KOBE)を皮切りに、9月の京セラドーム大阪まで全11公演</strong>が開催されます。"
    "各公演の日程・会場は下記のとおりです(出典：イープラス)。</p>\n"
    "<table>\n<thead>\n<tr><th>公演日</th><th>会場</th><th>都市</th><th>ステータス</th></tr>\n</thead>\n<tbody>\n"
    + "\n".join(rows)
    + "\n</tbody>\n</table>\n"
    "<p>チケットの最新販売状況は各公演の出典元(イープラス)をご確認ください。"
    "神戸公演は全席完売で開幕し、ツアーは好調なスタートを切りました。</p>\n"
)

print(section)
```

- [ ] **Step 3: 生成して目視確認**

Run: `cd /home/aiuser/kpop-ai-system && python3 scratchpad/babymonster_tour_schedule.py`
Expected: 11行の`<tr>`を含むテーブルHTML。神戸2/福岡2/横浜2/東京ベイ2/愛知1/大阪2 の計11行。過去公演は「開催済」、未来公演は「チケット情報あり」。

- [ ] **Step 4: コミット(スクリプトのみ。DB書込は次タスク)**

```bash
cd /home/aiuser/kpop-ai-system
git add scratchpad/babymonster_tour_schedule.py
git commit -m "feat(seo): BABYMONSTER日本ツアー日程表HTML生成スクリプト"
```

---

### Task 2: ハブ本文への日程セクション注入 + 進行中サマリー反映

**Files:**
- Create: `scratchpad/id415_body_new.html`
- Modify: 本番 post 415 post_content

**Interfaces:**
- Consumes: Task 1 の日程表HTML、`scratchpad/id415_body_original.html`

- [ ] **Step 1: 新本文を組み立てる**

日程セクションを冒頭サマリー(`kpj-summary` div)直後、最初のH2の直前に挿入する。Pythonで文字列挿入(sed禁止・日本語崩れ回避)。

```python
# scratchpad/build_id415_body.py として作成して実行
orig = open("scratchpad/id415_body_original.html").read()
import subprocess
section = subprocess.run(
    ["python3", "scratchpad/babymonster_tour_schedule.py"],
    capture_output=True, text=True, check=True
).stdout

anchor = '<h2>「CHOOM」って何？'          # 最初のH2の直前に差し込む
assert anchor in orig, "アンカー不在——本文構造を再確認せよ"
new = orig.replace(anchor, section + anchor, 1)

# 進行中サマリーを3行まとめの最後に1行追加
summary_tail = "</li></ul></div>"       # kpj-summary の閉じ
add_li = "<li>【日本ツアー】2026年7月8日 神戸で開幕し全席完売。9月の京セラドーム大阪まで全11公演。</li>"
assert orig.count(summary_tail) >= 1
new = new.replace(summary_tail, add_li + summary_tail, 1)

open("scratchpad/id415_body_new.html", "w").write(new)
print("orig:", len(orig), "new:", len(new), "diff:", len(new)-len(orig))
```

Run: `cd /home/aiuser/kpop-ai-system && python3 scratchpad/build_id415_body.py`
Expected: diff が +800〜1500字程度。assert が全て通ること。

- [ ] **Step 2: 新本文の健全性チェック(タグ均衡・11会場)**

```bash
cd /home/aiuser/kpop-ai-system
grep -o '<tr>' scratchpad/id415_body_new.html | wc -l      # 12以上(既存表+11公演)
for v in 神戸 マリンメッセ ぴあアリーナ LaLa IGアリーナ 京セラ; do
  printf "%s: " "$v"; grep -o "$v" scratchpad/id415_body_new.html | wc -l
done
python3 -c "s=open('scratchpad/id415_body_new.html').read(); print('table open',s.count('<table>'),'close',s.count('</table>'))"
```

Expected: 6会場すべて1以上。`<table>`と`</table>`の数が一致。

- [ ] **Step 3: DBへ書込(直接渡し・stdin禁止)**

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh post update 415 \
  --post_content="$(cat scratchpad/id415_body_new.html)"
```

Expected: `Success: Updated post 415.`

- [ ] **Step 4: DB本文で書込結果を検証**

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get 415 --field=post_content | grep -c 'GLION ARENA KOBE'   # 1以上
sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get 415 --field=post_content | grep -oE '<h2[^>]*>[^<]*</h2>' # ツアー日程H2が増えている
```

Expected: GLION ヒット1以上、H2に「BABYMONSTER 日本ツアー2026 全公演日程」が出現。

- [ ] **Step 5: 本番curlで実レンダ検証**

```bash
cd /home/aiuser/kpop-ai-system
html=$(curl -s -A "Mozilla/5.0" "https://www.kpopjournal.tokyo/babymonster-3-rd-15-6-20260414/" --max-time 25)
for v in 神戸 マリンメッセ ぴあアリーナ LaLa IGアリーナ 京セラ; do printf "%s: " "$v"; echo "$html" | grep -oc "$v"; done
```

Expected: 6会場すべて本番HTMLにレンダされている(0が無いこと)。

- [ ] **Step 6: コミット**

```bash
cd /home/aiuser/kpop-ai-system
git add scratchpad/build_id415_body.py scratchpad/id415_body_original.html
git commit -m "feat(seo): ID415に日本ツアー全11公演日程セクション+進行中サマリー注入"
```

---

### Task 3: タイトル/AIOSEOメタの実日程補正

**Files:**
- Modify: 本番 post 415 post_title
- Modify: 本番 wp_aioseo_posts の 415 メタ

**Interfaces:**
- Consumes: なし(独立)

- [ ] **Step 1: 現タイトル/メタを控える(ロールバック用)**

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-ro post get 415 --field=post_title
sudo -n /usr/local/sbin/kpop/kpop-wp-ro db query \
  "SELECT title, description FROM wp_aioseo_posts WHERE post_id=415;" 2>/dev/null
```

Expected: 現タイトルに「6月ワールドツアー」を含むこと(補正対象の確認)。AIOSEO行が有ればtitle/descを記録。

- [ ] **Step 2: post_title を実日程へ補正**

「6月ワールドツアー」→「日本ツアー(7〜9月・全11公演)」に補正。CHOOM完全ガイドの文脈は残す。

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh post update 415 \
  --post_title="BABYMONSTERの3rdミニアルバム「CHOOM」完全ガイド｜全15形態・2026年日本ツアー全11公演まとめ"
```

Expected: `Success: Updated post 415.`

- [ ] **Step 3: AIOSEO description を日程反映に更新**

AIOSEO行が存在する場合のみ実行(Step1で確認)。存在しなければスキップし、その旨ログ。

```bash
cd /home/aiuser/kpop-ai-system
sudo -n /usr/local/sbin/kpop/kpop-wp-rw.sh db query \
  "UPDATE wp_aioseo_posts SET description='BABYMONSTERの日本ツアー2026は7月8日神戸開幕〜9月京セラドーム大阪まで全11公演。全公演日程・会場・チケット情報とCHOOM全15形態を網羅。' WHERE post_id=415;"
```

Expected: Query OK。

- [ ] **Step 4: 実レンダで title/meta を検証**

```bash
cd /home/aiuser/kpop-ai-system
curl -s -A "Mozilla/5.0" "https://www.kpopjournal.tokyo/babymonster-3-rd-15-6-20260414/" --max-time 25 \
  | grep -oiE '<title>[^<]*</title>|<meta name="description"[^>]*>' | head -3
```

Expected: title/description に「日本ツアー」「全11公演」等が反映(キャッシュ次第で反映に時差あり。DB値が正なら可)。

- [ ] **Step 5: コミット(作業ログのみ・DB変更はコミット対象外)**

```bash
cd /home/aiuser/kpop-ai-system
git commit --allow-empty -m "chore(seo): ID415 title/AIOSEOメタを実日程(7-9月全11公演)へ補正"
```

---

### Task 4: クラスタ内部リンク(双方向・テキストノード限定)

**Files:**
- Modify: 本番 post 415(→12039, 9760 への発リンク)
- Modify: 本番 post 12039, 9760(→415 への逆リンク)

**Interfaces:**
- Consumes: Task 2 で更新済みの 415 本文

- [ ] **Step 1: internal_links.py の使い方を確認**

```bash
cd /home/aiuser/kpop-ai-system
sed -n '1,40p' lib/internal_links.py
python3 lib/internal_links.py --help 2>&1 | head -20 || true
```

Expected: テキストノード限定注入のCLIか関数を確認。CLIが無ければ手動アンカー挿入(Step2b)へ。

- [ ] **Step 2a: internal_links.py が使える場合 — 415↔個別記事を張る**

該当スクリプトのCLIに従い、415→12039(神戸完売)/9760(ドームツアー)、12039/9760→415 を注入。img属性を触らないこと。

- [ ] **Step 2b: CLIが無い場合 — 手動アンカー挿入(逆リンクのみ最小構成)**

12039/9760 の本文末尾に、ハブへの逆リンク段落を Python で追記(テキストノードとして追加、既存imgは触らない)。

```python
# scratchpad/add_backlink.py
import subprocess
HUB = "https://www.kpopjournal.tokyo/babymonster-3-rd-15-6-20260414/"
backlink = (f'<p>▶ BABYMONSTERの<a href="{HUB}">日本ツアー2026 全公演日程まとめはこちら</a></p>')
for pid in (12039, 9760):
    body = subprocess.run(
        ["sudo","-n","/usr/local/sbin/kpop/kpop-wp-ro","post","get",str(pid),"--field=post_content"],
        capture_output=True, text=True, check=True).stdout
    if "日本ツアー2026 全公演日程まとめはこちら" in body:
        print(pid, "already linked, skip"); continue
    new = body + "\n" + backlink
    open(f"scratchpad/body_{pid}_new.html","w").write(new)
    subprocess.run(
        ["sudo","-n","/usr/local/sbin/kpop/kpop-wp-rw.sh","post","update",str(pid),
         f"--post_content={new}"], check=True)
    print(pid, "linked")
```

Run: `cd /home/aiuser/kpop-ai-system && python3 scratchpad/add_backlink.py`
Expected: 各post「linked」。既にあればskip。

- [ ] **Step 3: 実レンダで内部リンク+img健全性を検証**

```bash
cd /home/aiuser/kpop-ai-system
for slug in babymonster-kobe-performance-sold-out babymonster-tour-dome-performance; do
  echo "=== $slug ==="
  curl -s -A "Mozilla/5.0" "https://www.kpopjournal.tokyo/$slug/" --max-time 25 \
    | grep -oE 'babymonster-3-rd-15-6-20260414' | head -1
done
# img属性破壊チェック(srcが空/壊れていないこと)
curl -s "https://www.kpopjournal.tokyo/babymonster-kobe-performance-sold-out/" --max-time 25 \
  | grep -oE '<img[^>]*src="[^"]*"' | head -3
```

Expected: 逆リンクがレンダされ、img の src が正常(空文字や壊れ属性が無い)。

- [ ] **Step 4: コミット**

```bash
cd /home/aiuser/kpop-ai-system
git add scratchpad/add_backlink.py 2>/dev/null; git commit --allow-empty -m "feat(seo): ハブ415と神戸/ドーム記事の双方向内部リンク"
```

---

### Task 5: GSC再申請 + 完了検証

**Files:**
- Modify: なし(申請のみ)

- [ ] **Step 1: 更新した全URLをGSC申請**

```bash
cd /home/aiuser/kpop-ai-system
for slug in babymonster-3-rd-15-6-20260414 babymonster-kobe-performance-sold-out babymonster-tour-dome-performance; do
  venv_kpi/bin/python3 lib/gsc_indexing.py --url "https://www.kpopjournal.tokyo/$slug/"
done
```

Expected: 各URLで申請成功ログ(GSC認証はローカル限定。失敗時はログを残し owner に申請依頼)。

- [ ] **Step 2: 最終実レンダ総点検**

```bash
cd /home/aiuser/kpop-ai-system
html=$(curl -s -A "Mozilla/5.0" "https://www.kpopjournal.tokyo/babymonster-3-rd-15-6-20260414/" --max-time 25)
echo "会場網羅:"; for v in 神戸 マリンメッセ ぴあアリーナ LaLa IGアリーナ 京セラ; do printf "  %s:" "$v"; echo "$html" | grep -oc "$v"; done
echo "dateModified:"; echo "$html" | grep -oE 'dateModified":"[^"]*"' | head -1
echo "日程H2:"; echo "$html" | grep -oE 'BABYMONSTER 日本ツアー2026 全公演日程[^<]*' | head -1
```

Expected: 6会場すべて1以上、dateModified が本日付近、日程H2が存在。

- [ ] **Step 3: 完了コミット**

```bash
cd /home/aiuser/kpop-ai-system
git commit --allow-empty -m "chore(seo): BABYMONSTER日本ツアーハブ415 リライト完了+GSC申請"
```

---

## 会期中フォロー(実装後の運用・別途手動)

福岡(7/28-29)、横浜(8/1-2)、東京ベイ(8/11-12)、愛知(8/16)、大阪(9/22-23) の各翌日:
1. `python3 scratchpad/babymonster_tour_schedule.py` 再生成(TODAY基準でステータスが自動で「開催済」化)
2. Task 2 の手順で 415 本文を差し替え
3. `lib/gsc_indexing.py --url` で再申請

## Self-Review 結果

- **Spec coverage**: 設計書のユニット①→Task2、②→Task2(サマリー)+Task5(dateModified)、③→Task3、④→Task4、会期中運用→末尾セクション、検証→各Task末尾+Task5。全カバー。
- **Placeholder scan**: TBD/TODO無し。各コードステップに実コードを記載。
- **Type consistency**: slug/post ID/URL/会場名は全タスクで統一(415, 12039, 9760, www ドメイン)。
- **既知の落とし穴を全て明示**: stdin書込禁止・DB本文が正・テキストノード限定・www URL・GSC申請必須・実レンダ検証。
