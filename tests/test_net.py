import threading
import time

from agent import net


def test_cap_threads_never_exceeds_limit():
    assert net.cap_threads(True) == net.MAX_THREADS
    assert net.cap_threads(64) == net.MAX_THREADS
    assert net.cap_threads(3) == 3
    assert net.cap_threads(False) is False
    assert net.cap_threads(None) is False
    assert net.cap_threads(1) is False


def test_install_caps_threads_and_limits_concurrency():
    import yfinance as yf

    seen, active, peak = [], [0], [0]
    lock = threading.Lock()

    def fake(*a, **kw):
        with lock:
            seen.append(kw.get("threads"))
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1

    net._installed = False
    yf.download = fake
    net.install()
    ts = [threading.Thread(target=yf.download, args=(["A"],), kwargs={"threads": True}) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(seen) == {net.MAX_THREADS}
    assert peak[0] <= net.MAX_CONCURRENT
