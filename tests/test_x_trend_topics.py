#!/usr/bin/env python3
"""lib/x_trend_topics.py のテスト。

守りたい仕様(2026-08-17の実測で判明した欠陥の再発防止):
  1. 期限切れ/古いシグナルを「今の話題」として拾わない
     → focus_themes は295件中258件が3ヶ月前の期限切れで、_pick_theme_for が
       expires_at を無視していたため、5月の話題を今日つぶやいていた。
  2. keyword ではなく title に実際に出るアーティストを主役として扱う
     → 「Stray Kids速報の深掘り: RESCENE、…」のように共演者名の記事が
       Stray Kids の話題として割り当たっていた。
  3. 話題は2段階で扱う。事件・訃報・身体的ハプニング等は扱わない(BLOCKED)。
     噂・疑惑・移籍・体調などは扱ってよいが tone="hedged" を付けて返し、
     生成側が断定しない口調に切り替わるようにする(HEDGE_REQUIRED)。
  4. 話題が無ければ空を返す(空虚な投稿を出さないため、呼出側が投稿を見送れる)。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.x_trend_topics import pick_trend_topic, load_recent_signals  # noqa: E402


def _sig(title, keyword="BTS", hours_ago=1, score=2.0, lang="en", sid="soompi"):
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    return {
        "timestamp": ts, "source": "english_media", "source_id": sid,
        "keyword": keyword, "title": title, "url": f"https://example.com/{abs(hash(title))}",
        "engagement_score": score, "language": lang, "urgency": "normal",
    }


def _write(tmp_path, sigs):
    p = tmp_path / "trend_signals.jsonl"
    p.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in sigs), encoding="utf-8")
    return p


def test_古いシグナルは拾わない(tmp_path):
    """window_h を超えた古いシグナルは候補から外れる(5月の話題を今日つぶやく事故の防止)。"""
    p = _write(tmp_path, [_sig("BTS Announces World Tour", hours_ago=200)])
    assert load_recent_signals(path=p, window_h=48) == []


def test_直近シグナルは拾う(tmp_path):
    p = _write(tmp_path, [_sig("BTS Announces World Tour", hours_ago=3)])
    assert len(load_recent_signals(path=p, window_h=48)) == 1


def test_titleに名前が無ければそのアーティストの話題にしない(tmp_path):
    """keyword=Stray Kids でも title の主役が RESCENE なら Stray Kids には割り当てない。"""
    p = _write(tmp_path, [_sig("RESCENE wins with Love Attack on Inkigayo", keyword="Stray Kids")])
    assert pick_trend_topic("Stray Kids", path=p) is None


def test_titleに名前があれば話題になる(tmp_path):
    p = _write(tmp_path, [_sig("Stray Kids Takes 2nd Win For This & That On Music Bank", keyword="Stray Kids")])
    got = pick_trend_topic("Stray Kids", path=p)
    assert got and "Stray Kids" in got["fact"]


def test_脇役として列挙されただけでは話題にしない(tmp_path):
    """「主役; Performances By 脇役, And More」型の見出しで脇役側に割り当てない。

    実データ(soompi/allkpop)の音楽番組まとめはこの形。従来は title 全体を見て
    いたため、Stray Kids が RESCENE の受賞記事を自分の話題として掴んでいた。
    """
    p = _write(tmp_path, [
        _sig("Watch: RESCENE Takes 2nd Win For LOVE ATTACK On Inkigayo; "
             "Performances By Stray Kids, WayV, And More", keyword="Stray Kids"),
        _sig("RESCENE wins with Love Attack on Inkigayo + performances from "
             "Stray Kids, KiiiKiii, and more!", keyword="Stray Kids"),
    ])
    assert pick_trend_topic("Stray Kids", path=p) is None
    assert pick_trend_topic("RESCENE", path=p) is not None


def test_名前の羅列だけの見出しは話題にしない(tmp_path):
    """「A, B, C, And More Sweep Top Spots」型は誰の話題でもない(中身が無い)。"""
    p = _write(tmp_path, [
        _sig("CORTIS, ATEEZ, BTS, RIIZE, Stray Kids, LE SSERAFIM, Yeonjun, "
             "BOYNEXTDOOR, aespa, And More Sweep Top Spots On Billboard World Albums Chart",
             keyword="ATEEZ", score=4.0),
    ])
    for a in ("ATEEZ", "BTS", "aespa", "LE SSERAFIM"):
        assert pick_trend_topic(a, path=p) is None, a


def test_単語の一部に偶然含まれても話題にしない(tmp_path):
    """IVE が "live" / "revives" の中に埋もれているだけのものを拾わない。

    実データで allkpop の "…still live without personal phones…"(RESCENE の記事)が
    IVE の話題として選ばれていた。名前の照合は語境界で行う必要がある。
    """
    p = _write(tmp_path, [
        _sig("RESCENE reveals all members still live without personal phones", keyword="RESCENE"),
        _sig("Group revives old concept for comeback", keyword="X"),
    ])
    assert pick_trend_topic("IVE", path=p) is None


def test_複数見出しが連結されたシグナルは使わない(tmp_path):
    """koreaherald の一覧ページは「5 見出しA 6 [Exclusive] 見出しB」と連結される。
    どれが誰の話題か特定できないため、種にしない。"""
    p = _write(tmp_path, [
        _sig("5 Fans revisit old BTS clips after V reveals hearing difficulties "
             "6 [Exclusive] Another headline here", keyword="BTS", sid="koreaherald"),
    ])
    assert pick_trend_topic("BTS", path=p) is None


def test_見出しが壊れているソースは種にしない(tmp_path):
    """koreaherald は一覧ページを拾っており、見出しに順位番号や別記事が混入する。
    (例: "6 Twice's Jeongyeon leaves JYP…" / "…collab Most Read K-pop")
    上流の収集を直すまで、この種のソースからは会話の種を取らない。"""
    p = _write(tmp_path, [
        _sig("Something Normal Happens To IVE Today", keyword="IVE", sid="koreaherald"),
    ])
    assert pick_trend_topic("IVE", path=p) is None


def test_批判や疑惑は扱うが断定させない(tmp_path):
    """ニュースメディアなので炎上・疑惑も扱う。ただし tone="hedged" を付けて返し、
    生成側が断定・便乗しない口調に切り替わるようにする。"""
    p = _write(tmp_path, [
        _sig("BLACKPINK Jennie's New Announcement Sparks Wave Of Intense Criticism",
             keyword="BLACKPINK"),
    ])
    got = pick_trend_topic("BLACKPINK", path=p)
    assert got is not None
    assert got["tone"] == "hedged"


def test_日本語見出しの付随言及では話題にしない(tmp_path):
    """「…9月6日に開催決定！BLACKPINK リサ、ジス＆ロゼに続き…」のように、
    句点/感嘆符のあとに参考として名前が出るだけのものは主役ではない。"""
    p = _write(tmp_path, [
        _sig("「日プ新世界」出演イ・ヒョンジェ、初の東京ファンミーティングが9月6日に開催決定！"
             "BLACKPINK リサ、ジス＆ロゼに続き…", keyword="BLACKPINK", lang="ja"),
    ])
    assert pick_trend_topic("BLACKPINK", path=p) is None


def test_所属離脱は扱うが断定させない(tmp_path):
    """「Chaeyoung Announces Departure From JYP」は実際のニュースなので扱う。
    ただし続報で状況が変わりうるため hedged。"""
    p = _write(tmp_path, [
        _sig("TWICE's Chaeyoung Announces Departure From JYP", keyword="TWICE"),
    ])
    got = pick_trend_topic("TWICE", path=p)
    assert got is not None
    assert got["tone"] == "hedged"


def test_噂や憶測は扱えるが必ずhedged(tmp_path):
    """噂・未確認報道も扱ってよいが、断定させないため必ず tone="hedged"。
    ここが plain になると「離脱するらしい」と言い切る投稿が出てしまう。"""
    for title, artist in [
        ("aespa's Giselle Sparks Rumors She's Leaving SM Entertainment", "aespa"),
        ("IVE reportedly in talks for new contract", "IVE"),
        ("TWICE、熱愛説が浮上", "TWICE"),
    ]:
        p = _write(tmp_path, [_sig(title, keyword=artist)])
        got = pick_trend_topic(artist, path=p)
        assert got is not None, title
        assert got["tone"] == "hedged", title


def test_身体的ハプニングは扱わない(tmp_path):
    """本人の意図しない衣装トラブル等は、報道であっても扱わない(尊厳の問題)。
    ニュース性ではなく見世物性で伸びる話題なので、hedge では足りない。"""
    p = _write(tmp_path, [
        _sig("Nip Slip? BLACKPINK Jennie's Viral Summer Sonic Wardrobe Malfunction "
             "Divides The Internet", keyword="BLACKPINK"),
    ])
    assert pick_trend_topic("BLACKPINK", path=p) is None


def test_ステージでの涙は扱うが断定させない(tmp_path):
    """感情が高ぶった場面は扱ってよいが、面白がったり原因を決めつけたりしない。"""
    p = _write(tmp_path, [
        _sig("BLACKPINK's Jennie Tearing Up On Stage During Final Encore",
             keyword="BLACKPINK"),
    ])
    got = pick_trend_topic("BLACKPINK", path=p)
    assert got is not None and got["tone"] == "hedged"


def test_他グループの発言内で言及されただけでは種にしない(tmp_path):
    """「KIIRAS、…ロールモデルはBLACKPINK先輩」は KIIRAS の記事であって
    BLACKPINK の出来事ではない。引用符の中で言及されただけのものは主役にしない。"""
    p = _write(tmp_path, [
        _sig("KIIRAS、ハンドマイクへのこだわりを語る「生歌で勝負したい…ロールモデルはBLACKPINK先輩」",
             keyword="BLACKPINK", lang="ja"),
    ])
    assert pick_trend_topic("BLACKPINK", path=p) is None


def test_体調や欠席は扱うが断定させない(tmp_path):
    """「Han Sits Out Music Core Due To Skin Inflammation」は事実の報道なので
    扱う。ただし容体を勝手に推し量らせないため hedged。"""
    p = _write(tmp_path, [
        _sig("Stray Kids' Han Sits Out Music Core Live Broadcast Due To Skin Inflammation",
             keyword="Stray Kids"),
    ])
    got = pick_trend_topic("Stray Kids", path=p)
    assert got is not None
    assert got["tone"] == "hedged"


def test_週刊まとめ記事は種にしない(tmp_path):
    """「Weekly allkpop: Colde, Stray Kids, KiiiKiii and more」は
    特定の出来事を含まない定期まとめ。"""
    p = _write(tmp_path, [
        _sig("Weekly allkpop: Colde, Stray Kids, KiiiKiii and more", keyword="Stray Kids"),
    ])
    assert pick_trend_topic("Stray Kids", path=p) is None


def test_同じ勢いならポジティブな話題を先に選ぶ(tmp_path):
    """hedged(噂・批判・体調)は扱うが、選択は後回しにする。

    実測(2026-08-17)で、hedge を入れた途端に生成8本中4本が炎上ネタになった。
    書き方を整えても、話題の配分が炎上に寄れば結果は炎上便乗アカウントと同じ。
    ポジティブな出来事が同じ勢いで存在するなら、そちらを先に使う。
    """
    p = _write(tmp_path, [
        _sig("BTS RM Faces Criticism Over Chris Brown Comment", keyword="BTS", score=3.0),
        _sig("BTS Jungkook Tops Spotify Chart With New Single", keyword="BTS", score=3.0),
    ])
    got = pick_trend_topic("BTS", path=p)
    assert got and got["tone"] == "plain"


def test_ポジティブな話題が無ければhedgedを使う(tmp_path):
    """炎上を避けるあまり、報じるべきニュースを一切扱わないのも違う。
    他に無ければ hedged を選んで、断定しない口調で扱う。"""
    p = _write(tmp_path, [
        _sig("BTS RM Faces Criticism Over Chris Brown Comment", keyword="BTS", score=3.0),
    ])
    got = pick_trend_topic("BTS", path=p)
    assert got and got["tone"] == "hedged"


def test_数字や達成を含む話題を優先する(tmp_path):
    """同じアーティストに複数の話題があるとき、具体的な数字・記録・初達成など
    反応を呼ぶ事実を優先する(実測でERが付いたのはこの型だけだった)。"""
    p = _write(tmp_path, [
        _sig("BTS members attend an event in Seoul", keyword="BTS", score=2.0),
        _sig("ARIRANG Becomes BTS's 1st Album To Spend 21 Weeks On UK Official Chart",
             keyword="BTS", score=2.0),
    ])
    got = pick_trend_topic("BTS", path=p)
    assert got and "21 Weeks" in got["fact"]


def test_センシティブ話題は除外(tmp_path):
    p = _write(tmp_path, [_sig("ATEEZ Hongjoong diagnosed with rib fracture 骨折 と 診断", keyword="ATEEZ"),
                          _sig("ATEEZ、逮捕されたと報道", keyword="ATEEZ")])
    got = pick_trend_topic("ATEEZ", path=p)
    assert got is None or "逮捕" not in got["fact"]


def test_話題が無ければNone(tmp_path):
    """種が無いときは None。呼出側はこれを見て投稿を見送る(空虚投稿を出さない)。"""
    p = _write(tmp_path, [_sig("IVE releases new MV", keyword="IVE")])
    assert pick_trend_topic("BLACKPINK", path=p) is None


def test_HTMLエンティティを復号する(tmp_path):
    """soompi の title は &#8220; 等が生で入る。そのまま投稿すると文字化けする。"""
    p = _write(tmp_path, [_sig("TWICE Takes Win For &#8220;Strategy&#8221; Today", keyword="TWICE")])
    got = pick_trend_topic("TWICE", path=p)
    assert got and "&#" not in got["fact"]


