from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .fsio import atomic_write

PAIRING_TTL_SECONDS = 600.0
MAX_PAIR_FAILURES = 5

PairOutcome = Literal["paired", "wrong", "exhausted", "expired", "unarmed"]


@dataclass(frozen=True)
class Pairing:
    code: str
    expires_at: float
    failures: int = 0


def attempt(p: Pairing | None, text: str, now: float) -> tuple[Pairing | None, PairOutcome]:
    if p is None:
        return None, "unarmed"
    if now >= p.expires_at:
        return None, "expired"
    if hmac.compare_digest(text.strip().encode(), p.code.encode()):
        return None, "paired"
    failures = p.failures + 1
    if failures >= MAX_PAIR_FAILURES:
        return None, "exhausted"
    return replace(p, failures=failures), "wrong"


class PairingStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def arm(self, now: float) -> Pairing:
        p = Pairing(f"{secrets.randbelow(10**6):06d}", now + PAIRING_TTL_SECONDS)
        self.save(p)
        return p

    def save(self, p: Pairing) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(
            self.path,
            json.dumps({"code": p.code, "expires_at": p.expires_at, "failures": p.failures}),
        )

    def load(self) -> Pairing | None:
        try:
            d = json.loads(self.path.read_text())
            return Pairing(str(d["code"]), float(d["expires_at"]), int(d.get("failures", 0)))
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError):
            self.clear()
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class OwnerStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> str | None:
        try:
            lines = self.path.read_text().splitlines()
        except FileNotFoundError:
            return None
        return lines[0].strip() or None if lines else None

    def write(self, open_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.path, open_id + "\n")

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
