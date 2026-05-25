#!/usr/bin/env python3
"""seo_opportunity_scanner.py — SEOコンテンツ戦略v1 の司令塔（2026-05-25）

GSC の query 次元を分析し「上位を狙える取りこぼしクエリ」を検知して、
記事化キュー data/seo_opportunity_queue.json に優先度付きで出力する。
docs/seo_content_strategy_v1.md §4 の実装。毎回の手動 GSC 分析を自動化する。

判定ロジック（手動分析で実証したものを成文化）:
  レーンB候補(新規) = imp>=MIN_IMP & 順位 4〜30位 & CTR < MAX_CTR & 未記事化
  レーンC候補(既存強化) = imp>=MIN_IMP & 順位 4〜20位 & 既記事化テーマ
  potential = 1ページ上位化での追加click概算 = imp*0.20 - clicks
除外:
  - 自サイト指名検索（kジャーナル等のブランド名）
  - ゴシップ・私的事実語（熱愛/破局/脱退理由/解散 等。§7）
  - ビッグワード×強競合（聖地巡礼 等、順位が極端に低く新興ドメインに重い）

使い方:
  venv_kpi/bin/python3 lib/seo_opportunity_scanner.py            # 16ヶ月で分析
  venv_kpi/bin/python3 lib/seo_opportunity_scanner.py --days 90  # 直近90日
  venv_kpi/bin/python3 lib/seo_opportunity_scanner.py --top 40   # 上位40件表示
依存: google-api-python-client / service_account.json（venv_kpi に存在）
"""
import argparse
import json
import os
import subprocess
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SA_FILE = os.path.join(BASE_DIR, "google_metrics", "service_account.json")
SITE = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
OUT_FILE = os.path.join(BASE_DIR, "data", "seo_opportunity_queue.json")

# --- 判定パラメータ ---
MIN_IMP = 300          # この impression 未満は対象外（需要が小さい）
MAX_CTR = 0.12         # 現CTRがこれ未満＝取りこぼし
POS_NEW = (3.5, 30.0)  # 新規候補の順位帯（中位＝上げ余地）
POS_REWRITE = (3.5, 20.0)  # 既存強化候補の順位帯

# --- テーマ分類（docs戦略の3レーン×テーマ）---
THEMES = {
    "dance_show": ["swf3", "スウパ", "ojo", "オジョ", "street woman", "ストリート",
                   "rhtokyo", "riehata", "bumsup", "ag squad", "motiv", "royal family",
                   "ロイヤルファミリー", "supa", "route59", "ルート59"],
    "movie_anime": ["デーモンハンター", "demon hunter", "golden", "ゴールデン",
                    "kpopガールズ", "サジャ", "ハントリックス"],
    "kdrama": ["コンフィデンス", "confidence", "暴君", "ドラマ", "相関図", "kr 吹き替え",
               "tyrant", "暴君のシェフ", "キャスト"],
    "beauty": ["スキンケア", "コスメ", "美容", "下地", "メイク", "美顔器", "ブースタープロ",
               "medicube", "メディキューブ", "ファンデ", "ティント", "クッション"],
    "travel": ["旅行", "ソウル", "弘大", "ホンデ", "明洞", "カフェ", "グルメ", "聖地",
               "wowpass", "狎鴎亭", "東大門", "江南"],
    "artist": ["bts", "blackpink", "twice", "aespa", "seventeen", "newjeans", "ive",
               "bigbang", "ビッグバン", "stray", "nct"],
    "trend_goods": ["ラブブ", "labubu"],
    "awards": ["mama", "投票", "awards", "授賞"],
}

# --- 除外フィルタ ---
BRAND_TERMS = ["kジャーナル", "ケージャーナル", "k journal", "kーjournal", "k-journal",
               "ケーポップジャーナル", "kpop journal", "kpopjournal"]
GOSSIP_TERMS = ["熱愛", "破局", "彼氏", "彼女", "結婚", "離婚", "整形", "炎上", "暴露",
                "脱退理由", "解散", "スキャンダル", "同棲", "交際", "dating", "不倫",
                "ゴシップ", "ダイエット", "兵役", "噂", "うわさ", "私服", "すっぴん",
                "彼", "год", "妊娠", "病気", "体重", "身長 体重"]
# 速報(breaking)パイプラインが扱う即時性クエリ＝常緑SEO記事の対象外
BREAKING_TERMS = ["速報", "自撮り", "活動再開", "復帰", "完全体", "事務所",
                  "公開", "発表 いつ", "カムバ いつ"]
# 強競合ビッグワード（順位が極端に低い＝新興ドメインに重い。正面突破しない）
HARD_COMPETITION = ["聖地巡礼", "聖地 巡礼", "pilgrimage"]


def fetch_queries(days):
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    svc = build("searchconsole", "v1", credentials=creds)
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    body = {"startDate": start, "endDate": end, "dimensions": ["query"], "rowLimit": 25000}
    res = svc.searchanalytics().query(siteUrl=SITE, body=body).execute()
    return res.get("rows", [])


