"""trending が空のときのフォールバックが、話題の無いアーティストを引かないこと。

2026-08-28実測: 本番ログで ATEEZ の no_fresh_topic が4回。ATEEZ は
シグナル窓(48h)内の候補が0件で trending_artists() に載らないため、
通常経路では選ばれない。にもかかわらず選ばれていたのは、trending が空を
返した時間帯に DEFAULT_ARTIST_POOL からランダムで引くフォールバックが
話題の有無を見ていなかったため。skip は投稿機会の損失なので、
フォールバックでも「話題がある側」から選ぶ。
"""
import lib.x_conversation_starter as cs


def test_fallback_prefers_artists_with_topics(monkeypatch):
    """trending が空でも、話題を持つアーティストがいればそこから選ぶ。"""
    monkeypatch.setattr(cs, "_trending_artists_safe", lambda: [])

    def fake_has_topic(artist):
        return artist in {"IVE", "TWICE"}

    monkeypatch.setattr(cs, "_artist_has_topic", fake_has_topic)
    picks = {cs._weighted_artist({}) for _ in range(30)}
    assert picks <= {"IVE", "TWICE"}, f"話題の無いアーティストを引いた: {picks}"


def test_fallback_still_returns_when_nothing_has_topic(monkeypatch):
    """誰も話題を持たない場合でも例外にせず何か返す(呼出側が skip 判定する)。"""
    monkeypatch.setattr(cs, "_trending_artists_safe", lambda: [])
    monkeypatch.setattr(cs, "_artist_has_topic", lambda a: False)
    got = cs._weighted_artist({})
    assert got in cs.DEFAULT_ARTIST_POOL


def test_normal_path_uses_trending(monkeypatch):
    """trending があるときは従来どおりそこから選ぶ。"""
    monkeypatch.setattr(cs, "_trending_artists_safe", lambda: ["ITZY"])
    monkeypatch.setattr(cs, "_recent_artists", lambda n=4: set())
    assert cs._weighted_artist({}) == "ITZY"


def test_mark_topic_used_is_exposed_for_pipeline():
    """本番(x_scheduled_poster)から使用済み話題を記録できる公開APIがあること。

    2026-08-28: 記録は __main__ 経路にしか無く、本番は generate() を直接呼ぶため
    x_used_topics.jsonl が生成されていなかった(ファイル不在を実測)。
    結果 used_urls が常に空で、同じ話題を再選出しうる状態だった。
    """
    assert hasattr(cs, "mark_topic_used"), "公開APIが無い"


def test_mark_topic_used_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(cs, "USED_TOPICS_FILE", tmp_path / "x_used_topics.jsonl")
    cs.mark_topic_used("https://example.com/a")
    assert (tmp_path / "x_used_topics.jsonl").exists()
    assert "https://example.com/a" in cs._recent_topic_urls()


def test_mark_topic_used_ignores_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(cs, "USED_TOPICS_FILE", tmp_path / "x_used_topics.jsonl")
    cs.mark_topic_used("")
    assert not (tmp_path / "x_used_topics.jsonl").exists()
