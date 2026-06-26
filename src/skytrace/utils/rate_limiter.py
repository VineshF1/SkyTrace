"""Rate limiters: stop us from hitting APIs too fast.

Two types:
- TokenBucket: lets short bursts through, then slows down
- SlidingWindow: tracks requests over a time window

N2YO allows 1000 requests/hour. We set ours to 800 to stay safe.
Nominatim allows 1 request/second - separate limiter for that.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket rate limiter - thread-safe for asyncio."""
    capacity: int
    refill_rate: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()
    
    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
    
    async def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        deadline = time.monotonic() + timeout if timeout else None
        
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            needed = tokens - self.tokens
            wait_time = needed / self.refill_rate
        
            if deadline and time.monotonic() + wait_time > deadline:
                return False
        
        await asyncio.sleep(wait_time)
        
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def try_acquire(self, tokens: int = 1) -> bool:
        async with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    @property
    def available_tokens(self) -> float:
        self._refill()
        return self.tokens


class SlidingWindowRateLimiter:
    """Sliding window rate limiter for precise control."""
    
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: list[float] = []
        self._lock = asyncio.Lock()
    
    def _prune_old_requests(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._requests = [t for t in self._requests if t > cutoff]
    
    async def acquire(self, timeout: Optional[float] = None) -> bool:
        deadline = time.monotonic() + timeout if timeout else None
        
        while True:
            async with self._lock:
                now = time.monotonic()
                self._prune_old_requests(now)
                
                if len(self._requests) < self.max_requests:
                    self._requests.append(now)
                    return True
                
                oldest = self._requests[0]
                wait_time = oldest + self.window_seconds - now
            
            if deadline and time.monotonic() + wait_time > deadline:
                return False
            
            if wait_time > 0:
                await asyncio.sleep(min(wait_time, 0.1))
    
    async def try_acquire(self) -> bool:
        async with self._lock:
            now = time.monotonic()
            self._prune_old_requests(now)
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return True
            return False
    
    @property
    def remaining(self) -> int:
        now = time.monotonic()
        self._prune_old_requests(now)
        return max(0, self.max_requests - len(self._requests))


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


def create_n2yo_limiter(requests_per_hour: int = 800, burst: int = 10) -> TokenBucket:
    refill_rate = requests_per_hour / 3600.0
    return TokenBucket(capacity=burst, refill_rate=refill_rate)


def create_sliding_n2yo_limiter(requests_per_hour: int = 800) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(max_requests=requests_per_hour, window_seconds=3600)