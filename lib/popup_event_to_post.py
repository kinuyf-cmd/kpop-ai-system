#!/usr/bin/env python3
"""popup_event_to_post.py — M7 段階7.4(F + G 項目)

popup_event_fetcher.py が出力した signal JSON を読み、各 signal に対して
Layer 2 引用記事 (60% 引用率上限) を生成して stg WP に投稿する。

実行:
    python3 lib/popup_event_to_post.py <signals.json>             # 通常実行
    DRY_RUN=1 python3 lib/popup_event_to_post.py <signals.json>   # SQL のみ生成、投稿しない
    LIMIT=1   python3 lib/popup_event_to_post.py <signals.json>   # 最初の1件のみ処理

設計方針:
- 出典 URL 必須(HARD_FAIL、citation-rules SKILL.md §8 遵守)
- 引用率: タイトル翻訳 + リード文 + 出典抜粋 ≤ 60%(Layer 2 規定)
- ハルシネーション最小: signal の title / venue / date は原文ママ使用
- popup 型 → wp_posts (post_type=post, category=popup)
- event 型  → wp_posts (post_type=tribe_events、The Events Calendar 連携)
"""
from __future__ import annotations
import json
import os
import re
import hashlib
import sys
import subprocess
import shlex
import tempfile
import urllib.parse
import ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path

DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))

# uploads(www-data 所有)への書込は cron 実行ユーザ(aiuser)では EPERM になるため、
# サムネ取込は www-data 権限ラッパー経由で行う(2026-06-16 根治。
# [[popup-cron-thumbnail-aiuser-write-fail]])。
WP_RW = "/usr/local/sbin/kpop/kpop-wp-rw.sh"
LIMIT = int(os.environ.get("LIMIT", "0"))

# サムネ画像取得用 SSL コンテキスト。kbuzzlab は Let's Encrypt 新ルート
# (ISRG Root YR)未収録のため、fetcher と同じ独自 CA バンドルを使う
# (2026-06-15: 画像 DL 経路の検証失敗を修正。bundle 不在時はデフォルト検証)。
_CA_BUNDLE = Path(__file__).resolve().parent.parent / "data" / "ca" / "kpop_ca_bundle.pem"
try:
    _IMG_SSL_CTX = ssl.create_default_context(cafile=str(_CA_BUNDLE)) if _CA_BUNDLE.is_file() else None
except Exception:
    _IMG_SSL_CTX = None

# ─── 設定 ──────────────────────────────────────────────
# stg DB 接続(/tmp/wp_stg.txt から読む)
def _load_db_creds() -> dict:
    creds_file = Path("/tmp/wp_stg.txt")
    if not creds_file.exists():
        sys.exit("ERROR: /tmp/wp_stg.txt not found — cannot connect to stg DB")
    out = {}
    for line in creds_file.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out

DB = _load_db_creds()

def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")

def slugify(title: str, max_len: int = 70) -> str:
    """日本語タイトルからスラッグ生成。日本語は URL エンコード、ASCII は kebab-case。"""
    # ASCII keep, others URL-encode
    s = re.sub(r"[^\w\-]", "-", title.lower())[:max_len]
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not re.search(r"[a-z0-9]", s):
        # fall back to a stable hash-ish slug from full title
        s = "popup-" + str(abs(hash(title)))[:8]
    return s[:max_len]

def esc_sql(s: str | None) -> str:
    """MySQL '"' エスケープ。NULL は空文字。"""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "''")

# ─── 自動公開の品質ゲート ──────────────────────────────────
def popup_quality_gate(sig: dict, title: str) -> tuple[bool, str]:
    """popup を自動 publish してよいか判定する。戻り値 (公開可, 理由)。

    2026-05-26 に「無検査公開」を止めた事故対応の意図(空本文・薄い記事を出さない)を
    保ったまま自動公開を再開するためのゲート。合格 → publish、不合格 → draft 据え置き。

    合格条件(すべて満たす):
      1. 固有タイトル … 「{artist} ポップアップストア開催決定 / 期間限定イベント情報」
         のような汎用テンプレタイトルでない(= build_popup_article が原題を採用できた)。
      2. 開催情報あり … 会場 or 開催期間 or 住所 のいずれかが取れている
         (kbz_info / PRTIMES 抽出 由来)。日付/場所の無い「実質空」記事を publish しない。
    """
    artist = (sig.get("artist_keyword") or "").strip()
    generic = {f"{artist} ポップアップストア開催決定", f"{artist} 期間限定イベント情報"}
    if title.strip() in generic:
        return False, "汎用タイトル(原題を採用できず)"
    kbz = sig.get("kbz_info", {}) or {}
    has_info = any(str(kbz.get(k, "")).strip() for k in ("会場", "開催期間", "住所", "開催エリア"))
    if not has_info:
        return False, "会場/期間が空(実質情報なし)"
    return True, "固有タイトル+開催情報あり"


