import json
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterator

import lark_oapi as lark  # pyright: ignore[reportMissingTypeStubs]
import pytest

from herdr_lark.config import (
    ConfigError,
    Credentials,
    load_config,
    load_credentials,
    write_credentials,
)
from herdr_lark.lark import LarkError, api_base, fetch_tenant_token


def creds_file(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "credentials.env"
    p.write_text(body)
    p.chmod(0o600)
    return p


def test_domain_defaults_to_lark(tmp_path: Path):
    c = load_credentials(creds_file(tmp_path, "LARK_APP_ID=a\nLARK_APP_SECRET=b\n"))
    assert c.domain == "lark"


def test_feishu_domain_is_parsed(tmp_path: Path):
    c = load_credentials(creds_file(tmp_path, "LARK_APP_ID=a\nLARK_APP_SECRET=b\nLARK_DOMAIN=feishu\n"))
    assert c.domain == "feishu"


def test_unknown_domain_is_rejected_at_the_boundary(tmp_path: Path):
    with pytest.raises(ConfigError, match="LARK_DOMAIN"):
        load_credentials(creds_file(tmp_path, "LARK_APP_ID=a\nLARK_APP_SECRET=b\nLARK_DOMAIN=china\n"))


def test_write_credentials_round_trips_with_mode_0600(tmp_path: Path):
    p = write_credentials(Credentials("cli_a", "sec", "feishu"), tmp_path / "d" / "credentials.env")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert load_credentials(p) == Credentials("cli_a", "sec", "feishu")


def test_api_base_matches_the_sdk_constants(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("HERDR_LARK_API_BASE", raising=False)
    assert api_base("lark") == lark.LARK_DOMAIN == "https://open.larksuite.com"
    assert api_base("feishu") == lark.FEISHU_DOMAIN == "https://open.feishu.cn"


def test_api_base_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HERDR_LARK_API_BASE", "http://127.0.0.1:1")
    assert api_base("feishu") == "http://127.0.0.1:1"


def test_lang_defaults_to_zh_and_accepts_en(tmp_path: Path):
    assert load_config(tmp_path / "none.toml").lang == "zh"
    p = tmp_path / "config.toml"
    p.write_text('lang = "en"\npoll_seconds = 5\n')
    assert load_config(p).lang == "en" and load_config(p).poll_seconds == 5.0


@pytest.mark.parametrize("body", ['lang = "fr"', "lang = 3"])
def test_bad_lang_is_rejected(tmp_path: Path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body)
    with pytest.raises(ConfigError, match="lang"):
        load_config(p)


class TokenServer:
    def __init__(self, reply: dict[str, object], status: int = 200) -> None:
        self.requests: list[dict[str, str]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                n = int(self.headers["Content-Length"])
                outer.requests.append({"path": self.path, **json.loads(self.rfile.read(n))})
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

            def log_message(self, *a: object) -> None:
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def serve() -> Iterator[list[TokenServer]]:
    made: list[TokenServer] = []
    yield made
    for s in made:
        s.httpd.shutdown()


def test_token_fetch_posts_credentials_and_accepts_code_zero(serve: list[TokenServer]):
    s = TokenServer({"code": 0, "tenant_access_token": "t-1", "expire": 7200})
    serve.append(s)
    fetch_tenant_token(s.base, "cli_a", "sec")
    assert s.requests == [
        {"path": "/open-apis/auth/v3/tenant_access_token/internal", "app_id": "cli_a", "app_secret": "sec"}
    ]


def test_token_fetch_reports_the_lark_error(serve: list[TokenServer]):
    s = TokenServer({"code": 10003, "msg": "invalid param"}, status=400)
    serve.append(s)
    with pytest.raises(LarkError, match="10003"):
        fetch_tenant_token(s.base, "cli_a", "bad")


def test_token_fetch_reports_an_unreachable_endpoint():
    with pytest.raises(LarkError, match="cannot reach"):
        fetch_tenant_token("http://127.0.0.1:1", "a", "b")
