"""Tests for rate limiter demonstrating burst control and threshold behavior."""

import asyncio
import pytest

from skytrace.utils.rate_limiter import (
    TokenBucket,
    SlidingWindowRateLimiter,
    RateLimitExceeded,
    create_n2yo_limiter,
)


class TestTokenBucket:
    """Unit tests for the TokenBucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_single_token(self):
        bucket = TokenBucket(capacity=5, refill_rate=10)
        assert await bucket.acquire(1) is True
        assert bucket.available_tokens == pytest.approx(4.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_burst_exceeds_capacity(self):
        bucket = TokenBucket(capacity=3, refill_rate=100)
        # Can acquire 3 immediately
        assert bucket.tokens == 3
        assert await bucket.acquire(3) is True
        # No tokens left; next acquire should fail without wait
        assert await bucket.try_acquire(1) is False

    @pytest.mark.asyncio
    async def test_rate_refill_over_time(self):
        bucket = TokenBucket(capacity=1, refill_rate=10)
        assert bucket.tokens == 1
        # Use the one token
        assert await bucket.acquire(1) is True
        # Try without waiting -- should fail
        assert await bucket.try_acquire(1) is False
        # Wait for refill (10 tokens/sec = 1 per 0.1s)
        await asyncio.sleep(0.15)
        assert await bucket.try_acquire(1) is True

    @pytest.mark.asyncio
    async def test_timeout_on_excessive_request(self):
        bucket = TokenBucket(capacity=1, refill_rate=0.1)
        assert await bucket.acquire(1) is True
        # Request next with tiny timeout -- should fail
        result = await bucket.acquire(1, timeout=0.01)
        assert result is False


class TestSlidingWindowRateLimiter:
    """Unit tests for sliding-window rate limiter."""

    @pytest.mark.asyncio
    async def test_max_requests_enforced(self):
        limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=0.5)
        assert await limiter.try_acquire() is True
        assert await limiter.try_acquire() is True
        # At capacity
        assert await limiter.try_acquire() is False
        # Wait for window to slide
        await asyncio.sleep(0.6)
        assert await limiter.try_acquire() is True

    @pytest.mark.asyncio
    async def test_remaining_counts_correctly(self):
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=1)
        assert limiter.remaining == 3
        await limiter.try_acquire()
        assert limiter.remaining == 2


class TestN2YORateLimiter:
    """Tests for N2YO-configured rate limiter."""

    @pytest.mark.asyncio
    async def test_n2yo_bucket_configuration(self):
        # 800 requests per hour = ~0.222 per second
        limiter = create_n2yo_limiter(requests_per_hour=800, burst=10)
        # Should allow burst of 10
        for _ in range(10):
            assert await limiter.acquire(1) is True
        # 11th should fail immediately
        assert await limiter.try_acquire(1) is False