# ─── 記事テンプレート(Layer 2 引用率 60% 上限) ──────────
def build_popup_article(sig: dict) -> tuple[str, str, str]:
    """popup 型シグナルから記事(title, body_html, slug)を生成。

    本文構造(改修7: 本文は「短いリード文 + 出典リンク」のみ):
      1. リード(自社、短い): 何のポップアップか・詳細は下記(開催情報セクション)に集約
      2. 出典明記(必須): kpop-citation-source クラスで外部リンク
    詳細(期間/エリア/営業時間/住所/特典等)は ACF(add_popup_acf_meta)に格納し、
    テンプレ側の開催情報セクションが描画する。本文に引用ボックスで detail 全文を
    入れると ACF popup_detail と重複するため撤去(改修7・将来記事の重複防止)。
    引用率(Layer2 ≤60%)は本文が短くなることで一層余裕を持って遵守。
    """
    title_orig = sig["title"]
    artist = sig["artist_keyword"]
    source_url = sig["source_url"]
    media = sig["source_media"]

    # 自社タイトル(Layer 2: 原題は引用、自社は要約タイトル)
    # 出典はタイトルに含めない(本文の出典ボックス・カードのソース欄に別途明記する。
    # タイトルに「— 出典: xxx」を入れると一覧/個別で冗長になるため、2026-05-21 に撤去)。
    #
    # 2026-06-15: 原題ベースを全ソースに拡大(event 側 build_event_article と同方針)。
    # 旧実装は kbuzzlab だけ原題を使い、pops-in/PRTIMES は artist しか使わず
    # 「アイドル ポップアップストア開催決定」のような中身の無い汎用タイトルを量産
    # していた(SEO 価値も低い)。実際の原題は「BLACKPINK x たまごっち SEOUL
    # POP-UP STORE」のように固有名+具体名で十分良質なため、原題を正本に使う。
    #   ・原題が薄い(artist と同一/空)とき だけ 従来の汎用タイトルにフォールバック。
    clean_title = re.sub(r"\s*[|｜]\s*kbuzzlab.*$", "", title_orig or "", flags=re.I).strip()
    # サイト名・媒体サフィックス(| pops-in 等)も保険で除去
    clean_title = re.sub(r"\s*[|｜]\s*(pops-?in|PRTIMES).*$", "", clean_title, flags=re.I).strip()
    has_real_title = bool(clean_title) and clean_title.strip() != (artist or "").strip()
    if has_real_title:
        if len(clean_title) > 70:
            clean_title = clean_title[:67] + "…"
        new_title = clean_title
    elif "ポップアップ" in (title_orig or "") or "POP-UP" in (title_orig or "").upper() or "POPUP" in (title_orig or "").upper():
        new_title = f"{artist} ポップアップストア開催決定"
    else:
        new_title = f"{artist} 期間限定イベント情報"

    # リード文(自社、短く)。詳細は開催情報セクション(ACF)へ集約。
    lead = (
        f"<p>{esc_html(artist)} のポップアップ・期間限定イベント情報。"
        f"開催地・期間・営業時間などの詳細は下記の開催情報をご確認ください。</p>"
    )

    # 開催概要ボックス(2026-05-26 追加)。event 側と同様に、構造化データ(kbz_info)を
    # 本文に出して「本文がリード1文だけ=実質空」を防ぐ。ACF テーマ描画に依存せず、
    # post_content 自体に最低限の事実(会場/期間/営業時間/エリア)を持たせる。
    # 絵文字は mysql -e 経由で文字化けするためラベル文字 + CSS で表現(event と同方針)。
    kbz = sig.get("kbz_info", {}) or {}
    info_fields = [
        ("会場",   kbz.get("会場", "")),
        ("開催期間", kbz.get("開催期間", "")),
        ("開催エリア", kbz.get("開催エリア", "")),
        ("住所",   kbz.get("住所", "")),
        ("営業時間", kbz.get("営業時間", "")),
    ]
    info_rows = "".join(
        f'<li><span class="kpop-event-info-label">{esc_html(label)}</span>'
        f'<span class="kpop-event-info-value">{esc_html(str(val).strip())}</span></li>'
        for label, val in info_fields if str(val).strip()
    )
    info_box = ""
    if info_rows:
        info_box = (
            '<div class="kpop-event-info">'
            '<p class="kpop-event-info-head">開催概要</p>'
            f'<ul class="kpop-event-info-list">{info_rows}</ul>'
            '</div>'
        )

    # 出典リンクのみ(改修4・7: 引用ボックス/「詳細リリース…プレスリリース」は撤去)
    source_block = (
        f'<p class="kpop-citation-cta">'
        f'出典: <a class="kpop-citation-source" href="{esc_html(source_url)}" '
        f'rel="noopener nofollow" target="_blank">{esc_html(media)}</a></p>'
    )

    body = lead + "\n" + (info_box + "\n" if info_box else "") + source_block

    # M11.5 9.5.8-B: kbuzzlab は source_url 末尾セグメントから slug 生成(衝突防止)
    if sig.get("source_media") == "kbuzzlab":
        url_seg = re.search(r"/popup_event/([^/]+)/?", sig.get("source_url", ""))
        if url_seg:
            slug = "popup-" + slugify(url_seg.group(1).strip("-"))
        else:
            slug = slugify(f"popup-{title_orig[:30]}-{datetime.now().strftime('%Y%m%d')}")
    elif sig.get("source_media") == "PRTIMES":
        # タスク#27: PRTIMES の artist_keyword は日本語(例「韓国コスメ」)になりうる。
        # slugify は \w で日本語を残すため multibyte slug になり、pretty permalink が
        # 解決できず 404 になる(実測。kbuzzlab の ASCII slug は 200)。
        # → リリース URL の releaseId(常に ASCII・一意・安定)から slug を作る。
        rid = re.search(r"/p/(\d+\.\d+)\.html", sig.get("source_url", ""))
        if rid:
            slug = "popup-prtimes-" + rid.group(1).replace(".", "-")
        else:
            slug = "popup-prtimes-" + str(abs(hash(sig.get("source_url", ""))))[:10]
    else:
        slug = slugify(f"{artist}-popup-{datetime.now().strftime('%Y%m%d')}")
        # 2026-05-26: 旧保険は「ascii 文字が1つも無い場合」だけ発火したが、
        # 末尾の "-popup-YYYYMMDD" に ascii があるため artist が日本語(例「アイドル」)
        # でも発火せず「アイドル-popup-20260526」のような multibyte slug が量産され、
        # 同一 artist 名で slug 衝突(WP が -2/-3 を付与)+ pretty permalink 404 を招いた。
        # → slug に「非 ascii 文字が残っていれば」必ず ascii 安定 slug に置換する。
        #    source_url の md5 を使い、同一ソースは同一 slug(冪等)・別ソースは別 slug にする。
        if re.search(r"[^\x00-\x7f]", slug):
            seed = hashlib.md5((source_url or title_orig).encode("utf-8")).hexdigest()[:10]
            slug = f"popup-{datetime.now().strftime('%Y%m%d')}-{seed}"
    return new_title, body, slug

