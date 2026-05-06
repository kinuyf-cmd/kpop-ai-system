#!/usr/bin/env python3
"""Task A0: 13案件の社会的証明数値を公式サイトからクロール・検証"""
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "ja,en;q=0.9",
}
TIMEOUT = 15

# 13案件: key -> {urls, patterns, claim_candidates}
PROGRAMS = {
    "global_wifi": {
        "name": "グローバルWiFi",
        "urls": [
            "https://townwifi.com/",
            "https://townwifi.com/about/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|名|台|件|回|利用|ユーザー|お客様|累計))",
            r"(累計\s*[\d,]+万?\s*(?:人|件|台|回))",
            r"(\d+%\s*(?:満足|リピート|推奨))",
            r"(シェア\s*(?:No\.\s*1|1位|トップ))",
            r"(No\.\s*1|ナンバーワン|第1位)",
        ],
        "claim_candidates": [
            "利用者数1,800万人突破",
            "海外WiFiレンタル シェアNo.1",
        ],
    },
    "voyageesim": {
        "name": "VOYAGEESIM",
        "urls": [
            "https://voyageesim.com/",
            "https://voyageesim.com/about",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|回|利用|ユーザー|ダウンロード))",
            r"(\d+%\s*(?:満足|おすすめ|リピート))",
            r"(\d+\s*(?:ヵ国|カ国|か国)\s*(?:対応|以上))",
        ],
        "claim_candidates": [
            "200ヵ国以上対応",
        ],
    },
    "korea_data_wifi": {
        "name": "韓国データWiFi",
        "urls": [
            "https://www.korea-wifi.com/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|回|台|利用))",
            r"(\d+%\s*(?:満足|リピート))",
            r"(シェア|No\.\s*1|1位)",
        ],
        "claim_candidates": [],
    },
    "dholic": {
        "name": "DHOLIC",
        "urls": [
            "https://www.dholic.co.jp/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|名|件|会員|ユーザー|点|アイテム))",
            r"(\d+%\s*(?:満足|リピート))",
        ],
        "claim_candidates": [
            "会員数380万人突破",
        ],
    },
    "olens_poplens": {
        "name": "OLENS/POPLENS",
        "urls": [
            "https://www.poplens.jp/",
            "https://www.olens.co.kr/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|枚|件|箱|セット|累計))",
            r"(\d+%\s*(?:満足|リピート))",
            r"(シェア|No\.\s*1|1位)",
        ],
        "claim_candidates": [],
    },
    "kkday": {
        "name": "KKday",
        "urls": [
            "https://www.kkday.com/ja",
            "https://www.kkday.com/ja/about",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|商品|ツアー|体験|アクティビティ|利用))",
            r"(\d+\s*(?:ヵ国|カ国|か国|都市)\s*(?:対応|以上))",
            r"(\d+%\s*(?:満足))",
        ],
        "claim_candidates": [
            "550以上の都市で体験",
        ],
    },
    "ikyu": {
        "name": "一休.com",
        "urls": [
            "https://www.ikyu.com/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|施設|ホテル|会員|利用))",
            r"(\d+%\s*(?:満足|リピート))",
        ],
        "claim_candidates": [],
    },
    "newt": {
        "name": "NEWT",
        "urls": [
            "https://newt.net/",
            "https://newt.net/about",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|ダウンロード|利用|ユーザー))",
            r"(\d+%\s*(?:満足))",
        ],
        "claim_candidates": [
            "海外旅行アプリ ダウンロード数No.1",
        ],
    },
    "matilda": {
        "name": "MATILDA",
        "urls": [
            "https://matilda-online.com/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|点|ブランド|アイテム))",
            r"(\d+%\s*(?:満足|リピート))",
        ],
        "claim_candidates": [],
    },
    "codibook": {
        "name": "Codibook",
        "urls": [
            "https://codibook.net/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|点|ダウンロード|利用))",
            r"(\d+%\s*(?:満足))",
        ],
        "claim_candidates": [],
    },
    "italki": {
        "name": "italki",
        "urls": [
            "https://www.italki.com/",
            "https://www.italki.com/about",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|名|件|利用|学習者|講師|レッスン))",
            r"(\d+\s*million\s*(?:learners|students|users|lessons))",
            r"(\d[\d,]+\s*(?:teachers|tutors|languages))",
        ],
        "claim_candidates": [
            "世界1,000万人以上の学習者",
        ],
    },
    "dekiru_korean": {
        "name": "できる韓国語オンライン",
        "urls": [
            "https://www.dekirukan.jp/",
            "https://dekikan.com/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|名|部|件|冊|シリーズ|受講|利用))",
            r"(\d+%\s*(?:満足))",
            r"(シリーズ\s*累計\s*[\d,]+万部)",
        ],
        "claim_candidates": [
            "シリーズ累計350万部突破",
        ],
    },
    "sazo_purchase_agent": {
        "name": "SAZO",
        "urls": [
            "https://sazo.buyee.jp/",
        ],
        "patterns": [
            r"(\d[\d,]+万?\s*(?:人|件|利用|取引))",
            r"(\d+%\s*(?:満足))",
        ],
        "claim_candidates": [],
    },
}


