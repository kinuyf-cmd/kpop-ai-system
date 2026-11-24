"""sanitize_gpt_html の「同じ文字の連打を縮める」処理が、URLや数字を壊さないこと(2026-11-12)。

実害: PR TIMES の出典URL 000000141 → 00141、000001873 → 001873 に化けて 404 になった
(AAA 2026 ハブ post 23390 / MUSIC BANK 国立ハブ post 27634)。
"""
from lib.text_sanitizer import sanitize_gpt_html


def test_url_zeros_in_href_are_kept():
    html = '<p>参考: <a href="https://prtimes.jp/main/html/rd/p/000000141.000058351.html">PR</a></p>'
    assert "000000141.000058351" in sanitize_gpt_html(html)


def test_url_zeros_in_text_are_kept():
    html = "<p>https://prtimes.jp/main/html/rd/p/000001873.000003711.html</p>"
    assert "000001873.000003711" in sanitize_gpt_html(html)


def test_numbers_in_text_are_kept():
    assert "100000人" in sanitize_gpt_html("<p>観客は100000人でした。</p>")


def test_repeated_symbols_in_text_are_still_collapsed():
    out = sanitize_gpt_html("<p>最高でした！！！！！！</p>")
    assert "！！！！！" not in out
    assert "最高でした！！" in out