def build_event_article(sig: dict) -> tuple[str, str, str, str]:
    """event 型シグナルから記事(title, body_html, slug, start_date)を生成。

    event は The Events Calendar の tribe_events として登録するため
    開始日(start_date)も返す。
    """
    title_orig = sig["title"]
    artist = sig["artist_keyword"]
    source_url = sig["source_url"]
    media = sig["source_media"]
    start_date = sig.get("start_date", "")
    # 開演時刻(任意)。"HH:MM" 形式があれば metadata 用に start_dt へ合成する。
    # 本文の「公演日」は date のみ表示のままにし、時刻は Events Calendar のメタへ反映。
    start_time = (sig.get("start_time") or "").strip()
    venue = (sig.get("venue") or "").strip()

    # title がアーティスト名そのもの(enrichment で正式名を取れなかった)ケースは
    # 引用ブロックに入れても情報量ゼロ。公演名として表示する値を決める:
    #   ・title が artist と異なる(正式な公演名) → そのまま公演名に使う
    #   ・title == artist(薄い)          → 「{artist} 公演」を見出しに使い
    #                                        引用ブロックは出さない(空欄カード防止)
    has_real_title = bool(title_orig) and title_orig.strip() != artist.strip()
    event_name = title_orig.strip() if has_real_title else f"{artist} 公演"

    # PRTIMES 等の見出しは「煽り文 + 『正式公演名』 + 詳細解禁!」の構造が多く、
    # そのままだと公演名が長い宣伝文になり一覧/タイトルで読みにくい。
    # 『...』『...』や「...」で囲われた正式公演名があればそれを公演名に採る。
    if has_real_title:
        import re as _re
        _q = _re.findall(r'[『「]([^』」]{4,60})[』」]', event_name)
        if _q:
            # 最も長い引用部 = 正式公演名の可能性が高い
            event_name = max(_q, key=len).strip()

    # タイトルは公演名を活かして具体化する。
    #   ・正式な公演名あり → 「{artist}『{公演名}』ライブ・コンサート情報」
    #     (誤分類があっても実公演名がタイトルに出るので人間が気づける。
    #      例: 旧「IVE ライブ・コンサート情報」では BABY SHARK 公演の誤りに
    #      気づけなかった。新「IVE『BABY SHARK LIVE!』…」なら一目で発覚する)
    #   ・公演名が薄い(=artist と同一) → 従来どおり汎用タイトル
    # 「— 出典: {media}」接尾辞は一覧/カレンダーで冗長なので付けない(本文で明示)。
    if has_real_title:
        _pn = event_name
        # HTMLエンティティを戻す(&lt; 等が見出しに混入するのを防ぐ)
        import html as _html
        _pn = _html.unescape(_pn)
        # 公演名が artist で始まる場合の重複を除く(例 "aespa aespa JAPAN..." )
        if _pn.lower().startswith(artist.lower()):
            _pn = _pn[len(artist):].lstrip(" 　:：-―")
        _pn = _pn[:40].rstrip()
        # 除去後に空ならアーティストのみの汎用タイトルに退避
        new_title = f"{artist}『{_pn}』ライブ・コンサート情報" if _pn else f"{artist} ライブ・コンサート情報"
    else:
        new_title = f"{artist} ライブ・コンサート情報"

    lead = (
        f"<p>{esc_html(artist)} 関連のライブ・コンサート情報が "
        f"{esc_html(media)} で確認されました。下記の開催概要をご確認のうえ、"
        f"チケット販売状況の詳細は出典元をご確認ください。</p>"
    )

    # 開催概要(公演名 / 公演日 / 会場)。enrichment 由来の構造化データを
    # 必ず本文に出す。これが無いと詳細ページが「空欄カード」に見える(2026-05-26 修正)。
    # 絵文字(📅🎫)は mysql -e 引数経由で4バイト文字が ? に化ける実害があったため
    # 使わず、ラベル文字+CSS のピンク枠で表現する。
    info_rows = []
    info_rows.append(
        f'<li><span class="kpop-event-info-label">公演名</span>'
        f'<span class="kpop-event-info-value">{esc_html(event_name)}</span></li>'
    )
    if start_date:
        info_rows.append(
            f'<li><span class="kpop-event-info-label">公演日</span>'
            f'<span class="kpop-event-info-value">{esc_html(start_date)}</span></li>'
        )
    if venue:
        info_rows.append(
            f'<li><span class="kpop-event-info-label">会場</span>'
            f'<span class="kpop-event-info-value">{esc_html(venue)}</span></li>'
        )
    info_box = (
        '<div class="kpop-event-info">'
        '<p class="kpop-event-info-head">開催概要</p>'
        f'<ul class="kpop-event-info-list">{"".join(info_rows)}</ul>'
        '</div>'
    )

    # 引用ブロックは「正式な公演名」を取れたときだけ出す。薄い(=artist と同一)
    # ときに引用すると中身がアーティスト名だけの空ブロックになり逆効果。
    quote_box = ""
    if has_real_title:
        quote_box = (
            f'<figure class="kpop-citation-quote">'
            f'<blockquote cite="{esc_html(source_url)}">'
            f'<p>{esc_html(title_orig)}</p>'
            f'</blockquote>'
            f'<figcaption>出典: <a class="kpop-citation-source" href="{esc_html(source_url)}" '
            f'rel="noopener nofollow" target="_blank">{esc_html(media)}</a></figcaption>'
            f'</figure>'
        )

    cta = (
        f'<p class="kpop-citation-cta">'
        f'<strong>チケット情報の詳細は出典元をご確認ください。</strong> '
        f'<a href="{esc_html(source_url)}" rel="noopener nofollow" target="_blank">'
        f'{esc_html(media)} の公演情報</a></p>'
    )

    body = lead + "\n" + info_box + "\n" + quote_box + "\n" + cta
    # slug 一意化: artist+今日 だけだと同一アーティストの複数公演や artist 未抽出
    # (K-POP固定値)で衝突し後勝ち消失する。start_date と source_url から
    # 安定したサフィックスを付けて一意にする。
    import hashlib
    uniq_seed = f"{start_date}-{source_url}"
    uniq = hashlib.md5(uniq_seed.encode("utf-8")).hexdigest()[:6]
    date_part = (start_date or datetime.now().strftime('%Y%m%d')).replace("-", "")
    slug = slugify(f"{artist}-event-{date_part}-{uniq}")
    # メタ用の開始日時: 開演時刻があれば "YYYY-MM-DD HH:MM" を返す(無ければ date のみ)。
    # slug は date_part のみ使用=時刻が変わっても dedup キーは不変(同一公演を二重作成しない)。
    start_dt = f"{start_date} {start_time}" if (start_date and start_time) else start_date
    return new_title, body, slug, start_dt

