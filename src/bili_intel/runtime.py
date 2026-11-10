"""Bounded per-stage concurrency and process-local rolling minute API quotas."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import BoundedSemaphore, Condition
from time import monotonic


@dataclass
class StageLimits:
    def __init__(self, network: int = 1, asr: int = 1, llm: int = 2,
                 rpm: int = 30, tpm: int = 60000):
        if min(network, asr, llm, rpm, tpm) < 1:
            raise ValueError('All concurrency and rate limits must be positive')
        self.network = BoundedSemaphore(network)
        self.asr = BoundedSemaphore(asr)
        self.llm = BoundedSemaphore(llm)
        self.limiter = RollingMinuteLimiter(rpm, tpm)


class RollingMinuteLimiter:
    """Process-local admission control; not a multi-host or global account quota."""
    def __init__(self, rpm: int, tpm: int):
        self.rpm, self.tpm = rpm, tpm
        self.events: deque[tuple[float, int]] = deque()
        self.lock = Condition()

    def acquire(self, estimated_tokens: int) -> None:
        if estimated_tokens < 1 or estimated_tokens > self.tpm:
            raise ValueError('Request exceeds configured TPM; lower token budgets or raise TPM')
        with self.lock:
            while True:
                now = monotonic()
                while self.events and self.events[0][0] <= now - 60:
                    self.events.popleft()
                tokens = sum(n for _, n in self.events)
                if len(self.events) < self.rpm and tokens + estimated_tokens <= self.tpm:
                    self.events.append((now, estimated_tokens))
                    return
                self.lock.wait(timeout=max(.05, 60 - (now - self.events[0][0])))