def existing_slugs():
    """公開記事の slug を RO ラッパーで取得（記事化済みテーマの判定用）。"""
    try:
        out = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro", "post", "list",
             "--post_type=post", "--post_status=publish",
             "--fields=post_name", "--format=csv", "--posts_per_page=-1"],
            capture_output=True, text=True, timeout=60)
        lines = out.stdout.strip().splitlines()[1:]  # skip header
        return set(l.strip() for l in lines if l.strip())
    except Exception:
        return set()


def classify(q):
    ql = q.lower()
    for theme, kws in THEMES.items():
        if any(k.lower() in ql for k in kws):
            return theme
    return "other"


def is_excluded(q):
    ql = q.lower()
    if any(b.lower() in ql for b in BRAND_TERMS):
        return "brand"
    if any(g in q for g in GOSSIP_TERMS):
        return "gossip"
    if any(b in q for b in BREAKING_TERMS):
        return "breaking"
    if any(h in q for h in HARD_COMPETITION):
        return "hard_competition"
    return None


def theme_is_covered(theme, slugs):
    """そのテーマの記事が既に存在するか（slug にテーマ語が含まれるか）。"""
    theme_slug_hint = {
        "dance_show": ["swf3", "ojo", "supa", "rhtokyo", "bumsup", "motiv", "royal", "street-woman"],
        "movie_anime": ["demon-hunters", "golden"],
        "kdrama": ["confidence-man", "tyrant-chef", "kdrama"],
        "beauty": ["skincare", "medicube", "base-makeup", "beauty"],
        "travel": ["hongdae", "myeongdong", "wowpass", "seoul", "travel"],
        "trend_goods": ["labubu"],
        "awards": ["mama", "voting"],
        "artist": [],
    }
    hints = theme_slug_hint.get(theme, [])
    if not hints:
        return False
    return any(any(h in s for h in hints) for s in slugs)


def scan(days, top):
    rows = fetch_queries(days)
    slugs = existing_slugs()
    new_cands, rewrite_cands = [], []
    excluded = {"brand": 0, "gossip": 0, "breaking": 0, "hard_competition": 0}

    for r in rows:
        q = r["keys"][0]
        imp, clk, pos = r["impressions"], r["clicks"], r["position"]
        if imp < MIN_IMP:
            continue
        ex = is_excluded(q)
        if ex:
            excluded[ex] += 1
            continue
        ctr = clk / imp if imp else 0
        theme = classify(q)
        potential = round(imp * 0.20 - clk)
        rec = {"query": q, "imp": round(imp), "clicks": round(clk),
               "position": round(pos, 1), "ctr_pct": round(ctr * 100, 1),
               "theme": theme, "potential": potential}
        covered = theme_is_covered(theme, slugs)
        if POS_REWRITE[0] < pos <= POS_REWRITE[1] and covered:
            rec["lane"] = "C_rewrite"
            rewrite_cands.append(rec)
        elif POS_NEW[0] < pos <= POS_NEW[1] and ctr < MAX_CTR and not covered:
            rec["lane"] = "B_new"
            new_cands.append(rec)

    new_cands.sort(key=lambda x: -x["potential"])
    rewrite_cands.sort(key=lambda x: -x["potential"])

    queue = {
        "generated_at": date.today().isoformat(),
        "window_days": days,
        "params": {"min_imp": MIN_IMP, "max_ctr": MAX_CTR,
                   "pos_new": POS_NEW, "pos_rewrite": POS_REWRITE},
        "totals": {"queries_scanned": len(rows),
                   "lane_B_new": len(new_cands),
                   "lane_C_rewrite": len(rewrite_cands),
                   "excluded": excluded,
                   "existing_slugs": len(slugs)},
        "lane_B_new": new_cands,
        "lane_C_rewrite": rewrite_cands,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=1)

    # --- 標準出力サマリ ---
    print(f"GSC scan: {len(rows)} queries / window {days}d / existing_slugs {len(slugs)}")
    print(f"excluded: brand={excluded['brand']} gossip={excluded['gossip']} "
          f"breaking={excluded['breaking']} hard_competition={excluded['hard_competition']}")
    print(f"\n=== レーンB 新規記事候補 {len(new_cands)}件 / top{top} "
          f"(potential=上位化での追加click概算) ===")
    print(f"{'+clk':>6} {'imp':>6} {'clk':>5} {'pos':>5} {'theme':>11}  query")
    for r in new_cands[:top]:
        print(f"{r['potential']:6d} {r['imp']:6d} {r['clicks']:5d} {r['position']:5.1f} "
              f"{r['theme']:>11}  {r['query']}")
    print(f"\n=== レーンC 既存強化候補 {len(rewrite_cands)}件 / top{min(top, 15)} ===")
    print(f"{'+clk':>6} {'imp':>6} {'clk':>5} {'pos':>5} {'theme':>11}  query")
    for r in rewrite_cands[:min(top, 15)]:
        print(f"{r['potential']:6d} {r['imp']:6d} {r['clicks']:5d} {r['position']:5.1f} "
              f"{r['theme']:>11}  {r['query']}")
    print(f"\nsaved: {OUT_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=480, help="GSC 取得期間（日）")
    ap.add_argument("--top", type=int, default=30, help="表示件数")
    args = ap.parse_args()
    scan(args.days, args.top)


if __name__ == "__main__":
    main()
