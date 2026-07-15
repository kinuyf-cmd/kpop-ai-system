"""factcheck v2 の API 区間が単一インスタンスへ逐次化されること。

背景: 2026-07-15 のコスト調査で、速報パイプラインが複数記事を並列に
pre_publish_gate へ通すため、先行呼び出しの prompt cache write (system
prefix ~12.5k tok) が完了する前に後続が走り、実測 68% が cold write
(cache_read==0) になっていた。cache_create 12.5k tok を毎回書き直す =
factcheck が全API費の 84% を占める主因。_api_serialize_lock で API 区間
(client.messages.create) を逐次化し、先行が cache write を終えてから後続が
cache read hit する順序を保証する。
"""
import threading
import time

import lib.factcheck_v2 as fc


def test_api_lock_serializes_concurrent_sections():
    """2スレッドが同時に lock 区間へ入っても、内部の同時実行数は 1 を超えない。"""
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()

    def worker():
        nonlocal concurrent, max_concurrent
        with fc._api_serialize_lock():
            with lock:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            # API 呼び出しを模した処理時間 (この間 flock が保持される)
            time.sleep(0.05)
            with lock:
                concurrent -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # flock は同一プロセス内でも fd 単位で排他されるため、逐次化されれば 1。
    assert max_concurrent == 1, f"lock 区間が並走した: max_concurrent={max_concurrent}"


def test_api_lock_releases_on_exception():
    """lock 区間内で例外が出ても lock が解放され、後続が取得できること。"""
    class _Boom(Exception):
        pass

    try:
        with fc._api_serialize_lock():
            raise _Boom()
    except _Boom:
        pass

    # 解放されていれば再取得は即座に成功する (デッドロックしない)
    acquired = []

    def acquire():
        with fc._api_serialize_lock():
            acquired.append(True)

    t = threading.Thread(target=acquire)
    t.start()
    t.join(timeout=2.0)
    assert acquired == [True], "例外後に lock が解放されずデッドロックした"
