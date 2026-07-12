import pytest

from roadstop_scraper.common.rate_limiter import RateLimiter


class _FakeClock:
    """``time.monotonic`` / ``time.sleep`` を差し替える擬似時計。

    ``sleep`` は実際には待機せず、経過時間として現在時刻を進めるだけにすることで、
    待機の有無・待機秒数を高速かつ決定的に検証できるようにする。
    """

    def __init__(self, start: float = 0.0) -> None:
        self.current = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr("roadstop_scraper.common.rate_limiter.time.monotonic", fake.monotonic)
    monkeypatch.setattr("roadstop_scraper.common.rate_limiter.time.sleep", fake.sleep)
    return fake


def test_初期化の検証_負の最小待機時間の場合_ValueErrorを送出する():
    with pytest.raises(ValueError):
        RateLimiter(-1.0)


def test_初期化の検証_ゼロの最小待機時間は許容される():
    RateLimiter(0.0)


def test_待機の検証_初回のwaitは待機せず即座に返る(clock: _FakeClock):
    limiter = RateLimiter(1.0)

    limiter.wait()

    assert clock.sleeps == []


def test_待機の検証_最小待機時間未満での連続waitは不足分だけ待機する(clock: _FakeClock):
    limiter = RateLimiter(1.0)

    limiter.wait()
    clock.advance(0.3)
    limiter.wait()

    assert clock.sleeps == [pytest.approx(0.7)]


def test_待機の検証_最小待機時間以上の間隔が空いていれば待機しない(clock: _FakeClock):
    limiter = RateLimiter(1.0)

    limiter.wait()
    clock.advance(1.5)
    limiter.wait()

    assert clock.sleeps == []
