#!/usr/bin/env python3
"""cv_article_generator.py — 比較・おすすめ(CV)記事ドラフト生成

テーマ例:
  - K-POPサブスク比較
  - 韓国コスメおすすめ
  - K-POPチケット予約サイト比較

1日1本の「下書き」をWP側にdraft登録し、内部で人間orミュウツーレビュー後に publish する運用。
スラッグ変更禁止のため draft 段階で slug を最終決定してから publish する設計。

使い方:
  python3 lib/cv_article_generator.py --theme subsc
  python3 lib/cv_article_generator.py --theme all --dry-run
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
OUT = LOGS / "cv_article_queue.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

THEMES = {
    "subsc": {
        "slug": "kpop-subsc-compare-2026",
        "title": "K-POPが聴ける音楽サブスク完全比較【2026年最新版】｜Spotify・Apple Music・LINE MUSIC",
        "meta_desc": "K-POPを聴きたい人向けの主要音楽サブスクを曲数・独占配信・歌詞・価格で徹底比較。Spotify・Apple Music・LINE MUSIC・Amazon Musicそれぞれの強みと弱みを整理します。",
        "sections": [
            ("結論：用途別おすすめサブスク", "まず結論から。推し活中心ならSpotify、音質重視ならApple Music、歌詞重視ならLINE MUSICが軸になる。"),
            ("Spotify：プレイリスト文化と発見機能", "デイリーミックスとDiscover Weeklyが最もK-POPアルゴリズムに合う。ファンキュレーションも豊富。"),
            ("Apple Music：ハイレゾ音質と独占配信", "ロスレス・空間オーディオ対応。一部K-POPアーティストの独占配信・インタビューコンテンツあり。"),
            ("LINE MUSIC：日本語歌詞と共有機能", "日本語訳歌詞が充実、LINE着うた連携。カラオケ採点機能でファン向け。"),
            ("Amazon Music Unlimited：Prime連動の割引", "Prime会員ならコスパ最強。Alexa連携でスマート再生も可能。"),
            ("料金・曲数・独占配信の比較表", "各サービスの数字を一覧化。"),
            ("失敗しない選び方チェックリスト", "3つの質問であなたに最適なサービスを決めるフローチャート。"),
            ("まとめ：推し活スタイル別の最終推奨", "K-POPファンの4パターン別におすすめサービスを提示。"),
        ],
        "cta_affiliates": [
            ("https://www.spotify.com/", "Spotify公式"),
            ("https://music.apple.com/", "Apple Music公式"),
            ("https://music.line.me/", "LINE MUSIC公式"),
        ],
    },
    "cosme": {
        "slug": "kpop-korea-cosme-osusume-2026",
        "title": "K-POPアイドル愛用 韓国コスメおすすめ完全ガイド【2026年最新】｜ガラス肌・クッションファンデ",
        "meta_desc": "K-POPアイドルが実際に使う韓国コスメを肌タイプ別・目的別に徹底紹介。ガラス肌メイク、クッションファンデ、ティント、スキンケアまで2026年最新おすすめアイテムを網羅します。",
        "sections": [
            ("アイドルメイクの基本：ガラス肌の作り方", "土台作りに欠かせないステップとアイテム。"),
            ("クッションファンデ徹底比較", "ラネージュ、エチュード、CLIO、ロムアンドの違い。"),
            ("ティント・リップ決定版", "色持ち・発色・落ちにくさの3軸で比較。"),
            ("アイメイク：デビューカラー別の最旬アイテム", "推しグループのカラーに寄せたアイシャドウの選び方。"),
            ("スキンケアルーティン完全版", "朝/夜/週末スペシャルケアの分け方。"),
            ("価格帯別おすすめ：プチプラ〜デパコス", "予算2000円〜10000円で組める推し活メイク。"),
            ("失敗しない購入場所ガイド", "正規輸入品を安全に買うためのチェックポイント。"),
            ("まとめ：肌タイプ別の最終推奨セット", "乾燥肌/混合肌/脂性肌別の推奨アイテム3点パック。"),
        ],
        "cta_affiliates": [
            ("https://www.amazon.co.jp/", "Amazonで探す"),
            ("https://www.qoo10.jp/", "Qoo10で探す"),
        ],
    },
    "streaming": {
        "slug": "kpop-streaming-shichou-houhou-2026",
        "title": "K-POP動画・ライブの視聴方法完全ガイド【2026年最新】｜Weverse・LYN・Abemaを徹底比較",
        "meta_desc": "K-POPアイドルの動画・ライブをどこで観るか迷う人向け。Weverse・LYN・Abema・YouTube Premiumなど主要配信プラットフォームをコンテンツ量・価格・日本語字幕で徹底比較します。",
        "sections": [
            ("結論：目的別おすすめ視聴プラットフォーム", "推し活中心ならWeverse、ドキュメンタリーならLYN、韓国番組ならAbemaが軸になる。"),
            ("Weverse：公式コミュニケーションの中心地", "グループ別のコンテンツと投稿、メンバーシップの違い、日本語字幕対応の現状。"),
            ("LYN Content：独占ドキュメンタリーとバラエティ", "HYBE系・SM系・JYP系のコンテンツ独占、月額料金、無料期間。"),
            ("Abema：韓国ドラマ・音楽番組の決定版", "音楽番組リアルタイム配信、K-POP関連の独占番組、無料会員の制限。"),
            ("YouTube Premium：MV高画質とバックグラウンド再生", "広告なし、オフライン保存、YouTube Musicでの音楽視聴。"),
            ("V LIVE（現Weverse LIVE）：ライブ配信の現状", "2022年統合後のライブ機能、メンバーシップ限定配信。"),
            ("日本公式サイト・ファンクラブの有料動画", "所属事務所公式サイト独自配信、会員費、コンテンツ量。"),
            ("価格・字幕・独占コンテンツの完全比較表", "各サービスの数字を一覧化。"),
            ("失敗しない選び方チェックリスト", "3つの質問であなたに最適なプラットフォームを決定。"),
            ("まとめ：推し活スタイル別の最終推奨", "K-POPファンの4パターン別におすすめサービスを提示。"),
        ],
        "cta_affiliates": [
            ("https://weverse.io/", "Weverse公式"),
            ("https://abema.tv/", "Abema公式"),
            ("https://www.youtube.com/premium", "YouTube Premium"),
        ],
    },
    "ticket": {
        "slug": "kpop-ticket-kounyu-guide-2026",
        "title": "K-POPライブチケット購入完全ガイド【2026年最新】｜公式・リセール・海外公演の買い方",
        "meta_desc": "K-POPライブのチケットを確実に買うための完全ガイド。Weverse Shop・Interpark・日本公式・チケットぴあ・リセール各サイトの違いと、落選しない事前準備まで2026年最新情報で解説します。",
        "sections": [
            ("結論：公演タイプ別おすすめ購入ルート", "日本公演は公式FC→一般、韓国公演はWeverse Shop→Interparkが基本。"),
            ("日本公演の購入ルート：公式FC・一般販売", "所属事務所公式ファンクラブ先行、一般販売、チケットぴあ・イープラス・ローチケの違い。"),
            ("韓国公演の購入ルート：Weverse Shop・Interpark", "Weverse Shop先行、Interpark一般販売、メルパラ・YES24の選択肢。"),
            ("海外公演の購入ルート：Ticketmaster・公式サイト", "米国・欧州公演のTicketmaster、VISA事前払い、本人確認。"),
            ("ファンクラブ入会で先行販売を確保する", "所属事務所公式FC、Weverseメンバーシップ、会費と先行枠の関係。"),
            ("リセール利用時の注意点：チケット流通センター・StubHub", "正規リセールと非公式転売の違い、入場時の本人確認トラブル。"),
            ("落選しない事前準備：会員登録・決済手段・通信環境", "販売日までに済ませるべき5つの準備。"),
            ("同行者・譲渡の公式ルール", "公式譲渡機能、同行者登録、名義変更の制限。"),
            ("価格・販売時期・入会費の比較表", "各ルートの数字を一覧化。"),
            ("まとめ：公演形態別の最終推奨ルート", "ドーム/アリーナ/韓国公演/海外公演の4パターン別推奨。"),
        ],
        "cta_affiliates": [
            ("https://shop.weverse.io/", "Weverse Shop公式"),
            ("https://www.interpark.com/", "Interpark公式"),
            ("https://t.pia.jp/", "チケットぴあ公式"),
        ],
    },
}


def build_html(theme_key: str, theme: dict) -> str:
    parts = []
    parts.append(f"<p>{theme['meta_desc']}</p>")
    parts.append(f'<div data-cta="top" style="margin:16px 0;padding:14px;border-left:4px solid #ff4d6d;background:#fff5f7;"><p style="margin:0;"><strong>この記事でわかること</strong>｜{" / ".join(s[0] for s in theme["sections"][:3])}</p></div>')
    for i, (h, body) in enumerate(theme["sections"]):
        parts.append(f"<h2>{h}</h2>")
        parts.append(f"<p>{body}</p>")
        parts.append("<p>※本記事は2026年4月時点の公開情報にもとづいて編集されています。最新の価格・仕様は各公式サイトでご確認ください。</p>")
        if i == len(theme["sections"]) // 2:
            aff = "・".join(f'<a href="{u}" rel="sponsored nofollow">{n}</a>' for u, n in theme["cta_affiliates"])
            parts.append(f'<div data-cta="mid" style="margin:20px 0;padding:14px;border:2px solid #7b61ff;background:#faf9ff;"><p style="margin:0;"><strong>👇 公式ページ</strong>：{aff}</p></div>')
    parts.append('<div data-cta="bottom" style="margin:30px 0;padding:16px;border:2px dashed #ff4d6d;background:#fff8f9;text-align:center;"><p style="margin:0;"><strong>K-POP JOURNALでは毎日最新情報を発信中</strong></p><p style="margin:0;">👉 <a href="https://www.kpopjournal.tokyo/">トップへ</a> / <a href="https://www.kpopjournal.tokyo/kpop-beginner-hub-2026/">初心者ガイド</a></p></div>')
    # 情報元
    parts.append("<h2>情報元・参考資料</h2><ul>" +
                 "".join(f'<li><a href="{u}" rel="nofollow">{n}</a></li>' for u, n in theme["cta_affiliates"]) +
                 "</ul>")
    return "\n".join(parts)


def curl_post(path: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    return json.loads(subprocess.check_output(cmd, timeout=60).decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", choices=list(THEMES.keys()) + ["all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    keys = list(THEMES.keys()) if args.theme == "all" else [args.theme]
    ts = datetime.now(tz=JST).isoformat()
    with OUT.open("a") as fp:
        for k in keys:
            t = THEMES[k]
            html = build_html(k, t)
            payload = {
                "title": t["title"],
                "slug": t["slug"],
                "content": html,
                "status": "draft",  # 必ずdraft（人間レビュー後publish）
                "excerpt": t["meta_desc"],
                "meta": {"_aioseo_description": t["meta_desc"]},
            }
            if args.dry_run:
                print(f"  [dry] {k}: slug={t['slug']} len(html)={len(html)}")
                fp.write(json.dumps({"ts": ts, "theme": k, "slug": t["slug"],
                                     "action": "dry_run", "html_len": len(html)},
                                    ensure_ascii=False) + "\n")
                continue
            try:
                r = curl_post("/wp-json/wp/v2/posts", payload)
                pid = r.get("id")
                link = r.get("link", "")
                print(f"  ✅ {k}: post_id={pid} slug={t['slug']} status=draft")
                fp.write(json.dumps({"ts": ts, "theme": k, "post_id": pid,
                                     "slug": t["slug"], "status": "draft",
                                     "link": link}, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"  ❌ {k}: {e}")

    print(f"  ログ: {OUT}")


if __name__ == "__main__":
    main()
