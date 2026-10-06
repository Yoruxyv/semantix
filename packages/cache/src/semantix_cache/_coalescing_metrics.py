"""Fixed numeric ledger. Flights owns synchronization and failure isolation."""

from dataclasses import dataclass
from typing import Literal

Counter = Literal[
    "leaders_admitted",
    "followers_joined",
    "admissions_declined",
    "follower_hits",
    "follower_generated",
    "follower_errors",
    "follower_cancelled",
    "follower_timeouts",
    "follower_generations_started",
]
Terminal = Literal[
    "follower_hits",
    "follower_generated",
    "follower_errors",
    "follower_cancelled",
    "follower_timeouts",
]


@dataclass(slots=True)
class Ledger:
    leaders_admitted: int = 0
    followers_joined: int = 0
    admissions_declined: int = 0
    follower_hits: int = 0
    follower_generated: int = 0
    follower_errors: int = 0
    follower_cancelled: int = 0
    follower_timeouts: int = 0
    follower_generations_started: int = 0
    wait_count: int = 0
    wait_seconds: float = 0.0

    def increment(self, counter: Counter) -> None:
        setattr(self, counter, getattr(self, counter) + 1)

    def waited(self, seconds: float) -> None:
        self.wait_count += 1
        self.wait_seconds += seconds

    def copy(
        self,
    ) -> tuple[int, int, int, int, int, int, int, int, int, int, int, float]:
        pending = self.followers_joined - (
            self.follower_hits
            + self.follower_generated
            + self.follower_errors
            + self.follower_cancelled
            + self.follower_timeouts
        )
        return (
            self.leaders_admitted,
            self.followers_joined,
            self.admissions_declined,
            self.follower_hits,
            self.follower_generated,
            self.follower_errors,
            self.follower_cancelled,
            self.follower_timeouts,
            self.follower_generations_started,
            pending,
            self.wait_count,
            self.wait_seconds,
        )