def esc_html(s: str) -> str:
    """HTML エスケープ。"""
    return (str(s or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

# ─── DB 投稿 ───────────────────────────────────────────
def run_mysql(sql: str) -> str:
    """stg DB に SQL を実行して標準出力を返す。utf8mb4 を明示(絵文字対応)。"""
    cmd = [
        "mysql",
        "--default-character-set=utf8mb4",
        "-u", DB["WP_DB_USER"],
        f"-p{DB['WP_DB_PASSWORD']}",
        DB["WP_DB_NAME"],
        "-e", sql,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        sys.exit(f"mysql error: {r.stderr}")
    return r.stdout.strip()

def find_post_by_slug(slug: str, post_type: str) -> tuple[int, str]:
    """post_name(slug) + post_type で既存投稿を検索。event の冪等ガード用。
    全状態(publish/draft/trash含む)を対象。戻り値 (post_id, post_status)、無ければ (0, "")。"""
    res = run_mysql(
        f"SELECT ID, post_status FROM wp_posts WHERE post_name='{esc_sql(slug)}' "
        f"AND post_type='{esc_sql(post_type)}' ORDER BY ID DESC LIMIT 1;"
    )
    for line in res.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            return int(parts[0].strip()), (parts[1].strip() if len(parts) > 1 else "")
    return 0, ""


def find_popup_by_source_url(source_url: str) -> tuple[int, str]:
    """popup_source_url(完全一致)で既存 popup を検索。重複 import 再発防止ガード。

    今回の3重 import 根本原因対策: main() が source_url の重複確認なしで毎回
    insert していたため、同一出典 popup が複数 post 化していた(生 INSERT で
    WP の slug 一意化もバイパス)。本関数で insert 前に既存を検出して skip する。

    判定: wp_postmeta.meta_key='popup_source_url' AND meta_value=完全一致。
    状態スコープ: 全状態(publish/draft/pending/private/future + trash)を対象。
      → trash 済みの重複が再 import で復活しないよう、trash も「既存」とみなす
        (オーナー決定 2026-05-23。誤 trash は untrash で復元可)。
    戻り値: (post_id, post_status)。既存なしは (0, "")。

    citation-rules §8 で popup は source_url 必須。空 source_url は呼び出し側で
    既に HARD_FAIL skip 済みのため、ここでは念のため空なら (0, "") を返す。
    """
    su = (source_url or "").strip()
    if not su:
        return 0, ""
    su_esc = esc_sql(su)
    # 最古(=正版になりうる最初の1件)を残す方針で ORDER BY p.ID ASC。
    res = run_mysql(
        "SELECT p.ID, p.post_status FROM wp_posts p "
        "JOIN wp_postmeta pm ON pm.post_id = p.ID "
        f"WHERE pm.meta_key = 'popup_source_url' AND pm.meta_value = '{su_esc}' "
        "AND p.post_type = 'post' "
        "ORDER BY p.ID ASC LIMIT 1;"
    )
    for line in res.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            return int(parts[0].strip()), (parts[1].strip() if len(parts) > 1 else "")
    return 0, ""


def build_popup_meta_desc(title: str, sig: dict) -> str:
    """popup 記事の meta description を開催情報(kbz_info)から組み立てる。

    AIOSEO は description 未設定時に post_excerpt へフォールバックするため、
    excerpt に入れれば実レンダの meta description になる。popup 自動投稿は
    excerpt='' 固定だったため、日次ヘルスチェックの「メタdesc未設定」WARN の
    常連になっていた(2026-07-04 恒久対応)。
    """
    kbz = sig.get("kbz_info", {}) or {}
    period = str(kbz.get("開催期間", "")).strip()
    venue = str(kbz.get("会場", "") or kbz.get("住所", "") or kbz.get("開催エリア", "")).strip()
    desc = title.strip().rstrip("。") + "の開催情報。"
    if period:
        desc += f"開催期間は{period}。"
    if venue:
        desc += f"会場は{venue}。"
    desc += "期間・会場・アクセスなど詳細をまとめて紹介します。"
    if len(desc) > 120:
        desc = desc[:119] + "…"
    return desc


def insert_post(title: str, body: str, slug: str, post_type: str,
                category_slug: str | None = None, status: str = "draft",
                excerpt: str = "") -> int:
    """wp_posts に1件 INSERT してID返す。tribe_events の場合 category は使わない。

    status: 'publish' か 'draft'。呼び出し側が品質ゲート(popup_quality_gate)で判定する。
    excerpt: meta description 用(AIOSEO が description 未設定時にフォールバック)。
    """
    now = now_iso()
    title_esc = esc_sql(title)
    body_esc = esc_sql(body)
    slug_esc = esc_sql(slug)
    excerpt_esc = esc_sql(excerpt)
    status = "publish" if status == "publish" else "draft"

    sql = (
        f"INSERT INTO wp_posts (post_author, post_date, post_date_gmt, post_content, post_title, "
        f"post_excerpt, post_status, comment_status, ping_status, post_password, post_name, "
        f"to_ping, pinged, post_modified, post_modified_gmt, post_content_filtered, "
        f"post_parent, menu_order, post_type, comment_count) "
        f"VALUES (1, '{now}', '{now}', '{body_esc}', '{title_esc}', "
        # 2026-05-26: 空本文・サムネ無し・汎用タイトルの popup が無検査公開された事故の対応で
        #   一律 draft 化したが、結果 draft が滞留し popup 更新が止まった(2026-06-15 発覚)。
        # 2026-06-15: 品質ゲート(固有タイトル + 会場/期間あり)を通った記事のみ自動 publish に。
        #   ゲート不合格(薄い)は従来どおり draft 据え置きで人手確認に回す。
        f"'{excerpt_esc}', '{status}', 'closed', 'closed', '', '{slug_esc}', "
        f"'', '', '{now}', '{now}', '', "
        f"0, 0, '{post_type}', 0);"
    )

    if DRY_RUN:
        print(f"[DRY_RUN] {sql[:200]}...")
        return 0

    run_mysql(sql)
    # mysql -e ごとに新規セッション = LAST_INSERT_ID() は使えない。
    # 代わりに slug + post_type で最新の ID を取得(slug は本スクリプト内で一意)
    res = run_mysql(
        f"SELECT ID FROM wp_posts WHERE post_name='{slug_esc}' AND post_type='{esc_sql(post_type)}' "
        f"ORDER BY ID DESC LIMIT 1;"
    )
    lines = [l.strip() for l in res.splitlines() if l.strip().isdigit()]
    pid = int(lines[0]) if lines else 0
    if pid == 0:
        print(f"  WARN: post inserted but ID lookup failed for slug={slug}")
        return 0

    # GUID set
    site = "https://stg.kpopjournal.tokyo"
    guid = f"{site}/?p={pid}" if post_type == "post" else f"{site}/?post_type={post_type}&p={pid}"
    run_mysql(f"UPDATE wp_posts SET guid='{esc_sql(guid)}' WHERE ID={pid};")
    return pid

def assign_category(post_id: int, slug: str) -> None:
    """post に category(taxonomy=category) を紐付け。"""
    term_id = run_mysql(
        f"SELECT t.term_id FROM wp_terms t JOIN wp_term_taxonomy tt ON t.term_id=tt.term_id "
        f"WHERE tt.taxonomy='category' AND t.slug='{esc_sql(slug)}';"
    ).splitlines()
    if len(term_id) < 2:
        print(f"  warning: category '{slug}' not found, skipping assignment")
        return
    tid = term_id[-1].strip()
    tt_id = run_mysql(
        f"SELECT term_taxonomy_id FROM wp_term_taxonomy WHERE term_id={tid} AND taxonomy='category';"
    ).splitlines()[-1].strip()
    if DRY_RUN:
        print(f"[DRY_RUN] would assign category '{slug}' (term_id={tid}) to post {post_id}")
        return
    run_mysql(
        f"INSERT IGNORE INTO wp_term_relationships (object_id, term_taxonomy_id) "
        f"VALUES ({post_id}, {tt_id});"
    )

def download_and_attach_thumbnail(post_id: int, image_url: str, sig: dict) -> int:
    """og:image を取得し WP の featured_image としてセットする。成功時 attachment_id、失敗時 0。

    根治(2026-06-16 / [[popup-cron-thumbnail-aiuser-write-fail]]):
    uploads は www-data 所有で cron 実行ユーザ(aiuser)から直書きできず EPERM になる。
    そのため「aiuser 権限で一時ファイルへ DL → kpop-wp-rw.sh(www-data 権限)で
    `wp media import --featured_image`」に委譲する。WP がリサイズ/srcset 等の
    _wp_attachment_metadata まで正規生成するため、別途 regenerate が不要。

    安全設計:
    - 画像 DL は独自 CA バンドル(_IMG_SSL_CTX)使用 = kbuzzlab の LE Root YR 問題を回避
      ([[popup-update-stall-ssl-and-autopublish]])。
    - 上限 5MB(極端な大ファイル防止)、タイムアウト 30s。
    - 一時ファイルは world-readable(0644)= www-data が読めるようにし、必ず後始末する。
    - alt: 「出典: {media} - {タイトル}」(Layer 2 引用元明示。citation-rules §8)。
    """
    if not image_url:
        return 0
    import urllib.request, urllib.error

    # filename 抽出(URL 末尾)→ 安全な ASCII slug。import 先のファイル名に使う。
    filename = image_url.rsplit("/", 1)[-1].split("?")[0]
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", filename)[:80] or f"popup-{post_id}.jpg"
    if "." not in safe_name:
        safe_name += ".jpg"

    if DRY_RUN:
        print(f"[DRY_RUN] download {image_url[:60]} → (rw media import) post={post_id}")
        return 0

    # ── aiuser 権限で一時ファイルへ DL(world-readable) ──
    # uploads 上のファイル名は import するファイルの basename になるため、
    # tempdir 内で safe_name そのものを使い、クリーンなファイル名を維持する。
    tmp_dir = tempfile.mkdtemp(prefix="popup_thumb_")
    os.chmod(tmp_dir, 0o755)  # www-data が import 時にディレクトリを traverse できるように
    tmp_path = os.path.join(tmp_dir, safe_name)
    try:
        try:
            req = urllib.request.Request(image_url, headers={
                "User-Agent": "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; research)",
                "Accept": "image/webp,image/jpeg,image/png,image/*,*/*;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=30, context=_IMG_SSL_CTX) as r:
                content_length = int(r.headers.get("Content-Length", "0") or 0)
                if content_length > 5 * 1024 * 1024:
                    print(f"  WARN: image too large ({content_length} bytes), skip")
                    return 0
                mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
                data = r.read(5 * 1024 * 1024 + 1)  # 上限 5MB+1
                if len(data) > 5 * 1024 * 1024:
                    print(f"  WARN: stream too large, skip")
                    return 0
            Path(tmp_path).write_bytes(data)
            os.chmod(tmp_path, 0o644)  # www-data が読めるように
            print(f"  thumb fetched: {tmp_path} ({len(data)} bytes, {mime})")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"  WARN: thumbnail download failed: {e}")
            return 0

        # ── www-data 権限で import + featured_image(uploads 複製/メタ生成は WP が実施)──
        imp = subprocess.run(
            ["sudo", "-n", WP_RW, "media", "import", tmp_path,
             f"--post_id={post_id}", "--featured_image", "--porcelain"],
            capture_output=True, text=True, timeout=120,
        )
        if imp.returncode != 0:
            print(f"  WARN: media import 失敗(featured 未設定): {imp.stderr.strip()[:160]}")
            return 0
        try:
            attachment_id = int(imp.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print(f"  WARN: porcelain att_id parse 失敗: {imp.stdout.strip()[:80]}")
            return 0

        # ── alt(Layer 2 出典明示)。media は sig['source_media'] を使う ──
        _media = sig.get("source_media") or "kbuzzlab.com"
        alt = f"出典: {_media} - {sig.get('title', '')[:80]}"
        subprocess.run(
            ["sudo", "-n", WP_RW, "post", "meta", "update",
             str(attachment_id), "_wp_attachment_image_alt", alt],
            capture_output=True, text=True, timeout=60,
        )
        print(f"  featured_image set: post={post_id}, attachment={attachment_id}")
        return attachment_id
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def assign_popup_taxonomy(post_id: int, area_slug: str, status_slug: str) -> None:
    """M11.5 9.5.8-A hotfix: popup_area / popup_status taxonomy を post に紐付け。

    add_popup_acf_meta() と並列で呼ばれる。漏れがあると左サイドフィルタが
    count=0 になり「すべて」しか機能しない問題(オーナー視覚確認発覚)。
    """
    for tax, slug in (("popup_area", area_slug), ("popup_status", status_slug)):
        if not slug:
            continue
        # term_id を解決
        term_row = run_mysql(
            f"SELECT t.term_id FROM wp_terms t JOIN wp_term_taxonomy tt ON t.term_id=tt.term_id "
            f"WHERE tt.taxonomy='{tax}' AND t.slug='{esc_sql(slug)}';"
        ).splitlines()
        tids = [l.strip() for l in term_row if l.strip().isdigit()]
        if not tids:
            print(f"  warning: {tax} '{slug}' term not found, skipping")
            continue
        tid = tids[0]
        tt_row = run_mysql(
            f"SELECT term_taxonomy_id FROM wp_term_taxonomy WHERE term_id={tid} AND taxonomy='{tax}';"
        ).splitlines()
        tt_ids = [l.strip() for l in tt_row if l.strip().isdigit()]
        if not tt_ids:
            continue
        tt_id = tt_ids[0]
        if DRY_RUN:
            print(f"[DRY_RUN] assign {tax}='{slug}' (tt_id={tt_id}) to post {post_id}")
            continue
        run_mysql(
            f"INSERT IGNORE INTO wp_term_relationships (object_id, term_taxonomy_id) "
            f"VALUES ({post_id}, {tt_id});"
        )
        # term count 更新
        run_mysql(
            f"UPDATE wp_term_taxonomy SET count=("
            f"SELECT COUNT(*) FROM wp_term_relationships WHERE term_taxonomy_id={tt_id}"
            f") WHERE term_taxonomy_id={tt_id};"
        )


def _guess_popup_area(sig: dict) -> str:
    """signal の kbz_info / title から popup_area taxonomy slug を推測。

    韓国系は ソウル(seoul)/釜山(busan)、日本は東京(tokyo)等。
    判定できないときは空文字(assign しない)。
    """
    kbz = sig.get("kbz_info", {}) or {}
    # 会場・住所・開催エリアは「実際に開催される場所」を示す強い手がかり。
    # title/description は商材の出自(例: 韓国コスメ)で「韓国」を含みがちなので、
    # まず venue/address から日本の物理ロケーションを優先判定する(タスク#27)。
    # これにより「韓国コスメの渋谷 popup」を seoul と誤タグしない。
    venue_text = (str(kbz.get("会場", "")) + " " +
                  str(kbz.get("住所", "")) + " " +
                  str(kbz.get("開催エリア", ""))).lower()

    def _japan_area(t: str) -> str:
        if any(k in t for k in ["東京", "tokyo", "渋谷", "新宿", "原宿", "表参道"]):  return "tokyo"
        if any(k in t for k in ["大阪", "osaka", "梅田"]):                 return "osaka"
        if any(k in t for k in ["名古屋", "nagoya"]):                       return "nagoya"
        if "北海道" in t or "札幌" in t:                                    return "hokkaido"
        if "東北" in t or "仙台" in t:                                      return "tohoku"
        if "関東" in t:                                                      return "kanto"
        if "中部" in t:                                                      return "chubu"
        if "近畿" in t or "京都" in t or "神戸" in t:                       return "kinki"
        if "中国地方" in t or "広島" in t or "岡山" in t:                   return "chugoku"
        if "四国" in t:                                                      return "shikoku"
        if "九州" in t or "福岡" in t:                                       return "kyushu"
        if "沖縄" in t or "okinawa" in t:                                   return "okinawa"
        return ""

    # 会場/住所に日本の地名があればそれを最優先(物理開催地)
    jp_from_venue = _japan_area(venue_text)
    if jp_from_venue:
        return jp_from_venue

    text = (sig.get("title", "") + " " +
            sig.get("description_snippet", "") + " " + venue_text).lower()
    # 韓国エリア(kbuzzlab は聖水/江南 等の明示的な韓国地名が多い)
    if any(k in text for k in ["釜山", "busan", "プサン"]):
        return "busan"
    if any(k in text for k in ["ソウル", "seoul", "聖水", "ソンス", "seongsu", "江南", "gangnam",
                                 "弘大", "ホンデ", "明洞", "ミョンドン", "梨泰院", "韓国", "korea"]):
        return "seoul"
    # 日本主要エリア(title/description 由来)
    return _japan_area(text)


def _parse_period_dates(period_raw: str) -> tuple[str, str]:
    """開催期間文字列から (start_YYYY-MM-DD, end_YYYY-MM-DD) を返す。

    対応形式(実データで検証):
      - "2026年01月08日 〜 2026年02月28日"(kbuzzlab、年あり)
      - "5/22（金）〜5/24（日） 11:00～19:00"(PRTIMES、年なし → 今年を補完)
    どちらにも当たらなければ ("", "")(捏造しない)。

    年なし M/D 形式は年を仮定するため、過剰な信頼を避けつつ status 判定や
    開催情報表示に使える最低限の値を返す(年は実行年を採用)。
    """
    if not period_raw:
        return "", ""
    # 年あり: YYYY[年/-]M[月/-]D ... 〜 ... YYYY[年/-]M[月/-]D
    m = re.search(
        r"(\d{4})[年/.\-](\d{1,2})[月/.\-](\d{1,2})[日]?.*?[〜~～\-―から].*?"
        r"(\d{4})[年/.\-](\d{1,2})[月/.\-](\d{1,2})",
        period_raw,
    )
    if m:
        try:
            return (
                f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                f"{int(m.group(4)):04d}-{int(m.group(5)):02d}-{int(m.group(6)):02d}",
            )
        except ValueError:
            return "", ""
    # 年なし: M/D ... 〜 ... M/D(年は実行年を補完)
    m = re.search(
        r"(\d{1,2})\s*[/／月]\s*(\d{1,2})\D*?[〜~～\-―から]\D*?"
        r"(\d{1,2})\s*[/／月]\s*(\d{1,2})",
        period_raw,
    )
    if m:
        yr = datetime.now(timezone(timedelta(hours=9))).year
        try:
            return (
                f"{yr:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                f"{yr:04d}-{int(m.group(3)):02d}-{int(m.group(4)):02d}",
            )
        except ValueError:
            return "", ""
    return "", ""


def _guess_popup_status(sig: dict) -> str:
    """開催期間から popup_status を判定: upcoming / ongoing / ended"""
    import datetime as _dt
    period = str(sig.get("kbz_info", {}).get("開催期間", ""))
    start_str, end_str = _parse_period_dates(period)
    if not start_str or not end_str:
        return "ongoing"  # 判定不能なら開催中(中性デフォルト)
    try:
        start = _dt.date.fromisoformat(start_str)
        end   = _dt.date.fromisoformat(end_str)
    except ValueError:
        return "ongoing"
    today = _dt.date.today()
    if today < start: return "upcoming"
    if today > end:   return "ended"
    return "ongoing"


# タスク#26: fetcher が付けた korea_genre(kpop/drama/beauty/food/fashion/korea)を
# 既存 popup_genre taxonomy の slug に対応づける。
#   既存 popup_genre term(stg DB 実在): celebrity / entertainment / character
#                                        / gourmet / fashion
#   - kpop    → entertainment(エンターテインメント)
#   - drama   → celebrity(芸能人・セレブ: 韓流俳優/ドラマ)
#   - beauty  → fashion(ファッション・ビューティー: term 名にビューティー含む)
#   - food    → gourmet(グルメ・カフェ)
#   - fashion → fashion(ファッション・ビューティー)
#   - korea(汎用)/ 不明 → 付与しない(空文字)
# ※ 既存5記事のジャンルは kbuzzlab sp-cat 由来で別管理。これは PRTIMES 経由の
#   新規記事向けマッピング(kbuzzlab signal にも korea_genre は載るので共通利用可)。
_KOREA_GENRE_TO_SLUG = {
    "kpop":    "entertainment",
    "drama":   "celebrity",
    "beauty":  "fashion",
    "food":    "gourmet",
    "fashion": "fashion",
}


def _guess_popup_genre(sig: dict) -> str:
    """signal の korea_genre から popup_genre taxonomy slug を返す。

    判定不能(korea 汎用 / 欠落 / 未対応)のときは空文字(assign しない)。
    """
    return _KOREA_GENRE_TO_SLUG.get(sig.get("korea_genre", ""), "")


def assign_popup_genre(post_id: int, genre_slug: str) -> None:
    """popup_genre taxonomy term を post に紐付け。

    assign_popup_taxonomy と同じ手順(term_id → term_taxonomy_id → 関連挿入
    → count 更新)。slug が空 / term 未存在なら何もしない(安全側)。
    """
    if not genre_slug:
        return
    term_row = run_mysql(
        f"SELECT t.term_id FROM wp_terms t JOIN wp_term_taxonomy tt ON t.term_id=tt.term_id "
        f"WHERE tt.taxonomy='popup_genre' AND t.slug='{esc_sql(genre_slug)}';"
    ).splitlines()
    tids = [l.strip() for l in term_row if l.strip().isdigit()]
    if not tids:
        print(f"  warning: popup_genre '{genre_slug}' term not found, skipping")
        return
    tid = tids[0]
    tt_row = run_mysql(
        f"SELECT term_taxonomy_id FROM wp_term_taxonomy WHERE term_id={tid} AND taxonomy='popup_genre';"
    ).splitlines()
    tt_ids = [l.strip() for l in tt_row if l.strip().isdigit()]
    if not tt_ids:
        return
    tt_id = tt_ids[0]
    if DRY_RUN:
        print(f"[DRY_RUN] assign popup_genre='{genre_slug}' (tt_id={tt_id}) to post {post_id}")
        return
    run_mysql(
        f"INSERT IGNORE INTO wp_term_relationships (object_id, term_taxonomy_id) "
        f"VALUES ({post_id}, {tt_id});"
    )
    run_mysql(
        f"UPDATE wp_term_taxonomy SET count=("
        f"SELECT COUNT(*) FROM wp_term_relationships WHERE term_taxonomy_id={tt_id}"
        f") WHERE term_taxonomy_id={tt_id};"
    )


def add_popup_acf_meta(post_id: int, sig: dict) -> None:
    """kbuzzlab / PRTIMES シグナルから ACF を wp_postmeta に投入。

    ACF Free でも repeater 非対応のままシンプルなフィールド群なら
    get_post_meta() で template から読める。functions.php の
    kpop_render_popup_details_box() がその template 側にあたる。

    kbz_info 互換キー(開催期間/会場/営業時間/開催エリア/住所/予約/特典)を
    持つ signal なら、それを ACF へ落とす。PRTIMES は
    extract_prtimes_event_info() が同じ日本語キーで kbz_info を埋める
    (タスク#27)。

    citation-rules §8: popup_source_url は必須。source_url が無い signal は
    HARD_FAIL とし RuntimeError を送出する(呼び出し側の main は事前にも
    source_url 欠落を skip しているので、ここに来た時点で空なら異常)。
    """
    if not sig.get("source_url"):
        # HARD_FAIL(citation-rules §8): 出典 URL の無い popup は投稿してはならない
        raise RuntimeError(
            f"HARD_FAIL: source_url 欠落のため ACF 投入を中止 (post_id={post_id})"
        )
    kbz = sig.get("kbz_info", {}) or {}

    # フィールド対応(kbuzzlab の sp-info-label → ACF field)
    period_raw = kbz.get("開催期間", "")
    # "2026年01月08日 〜 2026年02月28日"(kbuzzlab)/ "5/22〜5/24"(PRTIMES、
    # 年無し)の両形式を start/end に分解(タスク#27)。抽出不能なら空(捏造禁止)。
    start_date_str, end_date_str = _parse_period_dates(period_raw)

    sns_list = kbz.get("sns", [])
    sns_text = "\n".join(sns_list) if isinstance(sns_list, list) else str(sns_list or "")

    fields = {
        "popup_organizer":    sig.get("source_media", ""),
        "popup_period_start": start_date_str,
        "popup_period_end":   end_date_str,
        "popup_hours":        kbz.get("営業時間", ""),
        "popup_area":         kbz.get("開催エリア", ""),
        # 住所優先。PRTIMES は会場名(地名込み)を住所欄に出して開催情報を機能させる。
        "popup_address":      kbz.get("住所", "") or kbz.get("開催エリア", "") or kbz.get("会場", ""),
        "popup_detail":       sig.get("description_snippet", "")[:300],
        "popup_sns":          sns_text,
        "popup_reservation":  kbz.get("予約", ""),
        "popup_benefit":      kbz.get("特典", ""),
        "popup_map_embed":    kbz.get("map_embed", ""),
        "popup_source_url":   sig.get("source_url", ""),  # HARD_FAIL 必須
    }

    for key, val in fields.items():
        if not val:
            continue
        val_esc = esc_sql(str(val))
        sql = (
            f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) "
            f"VALUES ({post_id}, '{key}', '{val_esc}') "
            f"ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value);"
        )
        if DRY_RUN:
            print(f"[DRY_RUN] {key}={val[:60]}")
        else:
            run_mysql(sql)


def add_event_date_meta(post_id: int, start_date: str) -> None:
    """tribe_events に開始日・終了日メタ + TEC 6.x の custom テーブル更新。

    TEC 6.x は save_post フックで wp_tec_events / wp_tec_occurrences を populate する。
    直接 DB INSERT ではフックが走らないため明示的に登録する。
    これを怠ると /event/{slug}/ single ページが 404 になる(段階7.6 で実測判明)。
    """
    if not start_date:
        return
    # start_date は "YYYY-MM-DD" または "YYYY-MM-DD HH:MM"("HH:MM:SS"も可)。
    # 開演時刻が含まれていればそれを使い、無ければ 19:00 をデフォルトとする
    # (2026-05-27: e-plus 等の実開演時刻を反映。旧実装は一律 19:00 固定だった)。
    from datetime import datetime as _dt, timedelta as _td
    _s = str(start_date).strip().replace("T", " ")
    _date_only = _s[:10]
    _hh, _mm = 19, 0
    _m = re.search(r"\b(\d{1,2}):(\d{2})", _s)
    if _m:
        _h, _mi = int(_m.group(1)), int(_m.group(2))
        if 0 <= _h <= 23 and 0 <= _mi <= 59:
            _hh, _mm = _h, _mi
    try:
        _start = _dt.strptime(f"{_date_only} {_hh:02d}:{_mm:02d}", "%Y-%m-%d %H:%M")
    except Exception:
        _start = _dt.strptime(f"{_date_only} 19:00", "%Y-%m-%d %H:%M")
    _end = _start + _td(hours=2)                 # 公演尺は不明なので従来通り +2h 固定
    _start_u = _start - _td(hours=9)             # JST → UTC
    _end_u = _end - _td(hours=9)
    _F = "%Y-%m-%d %H:%M:%S"
    start_jst = _start.strftime(_F)
    end_jst = _end.strftime(_F)
    start_utc = _start_u.strftime(_F)
    end_utc = _end_u.strftime(_F)
    # 以降の slug/postmeta で日付のみを使う箇所のため YYYY-MM-DD を保持
    start_date = _date_only

    # 1. postmeta
    meta_sqls = [
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventStartDate', '{start_jst}');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventEndDate', '{end_jst}');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventStartDateUTC', '{start_utc}');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventEndDateUTC', '{end_utc}');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventDuration', '7200');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventAllDay', 'no');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventOrigin', 'community-events');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventTimezone', 'Asia/Tokyo');",
        f"INSERT INTO wp_postmeta (post_id, meta_key, meta_value) VALUES ({post_id}, '_EventTimezoneAbbr', 'JST');",
    ]
    for sql in meta_sqls:
        if DRY_RUN:
            print(f"[DRY_RUN] {sql[:120]}...")
            continue
        run_mysql(sql)

    # 2. wp_tec_events(custom table、UNIQUE post_id)
    tec_event_sql = (
        f"INSERT INTO wp_tec_events (post_id, start_date, end_date, timezone, "
        f"start_date_utc, end_date_utc, duration, hash) "
        f"VALUES ({post_id}, '{start_jst}', '{end_jst}', 'Asia/Tokyo', "
        f"'{start_utc}', '{end_utc}', 7200, MD5(CONCAT({post_id}, '{start_jst}'))) "
        f"ON DUPLICATE KEY UPDATE start_date=VALUES(start_date), end_date=VALUES(end_date);"
    )
    if DRY_RUN:
        print(f"[DRY_RUN] {tec_event_sql[:120]}...")
    else:
        run_mysql(tec_event_sql)
        # event_id 取得
        res = run_mysql(f"SELECT event_id FROM wp_tec_events WHERE post_id={post_id};")
        ids = [l.strip() for l in res.splitlines() if l.strip().isdigit()]
        if ids:
            event_id = int(ids[0])
            # 3. wp_tec_occurrences(各 event は 1+ occurrence を持つ。単発イベントは 1 件)
            occ_sql = (
                f"INSERT IGNORE INTO wp_tec_occurrences (event_id, post_id, start_date, start_date_utc, "
                f"end_date, end_date_utc, duration, hash) "
                f"VALUES ({event_id}, {post_id}, '{start_jst}', '{start_utc}', "
                f"'{end_jst}', '{end_utc}', 7200, MD5(CONCAT({event_id}, {post_id}, '{start_jst}')));"
            )
            run_mysql(occ_sql)

