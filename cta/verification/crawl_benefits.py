#!/usr/bin/env python3
"""Task A1: ベネフィット52文言の数値検証"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "-q"])
    import requests
    from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}

# 52 benefit texts per program (4 each x 13 programs)
# Format: program_key -> [benefit_text, ...]
# Numbers to verify are embedded in the text
BENEFITS_DRAFT = {
    "global_wifi": [
        "1日定額¥970〜、韓国4G/5G接続",
        "空港受取&返却、24時間サポート対応",
        "同時接続5台、友達・家族でシェアOK",
        "200以上の国と地域で使える安心感",
    ],
    "voyageesim": [
        "韓国eSIM 1日¥690〜、到着前に設定完了",
        "物理SIM不要、QRコード読取で即開通",
        "200ヵ国以上対応、乗り継ぎ先でもそのまま使える",
        "データ使い放題プラン有、速度制限の心配なし",
    ],
    "korea_data_wifi": [
        "韓国専用WiFi、高速4G/LTE接続",
        "仁川空港・金浦空港で受取&返却OK",
        "1台で最大10台同時接続、グループ旅行に最適",
        "無制限プラン有、データ残量を気にせず使える",
    ],
    "dholic": [
        "韓国トレンド直輸入、毎日新作入荷",
        "全品送料¥550、¥5,500以上で送料無料",
        "サイズ交換対応、初めての韓国ファッションも安心",
        "推しと同じ系統のコーデが見つかる",
    ],
    "olens_poplens": [
        "韓国No.1カラコンブランド、アイドル多数着用",
        "1箱¥1,650〜、ワンデーから長期タイプまで",
        "処方箋不要、度あり・度なし対応",
        "K-POPアイドル愛用デザイン多数",
    ],
    "kkday": [
        "ソウル現地ツアー予約、日本語完全対応",
        "即日予約OK、当日参加できるアクティビティ多数",
        "最大20%割引クーポン随時配信",
        "550以上の都市で体験が予約できる",
    ],
    "ikyu": [
        "厳選高級ホテル、最大60%割引の直前セール",
        "ライブ会場近くの高評価ホテルが見つかる",
        "ポイント最大5%還元、次回予約にも使える",
        "口コミ評価4.0以上のホテルを多数掲載",
    ],
    "newt": [
        "航空券+ホテルをアプリで一括比較・予約",
        "海外旅行アプリ ダウンロード数No.1",
        "最低価格保証で安心して予約できる",
        "24時間チャットサポート対応",
    ],
    "matilda": [
        "韓国コスメ専門、日本未入荷ブランド多数",
        "韓国から直送、正規品のみ取扱い",
        "初回購入10%OFF、お得に試せる",
        "SNSで話題の最新コスメをいち早くGET",
    ],
    "codibook": [
        "韓国ファッション専門、毎日新商品追加",
        "¥3,000以下のプチプラ韓国服も豊富",
        "コーデ提案機能で推し活コーデを発見",
        "全品韓国直送、本場のトレンドそのまま",
    ],
    "italki": [
        "韓国語ネイティブ講師と1対1オンラインレッスン",
        "1レッスン¥800〜、お手頃価格で始められる",
        "24時間好きな時間に予約できる柔軟さ",
        "推しの言葉を理解したいファンに最適",
    ],
    "dekiru_korean": [
        "「できる韓国語」シリーズの公式オンライン講座",
        "動画+オンラインレッスンの組み合わせ学習",
        "入門〜上級、レベルに合わせたカリキュラム",
        "推しのSNSを原文で読めるようになる",
    ],
    "sazo_purchase_agent": [
        "韓国の通販サイトから商品を代行購入",
        "URLを入力するだけで簡単注文",
        "日本語サポートで安心して利用できる",
        "韓国限定グッズも自宅にお届け",
    ],
}

# URLs to verify prices/numbers against
VERIFY_URLS = {
    "global_wifi": ["https://townwifi.com/", "https://townwifi.com/korea/"],
    "voyageesim": ["https://voyageesim.com/", "https://voyageesim.com/korea"],
    "korea_data_wifi": ["https://www.korea-wifi.com/"],
    "dholic": ["https://www.dholic.co.jp/"],
    "olens_poplens": ["https://www.poplens.jp/"],
    "kkday": ["https://www.kkday.com/ja"],
    "ikyu": ["https://www.ikyu.com/"],
    "newt": ["https://newt.net/"],
    "matilda": ["https://matilda-online.com/"],
    "codibook": ["https://codibook.net/"],
    "italki": ["https://www.italki.com/"],
    "dekiru_korean": ["https://www.dekirukan.jp/", "https://dekikan.com/"],
    "sazo_purchase_agent": ["https://sazo.buyee.jp/"],
}

# Numbers that need verification (extracted from benefits)
NUMBERS_TO_VERIFY = {
    "global_wifi": {"¥970": "970", "5台": "5", "200": "200"},
    "voyageesim": {"¥690": "690", "200ヵ国": "200"},
    "korea_data_wifi": {"10台": "10"},
    "dholic": {"¥550": "550", "¥5,500": "5,500"},
    "olens_poplens": {"¥1,650": "1,650"},
    "kkday": {"20%": "20", "550": "550"},
    "ikyu": {"60%": "60", "5%": "5", "4.0": "4.0"},
    "newt": {},  # No.1 already verified in social proof
    "matilda": {"10%": "10"},
    "codibook": {"¥3,000": "3,000"},
    "italki": {"¥800": "800"},
    "dekiru_korean": {},
    "sazo_purchase_agent": {},
}


def fetch_text(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        return ""
    except:
        return ""


def verify_program_benefits(key: str) -> dict:
    """Verify benefit numbers for a single program."""
    result = {
        "program_key": key,
        "benefits_original": BENEFITS_DRAFT[key],
        "benefits_verified": [],
        "numbers_checked": {},
    }

    # Fetch page content
    all_text = ""
    for url in VERIFY_URLS.get(key, []):
        all_text += " " + fetch_text(url)

    nums = NUMBERS_TO_VERIFY.get(key, {})
    for label, search_val in nums.items():
        found = search_val in all_text or search_val.replace(",", "") in all_text
        result["numbers_checked"][label] = {
            "value": search_val,
            "found_on_site": found,
        }

    # Build verified benefits
    for benefit in BENEFITS_DRAFT[key]:
        verified_text = benefit
        needs_replace = False

        for label, search_val in nums.items():
            if label in benefit or search_val in benefit:
                if not result["numbers_checked"][label]["found_on_site"]:
                    needs_replace = True
                    # Replace specific number with qualitative
                    verified_text = make_qualitative_benefit(benefit, label)
                    break

        result["benefits_verified"].append({
            "original": benefit,
            "verified": verified_text,
            "changed": verified_text != benefit,
        })

    return result


def make_qualitative_benefit(text: str, num_label: str) -> str:
    """Replace specific numeric claim with qualitative expression."""
    replacements = {
        "¥970": ("1日定額¥970〜、韓国4G/5G接続", "1日定額制でリーズナブル、韓国4G/5G接続"),
        "¥690": ("韓国eSIM 1日¥690〜、到着前に設定完了", "韓国eSIM お手頃価格、到着前に設定完了"),
        "¥550": ("全品送料¥550、¥5,500以上で送料無料", "リーズナブルな送料、一定額以上で送料無料"),
        "¥5,500": ("全品送料¥550、¥5,500以上で送料無料", "リーズナブルな送料、一定額以上で送料無料"),
        "¥1,650": ("1箱¥1,650〜、ワンデーから長期タイプまで", "お手頃価格、ワンデーから長期タイプまで"),
        "20%": ("最大20%割引クーポン随時配信", "お得な割引クーポン随時配信"),
        "60%": ("厳選高級ホテル、最大60%割引の直前セール", "厳選高級ホテル、お得な直前セール"),
        "5%": ("ポイント最大5%還元、次回予約にも使える", "ポイント還元あり、次回予約にも使える"),
        "4.0": ("口コミ評価4.0以上のホテルを多数掲載", "高評価ホテルを多数掲載"),
        "10%": ("初回購入10%OFF、お得に試せる", "初回購入割引あり、お得に試せる"),
        "¥3,000": ("¥3,000以下のプチプラ韓国服も豊富", "プチプラ韓国服も豊富"),
        "¥800": ("1レッスン¥800〜、お手頃価格で始められる", "1レッスンお手頃価格で始められる"),
        "5台": ("同時接続5台、友達・家族でシェアOK", "複数台同時接続、友達・家族でシェアOK"),
        "200": ("200以上の国と地域で使える安心感", "世界中の国と地域で使える安心感"),
        "200ヵ国": ("200ヵ国以上対応、乗り継ぎ先でもそのまま使える", "多数の国と地域に対応、乗り継ぎ先でもそのまま使える"),
        "10台": ("1台で最大10台同時接続、グループ旅行に最適", "1台で複数台同時接続、グループ旅行に最適"),
        "550": ("550以上の都市で体験が予約できる", "世界中の都市で体験が予約できる"),
    }

    for key_text, (orig, replacement) in replacements.items():
        if key_text == num_label:
            return replacement

    # Generic fallback: remove numbers
    return re.sub(r'[\d,]+[万%円¥]?', '', text).strip()


def main():
    results = {}
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] Starting benefit verification for 13 programs...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(verify_program_benefits, k): k for k, v in BENEFITS_DRAFT.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                results[key] = result
                changed = sum(1 for b in result["benefits_verified"] if b["changed"])
                print(f"  {key}: {changed}/4 benefits needed qualitative replacement")
            except Exception as e:
                print(f"  ❌ {key}: {e}")

    # Summary
    total_changed = sum(
        sum(1 for b in r["benefits_verified"] if b["changed"])
        for r in results.values()
    )
    print(f"\n[SUMMARY] {total_changed}/52 benefits replaced with qualitative expressions")

    output = {
        "_metadata": {
            "created_at": datetime.now(JST).isoformat(),
            "purpose": "Phase 30.1 benefit number verification",
            "total_benefits": 52,
            "changed_count": total_changed,
        },
        "programs": results,
    }

    outpath = "/home/aiuser/kpop-ai-system/cta/verification/benefit_evidence_20260506.json"
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[OUTPUT] {outpath}")


if __name__ == "__main__":
    main()
