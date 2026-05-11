"""2026-05-11 chart pipeline 4層 silent rot 事故の再発防止テスト

事故内容:
  - cron entry cd 欠落で 2週間 chart 記事未公開
  - scraper fallback が `[week, week-1]` のみ (Circle Chart の2週ラグで失敗)
  - assess_residue が body_text に対し _strip_quoted_proper_nouns 未適用
  - ARTIST_JA に新人アーティスト未登録 + `_to_ja` が "English (Korean)" 形式を扱えない

各層の修正がregressionしないよう機械的に検証する。
"""
import json
import os
import re
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

BASE = '/home/aiuser/kpop-ai-system'


def test_scraper_fallback_covers_two_week_lag():
    """tools/scrape_circle_chart.py の fallback が week-2 まで遡ること"""
    src = open(os.path.join(BASE, 'tools/scrape_circle_chart.py')).read()
    assert 'week - 2' in src, "scraper fallback が week-2 を試行しない (Circle Chart 2週ラグで詰まる)"


def test_residue_check_strips_quoted_proper_nouns_in_body():
    """assess_residue が body_text 中の 「...」 内 hangul を除外すること"""
    from lib.translation_residue_check import assess_residue
    # チャート記事の典型: 楽曲名を「」で囲んだ韓国語
    title = "NEXZが首位｜K-POPチャートTOP10【2026年5月第2週】"
    body = ('1位: NEXZ「Mmchk」 2位: CRAVITY「AWAKE」 3位: TWS「널 따라가 (You, You)」 '
            '4位: AKMU「소문의 낙원」 5位: パク・ジフン「Bodyelse」 '
            '6位: AKMU「기쁨, 슬픔, 아름다운 마음」 7位: QWER「CEREMONY」 '
            '8位: TWS「너의 모든 가능성이 되어 줄게」')
    r = assess_residue(title, body)
    assert r['verdict'] == 'PASS', (
        f"チャート記事の「」囲みhangulがBLOCKされる (回帰): {r['reason']} samples={r['samples'][:2]}"
    )


def test_residue_check_still_catches_bare_hangul_in_body():
    """逆方向: 引用符外の生hangulはちゃんとBLOCKされること (defense-in-depth)"""
    from lib.translation_residue_check import assess_residue
    body = "이것은 한국어 본문 텍스트입니다. " * 5  # 20+字、引用符なし
    r = assess_residue('title', body)
    assert r['verdict'] == 'BLOCK', (
        f"引用符外の生hangulが検出されない (gate実質無効化): {r}"
    )


def test_chart_article_artist_to_ja_handles_english_korean_format():
    """chart_article_generator._to_ja が 'English (Korean)' 形式から英語抽出すること"""
    sys.path.insert(0, os.path.join(BASE, 'scripts'))
    from chart_article_generator import _to_ja
    assert _to_ja('NEXZ (넥스지)') == 'NEXZ'
    assert _to_ja('TWS (투어스)') == 'TWS'
    assert _to_ja('AKMU (악뮤)') == 'AKMU'
    # 純Korean は mapping 経由
    assert _to_ja('박지훈') == 'パク・ジフン'
    # 純Englishはそのまま
    assert _to_ja('CRAVITY') == 'CRAVITY'


def test_weekly_job_health_config_exists():
    """config/weekly_job_health.json が存在し、chart_article entryがあること"""
    path = os.path.join(BASE, 'config/weekly_job_health.json')
    assert os.path.exists(path), f"weekly_job_health.json 未生成: {path}"
    cfg = json.load(open(path))
    jobs = cfg.get('jobs', {})
    assert 'chart_article' in jobs, "chart_article ジョブ未登録"
    assert 'chart_scraper' in jobs, "chart_scraper ジョブ未登録"
    assert cfg.get('default_max_age_days', 0) >= 7, "default_max_age_days が短すぎる (週次cron用)"


def test_cron_health_check_imports_weekly_jobs():
    """cron_health_check.py が weekly_job_health.json を読む構造になっていること"""
    src = open(os.path.join(BASE, 'pipeline/cron_health_check.py')).read()
    assert 'weekly_job_health.json' in src or 'WEEKLY_JOB_CONFIG' in src, (
        "cron_health_check が weekly_job_health.json を参照していない"
    )
    assert 'check_weekly_jobs' in src, "check_weekly_jobs 関数が未定義"


def test_chart_cron_entries_have_cd_prefix():
    """crontab.txt の chart 関連エントリが cd プレフィックスを持つこと"""
    crontab = open(os.path.join(BASE, 'crontab.txt')).read()
    chart_lines = [l for l in crontab.splitlines()
                   if ('scrape_circle_chart' in l or 'chart_article_generator' in l)
                   and not l.lstrip().startswith('#')]
    assert chart_lines, "chart 関連 cron entry が crontab.txt に存在しない"
    for line in chart_lines:
        assert 'cd /home/aiuser/kpop-ai-system' in line, (
            f"chart cron entry に cd プレフィックスなし → cwd 不一致で silent fail: {line}"
        )