# ─── メイン ───────────────────────────────────────────
def main(signals_path: str) -> int:
    if not Path(signals_path).exists():
        sys.exit(f"signals file not found: {signals_path}")
    data = json.loads(Path(signals_path).read_text())
    signals = data.get("signals", [])
    if LIMIT > 0:
        signals = signals[:LIMIT]

    print(f"=== popup_event_to_post.py 開始 (signals={len(signals)}, DRY_RUN={DRY_RUN}) ===")

    posted = []
    for i, sig in enumerate(signals, 1):
        print(f"\n[{i}/{len(signals)}] type={sig['type']} artist={sig['artist_keyword']}")
        print(f"  source: {sig['source_media']} — {sig['title'][:80]}")
        # HARD_FAIL: source_url 必須
        if not sig.get("source_url"):
            print("  SKIP: source_url 欠落(HARD_FAIL)")
            continue

        # 2026-05-26 品質ガード: artist_keyword が汎用プレースホルダ(個別アーティスト名でない)
        # かつ構造化データ(kbz_info)が空のシグナルは、本文・タイトルが「アイドル ポップアップ
        # ストア開催決定」のような中身ゼロ記事になる。pops-in の idol-events 由来で量産された
        # 空記事事故の恒久対応として、両方を満たすものは記事化しない(HARD_FAIL でなく品質 skip)。
        _GENERIC_KW = {"アイドル", "韓国", "韓国アイドル", "K-POP", "ケーポップ", "韓流",
                       "SEOUL", "ソウル", "ソンス", "ホンデ", "聖水", "弘大"}
        _kbz = sig.get("kbz_info", {}) or {}
        _has_struct = any(str(_kbz.get(k, "")).strip()
                          for k in ("会場", "開催期間", "開催エリア", "住所", "営業時間"))
        if sig.get("artist_keyword", "").strip() in _GENERIC_KW and not _has_struct:
            print(f"  SKIP(品質): 汎用 artist='{sig.get('artist_keyword')}' かつ開催情報なし → 記事化しない")
            continue

        if sig["type"] == "popup":
            # 重複再発防止ガード(2026-05-23): popup_source_url 完全一致の既存があれば
            # insert せず skip。trash 含む全状態を対象(既存の重複整理を尊重)。
            # insert 前に判定するため、重複 popup を二度と生成しない(冪等)。
            existing_id, existing_status = find_popup_by_source_url(sig["source_url"])
            if existing_id:
                print(f"  SKIP(dedup): source_url は既存 ID {existing_id}(status={existing_status})、insert しない")
                posted.append({"type": "popup", "post_id": existing_id, "title": sig.get("title", ""),
                               "url": f"https://stg.kpopjournal.tokyo/?p={existing_id}", "skipped_dedup": True})
                continue
            title, body, slug = build_popup_article(sig)
            ok_pub, gate_reason = popup_quality_gate(sig, title)
            status = "publish" if ok_pub else "draft"
            print(f"  品質ゲート: {'PUBLISH' if ok_pub else 'DRAFT'} — {gate_reason}")
            pid = insert_post(title, body, slug, post_type="post", status=status,
                              excerpt=build_popup_meta_desc(title, sig))
            if pid and not DRY_RUN:
                assign_category(pid, "popup")
                # M11.5 段階9.5 + タスク#27: ACF を投入。
                # kbuzzlab は sp-info 由来、PRTIMES は個別リリース抽出由来の
                # kbz_info 互換 dict を持つ。どちらも add_popup_acf_meta で処理し、
                # popup_source_url を必ず入れる(citation-rules §8)。
                add_popup_acf_meta(pid, sig)
                # popup_area / popup_status taxonomy 紐付け(全 popup post に適用、
                # 9.5.8-A オーナー視覚確認フィードバックで判明した漏れの恒久対応)
                area_slug   = _guess_popup_area(sig)
                status_slug = _guess_popup_status(sig)
                assign_popup_taxonomy(pid, area_slug, status_slug)
                # タスク#26: 韓国関連ジャンル(korea_genre)→ popup_genre taxonomy
                assign_popup_genre(pid, _guess_popup_genre(sig))
                # M11.5 9.5.8-F-B: featured_image(thumbnail)を自社 uploads に複製
                thumb_url = sig.get("thumbnail_url", "")
                if thumb_url:
                    download_and_attach_thumbnail(pid, thumb_url, sig)
            posted.append({"type": "popup", "post_id": pid, "title": title, "url": f"https://stg.kpopjournal.tokyo/{slug}/"})
        elif sig["type"] == "event":
            title, body, slug, start_date = build_event_article(sig)
            # 冪等ガード(2026-05-25): slug は start_date+source_url の md5 を含むため
            # 同一公演は同一 slug になる。既存があれば insert せず skip し、週次 cron の
            # 重複増殖を防ぐ(event は popup と違い source_url ガードが無かった)。
            existing_eid, existing_estatus = find_post_by_slug(slug, "tribe_events")
            if existing_eid:
                print(f"  SKIP(dedup): event slug={slug} は既存 ID {existing_eid}(status={existing_estatus})")
                posted.append({"type": "event", "post_id": existing_eid, "title": title,
                               "url": f"https://stg.kpopjournal.tokyo/events/{slug}/", "skipped_dedup": True})
                continue
            pid = insert_post(title, body, slug, post_type="tribe_events")
            if pid and not DRY_RUN:
                add_event_date_meta(pid, start_date)
            posted.append({"type": "event", "post_id": pid, "title": title, "url": f"https://stg.kpopjournal.tokyo/events/{slug}/"})
        else:
            print(f"  SKIP: unknown type {sig['type']}")

    print(f"\n=== 投稿完了: {len(posted)} 件 ===")
    for p in posted:
        print(f"  [{p['type']}] post_id={p['post_id']} {p['title'][:60]}...")
        print(f"    {p['url']}")

    # タスク#27: 投稿結果(post_id 一覧)をスモークテストへ引き渡すため任意で JSON 出力。
    # POST_RESULTS=<path> が指定されたときのみ書き出す(既存挙動は不変)。
    results_path = os.environ.get("POST_RESULTS", "")
    if results_path and not DRY_RUN:
        try:
            Path(results_path).write_text(
                json.dumps({"posted": posted}, ensure_ascii=False, indent=2)
            )
            print(f"  posted results 書き出し: {results_path}")
        except OSError as e:
            print(f"  WARN: posted results 書き出し失敗: {e}")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: popup_event_to_post.py <signals.json>")
    sys.exit(main(sys.argv[1]))
