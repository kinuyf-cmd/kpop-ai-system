#!/usr/bin/env python3
"""daily_health_check.py — パイプライン統合ヘルスチェック(2026-07-02)

過去の実損(SEOスキャナ3週停止 / Soompiチャート停滞 / popup更新停止 /
サムネconfig欠落1.5ヶ月 / DALL-E率25%を体感で発見)の再発を構造的に防ぐ、
「成果物の鮮度」ベースの watchdog。cronログでなく実際の出力ファイルを見る
(ログは動いていても成果物が腐っているケースを検知するため)。

チェック項目:
  A. 成果物鮮度   — 主要jsonl/jsonの最終更新が閾値内か
  B. DALL-E率     — 昨日公開の採用sourceに占めるdalle比率(>40%でWARN)
  C. 公開品質     — 昨日の公開数/サムネsource内訳/ゲートWARN数のダイジェスト
  D. 必須config   — サムネ等の必須configファイル実在チェック
  E. GSC急落     — 直近7d clicksが前7d比 -30% 以下でWARN(GSC遅延3日考慮)

通知ポリシー(異常時のみ=普段は見なくていい):
  - WARN/FAIL が1件以上 → Discord alert_summary へ要約を送信
  - 全PASS → 通知なし。ログ(logs/health_check.jsonl)にのみ記録
  - 既知課題の抑制: config/health_check_ack.json に key を書くとそのWARNを
    "ACK"扱いにして通知から除外(直せない既知問題で毎日鳴るのを防ぐ)

使い方:
  venv_kpi/bin/python3 tools/health/daily_health_check.py           # 実行+異常時通知
  venv_kpi/bin/python3 tools/health/daily_health_check.py --dry-run # 通知せず表示のみ
  venv_kpi/bin/python3 tools/health/daily_health_check.py --force-notify # 正常でも送る(疎通確認)

課金なし。GSC/ファイル読み取りとDiscord webhook POSTのみ。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from lib.disk_guard import check_disk, free_gb  # noqa: E402
from lib.jsonl_integrity import find_broken  # noqa: E402
LOG_OUT = BASE / "logs" / "health_check.jsonl"
ACK_FILE = BASE / "config" / "health_check_ack.json"
SA = BASE / "google_metrics" / "service_account.json"
SITE = "https://www.kpopjournal.tokyo/"

# A. 成果物鮮度の定義: (key, path, 最大許容時間h, 説明)
# 注: Soompiチャートは上流(Soompi社)未発行でも成果物が古くなる(フェイルセーフで
# stale維持が正常動作)ため、自パイプラインの死活は「cron実行ログ」で見る。
# 土日月 07:30/19:30 実行 → 最長ギャップは月19:30→土07:30の約4.5日 → 閾値5.5日。
# 成果物側は21日の長期閾値で「上流が異常に長く止まっている」ことだけ検知する。
FRESHNESS = [
    ("breaking",      BASE / "logs/breaking_articles.jsonl",   26,  "速報パイプライン"),
    ("publish",       BASE / "logs/unified_publish.jsonl",     26,  "統一公開ログ"),
    ("soompi_cron",   BASE / "logs/cron_soompi_chart_update.log", 5.5 * 24, "Soompiチャート更新cron(自パイプライン死活)"),
    ("soompi_chart",  BASE / "data/soompi_chart_top10.json",   21 * 24, "Soompiチャート成果物(上流長期停止検知)"),
    ("seo_scanner",   BASE / "data/seo_opportunity_queue.json", 8 * 24, "SEO機会スキャナ(週次)"),
    ("x_posts",       BASE / "logs/x_posts.jsonl",             26,  "X自動投稿"),
]

# D. 必須config(欠落すると品質が静かに劣化するもの)
REQUIRED_CONFIGS = [
    ("cfg_concrete", BASE / "config/concrete_vs_abstract.json", "記事分類(サムネ精度に影響)"),
    ("cfg_themes",   BASE / "config/article_themes.json",       "テーマ別サムネ設定"),
    ("cfg_youtube",  BASE / "config/official_accounts.json",    "YouTube本人写真ソース"),
]

DALLE_WARN_RATIO = 0.40   # 昨日公開のDALL-E採用比がこれを超えたらWARN
GSC_DROP_WARN = -0.30     # 7d clicks 前週比がこれ以下でWARN


def _now():
    return datetime.datetime.now()


def check_freshness(results):
    for key, path, max_h, label in FRESHNESS:
        if not path.exists():
            results.append(("FAIL", f"fresh_{key}", f"{label}: 成果物が存在しない ({path.name})"))
            continue
        age_h = (_now().timestamp() - path.stat().st_mtime) / 3600
        if age_h > max_h:
            results.append(("WARN", f"fresh_{key}",
                            f"{label}: {age_h/24:.1f}日更新なし (閾値{max_h/24:.1f}日) — cron停止疑い"))
        else:
            results.append(("PASS", f"fresh_{key}", f"{label}: {age_h:.1f}h前に更新"))


def _yesterday_publishes():
    """unified_publish.jsonl から昨日(ローカル日付)の成功公開を返す"""
    y = (_now() - datetime.timedelta(days=1)).date().isoformat()
    rows = []
    try:
        with open(BASE / "logs/unified_publish.jsonl", encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("success") and str(r.get("ts", "")).startswith(y):
                    rows.append(r)
    except FileNotFoundError:
        pass
    return y, rows


def _source_of(r):
    for x in r.get("log", []):
        if "media_id:" in x and "(" in x:
            return x.split("(", 1)[1].rstrip(")")
    return "no_thumb"


def check_publish_quality(results, digest):
    y, rows = _yesterday_publishes()
    digest["date"] = y
    digest["published"] = len(rows)
    if not rows:
        # 公開ゼロ自体は速報が無い日もあるので INFO 扱い(鮮度チェックが別途見る)
        results.append(("PASS", "quality", f"昨日({y})の公開: 0件"))
        return
    import collections
    src = collections.Counter()
    gate_warns = 0
    for r in rows:
        s = _source_of(r).lower()
        if "dalle" in s:
            src["dalle"] += 1
        elif "source_site" in s or ("og" in s and "artist" not in s):
            src["og"] += 1
        elif "artist" in s or "cache" in s or "wikimedia" in s:
            src["artist_photo"] += 1
        else:
            src["other"] += 1
        gate_warns += sum(1 for x in r.get("log", []) if "Gate WARN" in x)
    digest["thumb_sources"] = dict(src)
    digest["gate_warns"] = gate_warns
    ratio = src["dalle"] / len(rows)
    digest["dalle_ratio"] = round(ratio, 3)
    if ratio > DALLE_WARN_RATIO:
        results.append(("WARN", "dalle_ratio",
                        f"DALL-E採用率 {ratio*100:.0f}% ({src['dalle']}/{len(rows)}) — "
                        f"閾値{DALLE_WARN_RATIO*100:.0f}%超。og取得/本人写真cacheの劣化疑い"))
    else:
        results.append(("PASS", "dalle_ratio",
                        f"DALL-E採用率 {ratio*100:.0f}% ({src['dalle']}/{len(rows)})"))
    results.append(("PASS", "quality",
                    f"昨日({y})公開{len(rows)}件: og={src['og']} 本人={src['artist_photo']} "
                    f"dalle={src['dalle']} 他={src['other']} / GateWARN={gate_warns}件"))


def check_disk_space(results, digest):
    """ディスク残量。2026-08-29 に満杯で collect-all 8/14 が落ち、
    その日の記事収集が欠損した。落ちた事実がログに埋もれて誰も気付かなかったので、
    ここで先に鳴らす([[disk-full-silent-collector-loss]])。"""
    level, msg = check_disk()
    digest["disk_free_gb"] = round(free_gb(), 1)
    results.append((level, "disk_space", msg))


def check_jsonl_integrity(results, digest):
    """jsonl の破損を検知する。2026-08-29 のディスク満杯で追記が切れ、
    次レコードが同じ行に連結する破損が 8 ファイルで発生していた。
    読み手は try/except で握るため**1行黙って欠落**し、誰も気付けない
    ([[disk-full-silent-collector-loss]])。"""
    broken = find_broken()
    digest["jsonl_broken_files"] = len(broken)
    if not broken:
        results.append(("PASS", "jsonl_integrity", "jsonl 破損: なし"))
        return
    head = ", ".join(f"{p.name}({n}行)" for p, n in broken[:3])
    more = f" 他{len(broken)-3}件" if len(broken) > 3 else ""
    results.append(("WARN", "jsonl_integrity",
                    f"jsonl 破損 {len(broken)}ファイル: {head}{more} — 追記中断の疑い(dedup/台帳が黙って欠落)"))


def check_configs(results):
    for key, path, label in REQUIRED_CONFIGS:
        if path.exists():
            results.append(("PASS", key, f"config OK: {path.name}"))
        else:
            results.append(("WARN", key, f"必須config欠落: {path.name} ({label})"))


def check_adsense_token(results, digest):
    """AdSense OAuth トークンの生存を監視する。

    2026-07-31 実測: refresh_token が7日周期で失効していた(7/17再認証 → 7/22からNG)。
    これは OAuth 同意画面の公開ステータスが「テスト」の場合の挙動。
    従来は metrics 取得時に WARN が出るだけで放置され、収益データが
    7日以上欠測しても気付けなかったため、health_check の項目として明示する。

    注: ここでは実際に refresh を試さない。同一 client_id × アカウントの
    refresh_token には発行数上限(~100)があり、無用なフロー実行は自己失効を
    誘発する。ローカルの token 更新時刻だけで判定する。
    復旧手順は docs/adsense_oauth_reauth_runbook.md。
    """
    token_path = BASE / "google_metrics" / "adsense_token.json"
    if not token_path.exists():
        results.append(("WARN", "adsense_token",
                        "adsense_token.json が存在しない → runbook で再認証が必要"))
        return
    # 2026-08-29: ディスク満杯で書き込みが切れ token が **0バイト**になった。
    # mtime は更新されるので鮮度判定だけでは PASS になり、3日欠測に気付けなかった。
    # 中身の妥当性まで見る([[disk-full-silent-collector-loss]])。
    try:
        raw = token_path.read_text(encoding="utf-8").strip()
        if not raw:
            results.append(("FAIL", "adsense_token",
                            "adsense_token.json が空(0バイト) — 書き込み中断の疑い。"
                            "AdSense収益が欠測中。復旧: docs/adsense_oauth_reauth_runbook.md"))
            return
        json.loads(raw)
    except (OSError, ValueError):
        results.append(("FAIL", "adsense_token",
                        "adsense_token.json が壊れている(JSON不正) — "
                        "AdSense収益が欠測中。復旧: docs/adsense_oauth_reauth_runbook.md"))
        return

    age_h = (datetime.datetime.now().timestamp() - token_path.stat().st_mtime) / 3600
    digest["adsense_token_age_h"] = round(age_h, 1)
    # 正常なら cron(毎朝8:30)が refresh して mtime を更新する。
    # 48h 以上更新されていない = refresh に失敗し続けている。
    if age_h >= 48:
        results.append(("WARN", "adsense_token",
                        f"AdSenseトークンが{age_h/24:.1f}日間更新されていない"
                        f"(refresh_token失効の疑い)。"
                        f"復旧: docs/adsense_oauth_reauth_runbook.md"))
    else:
        results.append(("PASS", "adsense_token",
                        f"AdSenseトークン: {age_h:.1f}h前に更新"))


def check_gsc_drop(results, digest):
    if not SA.exists():
        results.append(("WARN", "gsc", "service_account.json が無くGSCチェック不可"))
        return
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds = service_account.Credentials.from_service_account_file(
            str(SA), scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

        def clicks(back):
            end = datetime.date.today() - datetime.timedelta(days=3 + back)
            start = end - datetime.timedelta(days=6)
            r = svc.searchanalytics().query(siteUrl=SITE, body={
                "startDate": start.isoformat(), "endDate": end.isoformat(),
                "dimensions": []}).execute().get("rows", [{}])
            return (r[0] if r else {}).get("clicks", 0)
        cur, prev = clicks(0), clicks(7)
        digest["gsc_7d_clicks"] = cur
        digest["gsc_prev7d_clicks"] = prev
        if prev > 20:  # 母数が小さすぎる時は判定しない
            delta = (cur - prev) / prev
            if delta <= GSC_DROP_WARN:
                results.append(("WARN", "gsc_drop",
                                f"GSC 7d clicks 急落: {cur:.0f} (前週{prev:.0f}, {delta*100:+.0f}%)"))
            else:
                results.append(("PASS", "gsc_drop",
                                f"GSC 7d clicks: {cur:.0f} (前週比{delta*100:+.0f}%)"))
        else:
            results.append(("PASS", "gsc_drop", f"GSC 7d clicks: {cur:.0f} (母数小で急落判定スキップ)"))
    except Exception as e:
        results.append(("WARN", "gsc", f"GSCチェック失敗: {str(e)[:80]}"))


def check_meta_null(results, digest):
    """直近3日の公開記事でAIOSEOメタdesc未設定を検出
    ([[aioseo-meta-in-wp-aioseo-posts-table]]: メタは wp_aioseo_posts.description)。
    注: kpop-wp-ro の出力は1行目がカラムヘッダ([[wp-ro-db-query-header-literal-newline-trap]])。
    """
    # 実レンダリングのメタは post_excerpt からの AIOSEO フォールバックでも生成される
    # (unified_publisher が excerpt=meta_desc を渡す設計)ため、
    # 「aioseo desc と excerpt が両方空」の記事だけが真のメタ欠落(2026-07-02実測で確認)。
    q = ("SELECT COUNT(*) FROM wp_posts p "
         "LEFT JOIN wp_aioseo_posts a ON a.post_id=p.ID "
         "WHERE p.post_type='post' AND p.post_status='publish' "
         "AND p.post_date >= DATE_SUB(NOW(), INTERVAL 3 DAY) "
         "AND (a.description IS NULL OR a.description='') "
         "AND (p.post_excerpt IS NULL OR p.post_excerpt='')")
    try:
        r = subprocess.run(["sudo", "-n", "/usr/local/sbin/kpop/kpop-wp-ro", "db", "query", q],
                           capture_output=True, text=True, timeout=30)
        lines = [x for x in r.stdout.strip().splitlines() if x.strip()]
        n = int(lines[-1]) if lines and lines[-1].isdigit() else None
        if n is None:
            results.append(("WARN", "meta_null", f"メタNULL検査の出力解釈不能: {r.stdout[:60]!r}"))
            return
        digest["meta_null_3d"] = n
        if n > 0:
            results.append(("WARN", "meta_null",
                            f"直近3日公開でメタdesc未設定 {n}件 — CTR取りこぼしの温床"
                            f"([[ctr-meta-optimization-20260615]]同型)"))
        else:
            results.append(("PASS", "meta_null", "直近3日公開のメタdesc未設定: 0件"))
    except Exception as e:
        results.append(("WARN", "meta_null", f"メタNULL検査失敗: {str(e)[:60]}"))


def load_acks():
    try:
        with open(ACK_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("ack", []))
    except Exception:
        return set()


def notify_discord(text):
    """alert_summary チャネルへ送信。resolve_discord_webhook.py 一元化+UA必須
    ([[discord-notify-global-repair-20260602]] 準拠)。"""
    try:
        url = subprocess.run(
            [sys.executable, str(BASE / "lib/resolve_discord_webhook.py"), "alert_summary"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not url.startswith("https://discord.com/api/webhooks/"):
            print("WARN: webhook解決失敗、通知スキップ", file=sys.stderr)
            return False
        body = json.dumps({"content": text[:1900]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "kpop-health-check/1.0 (github.com/kpop-ai-system)"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"WARN: Discord通知失敗: {e}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser(description="パイプライン統合ヘルスチェック")
    ap.add_argument("--dry-run", action="store_true", help="通知せず表示のみ")
    ap.add_argument("--force-notify", action="store_true", help="全PASSでも通知(疎通確認)")
    args = ap.parse_args()

    results = []   # (level, key, message)
    digest = {}
    check_freshness(results)
    check_publish_quality(results, digest)
    check_configs(results)
    check_disk_space(results, digest)
    check_jsonl_integrity(results, digest)
    check_meta_null(results, digest)
    check_gsc_drop(results, digest)
    check_adsense_token(results, digest)

    acks = load_acks()
    active = [(lv, k, m) for lv, k, m in results if lv != "PASS" and k not in acks]
    acked = [(lv, k, m) for lv, k, m in results if lv != "PASS" and k in acks]

    # 表示
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "🔴"}
    print(f"═══ ヘルスチェック {_now().strftime('%Y-%m-%d %H:%M')} ═══")
    for lv, k, m in results:
        ack = " [ACK]" if (lv != "PASS" and k in acks) else ""
        print(f"  {icon[lv]} {m}{ack}")
    print(f"\n異常(通知対象): {len(active)}件 / ACK済: {len(acked)}件")

    # 記録(常に)
    LOG_OUT.parent.mkdir(exist_ok=True)
    with open(LOG_OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": _now().isoformat(), "digest": digest,
            "results": [{"level": lv, "key": k, "msg": m} for lv, k, m in results],
            "active_alerts": len(active),
        }, ensure_ascii=False) + "\n")

    # 通知(異常時のみ)
    if (active or args.force_notify) and not args.dry_run:
        lines = [f"🏥 **ヘルスチェック** {_now().strftime('%m/%d %H:%M')} — 異常 {len(active)}件"]
        for lv, k, m in active:
            lines.append(f"{icon[lv]} {m}")
        if not active:
            lines.append("✅ 全項目正常(疎通確認送信)")
        d = digest
        if d.get("published") is not None:
            lines.append(f"\n昨日: 公開{d.get('published')}件 "
                         f"dalle率{d.get('dalle_ratio', 0)*100:.0f}% "
                         f"GSC7d {d.get('gsc_7d_clicks', '?')}clk")
        notify_discord("\n".join(lines))
        print("→ Discord通知送信")
    sys.exit(1 if any(lv == "FAIL" for lv, k, m in active) else 0)


if __name__ == "__main__":
    main()
