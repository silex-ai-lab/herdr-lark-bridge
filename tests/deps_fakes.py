from __future__ import annotations

from collections import deque
from typing import Sequence

from herdr_lark.config import Credentials
from herdr_lark.deps import Deps

from helpers import FakeHerdr, FakeLarkApi, FakeLaunchctl


class DepsRig:
    def __init__(
        self,
        platform: str = "darwin",
        lark_error: str | None = None,
        herdr_binary: str | None = "/opt/fake/bin/herdr",
        herdr_down: bool = False,
        answers: Sequence[str] = (),
        secrets: Sequence[str] = (),
        launchctl: FakeLaunchctl | None = None,
    ) -> None:
        self.lark = FakeLarkApi(lark_error)
        self.herdr = FakeHerdr()
        self.herdr.down = herdr_down
        self.launchctl = launchctl or FakeLaunchctl()
        self.made_for: list[Credentials] = []
        self.prompts: list[str] = []
        self._answers = deque(answers)
        self._secrets = deque(secrets)
        self.deps = Deps(
            make_lark=self._make_lark,
            make_herdr=lambda: self.herdr,
            find_herdr=lambda: herdr_binary,
            launchctl=self.launchctl,
            platform=platform,
            ask=self._ask,
            ask_secret=self._ask_secret,
        )

    def _make_lark(self, creds: Credentials) -> FakeLarkApi:
        self.made_for.append(creds)
        return self.lark

    def _ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._answers:
            raise EOFError
        return self._answers.popleft()

    def _ask_secret(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._secrets:
            raise EOFError
        return self._secrets.popleft()