def test_スコアが高い話題を優先(tmp_path):
    p = _write(tmp_path, [
        _sig("IVE appears on radio show", keyword="IVE", score=1.0),
        _sig("IVE Announces Comeback With New Album", keyword="IVE", score=4.0),
    ])
    got = pick_trend_topic("IVE", path=p)
    assert got and "Comeback" in got["fact"]


def test_使用済み話題は再選択しない(tmp_path):
    """同じ出来事を繰り返しつぶやかない(使い回し感の防止)。"""
    p = _write(tmp_path, [_sig("IVE Announces Comeback With New Album", keyword="IVE", score=4.0)])
    first = pick_trend_topic("IVE", path=p)
    assert first is not None
    again = pick_trend_topic("IVE", path=p, used_urls={first["url"]})
    assert again is None


def test_トレンドアーティスト一覧はシグナル出現順(tmp_path):
    from lib.x_trend_topics import trending_artists
    p = _write(tmp_path, [
        _sig("IVE Announces Comeback", keyword="IVE", score=4.0),
        _sig("IVE Wins On Music Bank", keyword="IVE", score=3.0),
        _sig("TWICE Announces Japan Dome Tour", keyword="TWICE", score=3.5),
    ])
    got = trending_artists(path=p)
    assert got and got[0] == "IVE"
    assert "TWICE" in got


def test_第三者の病気を感動話として扱わない(tmp_path):
    """「難病の少女にキスをした」型。本人以外の病気を素材として消費すると
    当事者を傷つけ、病名の誤訳も起きやすい(実測で「ソア癌」という訳語が出た)。"""
    p = _write(tmp_path, [
        _sig("BTS's Jimin Kisses Girl With Rare Disease During Concert", keyword="BTS"),
        _sig("Jungkook meets young cancer patient backstage", keyword="BTS"),
    ])
    assert pick_trend_topic("BTS", path=p) is None