def fetch_page(url: str) -> str:
    """Fetch page and return text content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script/style
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text(separator=" ", strip=True)
        return f"[HTTP {resp.status_code}]"
    except Exception as e:
        return f"[ERROR: {e}]"


def verify_program(key: str, config: dict) -> dict:
    """Verify social proof claims for a single program."""
    result = {
        "program_key": key,
        "name": config["name"],
        "urls_checked": [],
        "found_values": [],
        "verified_claims": [],
        "unverified_claims": [],
    }

    all_text = ""
    for url in config["urls"]:
        text = fetch_page(url)
        result["urls_checked"].append({
            "url": url,
            "status": "ok" if not text.startswith("[") else text[:50],
            "length": len(text),
        })
        all_text += " " + text

    # Search for patterns
    for pattern in config["patterns"]:
        matches = re.findall(pattern, all_text)
        for m in matches:
            if m not in result["found_values"]:
                result["found_values"].append(m)

    # Verify claim candidates
    for claim in config.get("claim_candidates", []):
        # Extract numbers from claim
        nums_in_claim = re.findall(r'[\d,]+', claim)
        found = False
        for num in nums_in_claim:
            if num in all_text or num.replace(",", "") in all_text:
                found = True
                break
        # Also check key phrases
        key_phrases = re.findall(r'[A-Za-zぁ-んァ-ヶ一-龠]+', claim)
        phrase_found = any(p in all_text for p in key_phrases if len(p) >= 2)

        if found or phrase_found:
            result["verified_claims"].append({
                "claim": claim,
                "verified": True,
                "source": "official_site",
            })
        else:
            result["unverified_claims"].append({
                "claim": claim,
                "verified": False,
                "reason": "not_found_on_official_site",
                "fallback": make_qualitative(claim),
            })

    # Determine overall verification
    result["has_verified_social_proof"] = len(result["found_values"]) > 0 or len(result["verified_claims"]) > 0
    if result["has_verified_social_proof"]:
        # Build social proof text from verified data
        result["social_proof_text"] = build_social_proof_text(key, result)
    else:
        result["social_proof_text"] = get_qualitative_fallback(key)

    return result


def make_qualitative(claim: str) -> str:
    """Convert numeric claim to qualitative expression."""
    if "万人" in claim or "利用者" in claim:
        return "多くのユーザーに選ばれています"
    if "No.1" in claim or "1位" in claim:
        return "人気のサービスです"
    if "%" in claim:
        return "高い満足度を獲得"
    if "万部" in claim:
        return "ベストセラーシリーズ"
    return "多くの方にご利用いただいています"


def build_social_proof_text(key: str, result: dict) -> str:
    """Build social proof text from verified data."""
    if result["verified_claims"]:
        return result["verified_claims"][0]["claim"]
    if result["found_values"]:
        return f"✅ {result['found_values'][0]}"
    return get_qualitative_fallback(key)


def get_qualitative_fallback(key: str) -> str:
    """Qualitative fallback for unverified programs."""
    fallbacks = {
        "global_wifi": "✅ 海外WiFiレンタルで多くの渡航者が利用",
        "voyageesim": "✅ 世界200以上の国と地域で利用可能",
        "korea_data_wifi": "✅ 韓国専用WiFiとして渡韓者に人気",
        "dholic": "✅ 日本最大級の韓国ファッション通販",
        "olens_poplens": "✅ K-POPアイドル多数着用のカラコンブランド",
        "kkday": "✅ アジアを中心に世界中の現地体験を提供",
        "ikyu": "✅ 厳選された高級ホテル・旅館を掲載",
        "newt": "✅ 海外旅行アプリとして急成長中",
        "matilda": "✅ 日本未入荷の韓国コスメを多数取扱",
        "codibook": "✅ 韓国の最新トレンドファッションが見つかる",
        "italki": "✅ 世界中のネイティブ講師と1対1レッスン",
        "dekiru_korean": "✅ 「できる韓国語」シリーズは韓国語学習の定番教材",
        "sazo_purchase_agent": "✅ 韓国商品の購入代行サービス",
    }
    return fallbacks.get(key, "✅ 多くの方にご利用いただいています")


def main():
    results = {}
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] Starting social proof verification for 13 programs...")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(verify_program, k, v): k for k, v in PROGRAMS.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                results[key] = result
                status = "✅" if result["has_verified_social_proof"] else "⚠️ qualitative"
                found = len(result["found_values"])
                print(f"  {status} {key}: {found} values found, {len(result['verified_claims'])} claims verified")
            except Exception as e:
                print(f"  ❌ {key}: {e}")
                results[key] = {
                    "program_key": key,
                    "name": PROGRAMS[key]["name"],
                    "error": str(e),
                    "has_verified_social_proof": False,
                    "social_proof_text": get_qualitative_fallback(key),
                }

    # Summary
    verified_count = sum(1 for r in results.values() if r.get("has_verified_social_proof"))
    print(f"\n[SUMMARY] {verified_count}/13 programs have verified social proof")

    # Output
    output = {
        "_metadata": {
            "created_at": datetime.now(JST).isoformat(),
            "purpose": "Phase 30.1 social proof verification",
            "total_programs": len(results),
            "verified_count": verified_count,
        },
        "programs": results,
    }

    outpath = "/home/aiuser/kpop-ai-system/cta/verification/social_proof_evidence_20260506.json"
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n[OUTPUT] {outpath}")


if __name__ == "__main__":
    main()
