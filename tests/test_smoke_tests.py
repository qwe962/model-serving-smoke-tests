from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from model_serving_smoke_tests.cli import main
from model_serving_smoke_tests.core import (
    Config,
    Redactor,
    SmokeRunner,
    report_exit_code,
)

API_KEY = "unit-test-user-secret"
ADMIN_KEY = "unit-test-admin-secret"


class MockHandler(BaseHTTPRequestHandler):
    cors_enabled = True
    last_json: dict | None = None

    def log_message(self, format, *args):  # noqa: A002
        return

    def _authorized(self, key: str) -> bool:
        return self.headers.get("Authorization") == f"Bearer {key}"

    def _send(self, status: int, body: dict | None = None, **headers: str) -> None:
        payload = json.dumps(body or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        headers = {}
        if self.cors_enabled:
            headers["Access-Control-Allow-Origin"] = self.headers.get("Origin", "*")
        self._send(204, **headers)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        elif self.path == "/v1/models":
            if not self._authorized(API_KEY):
                self._send(401, {"error": "unauthorized"})
            else:
                self._send(200, {"data": [{"id": "test-model"}]})
        elif self.path == "/admin/status":
            if not self._authorized(ADMIN_KEY):
                self._send(401, {"error": "unauthorized"})
            else:
                self._send(200, {"status": "ok"})
        elif self.path == "/v1/videos/job-1":
            if not self._authorized(API_KEY):
                self._send(401, {"error": "unauthorized"})
            else:
                self._send(200, {"id": "job-1", "status": "completed"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        type(self).last_json = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/admin/checksum":
            if not self._authorized(ADMIN_KEY):
                self._send(401, {"error": "unauthorized"})
            else:
                self._send(400, {"error": "required fields are missing"})
            return
        if not self._authorized(API_KEY):
            self._send(401, {"error": "unauthorized"})
        elif self.path == "/v1/chat/completions":
            self._send(
                200,
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            )
        elif self.path == "/v1/videos":
            self._send(200, {"id": "job-1", "status": "queued"})
        else:
            self._send(404, {"error": "not found"})


@contextmanager
def mock_server(*, cors_enabled: bool = True):
    MockHandler.cors_enabled = cors_enabled
    MockHandler.last_json = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def config(base_url: str, **overrides) -> Config:
    values = {
        "base_url": base_url,
        "api_key": API_KEY,
        "admin_api_key": ADMIN_KEY,
        "admin_path": "/admin/status",
        "timeout": 1,
        "poll_interval": 0.001,
    }
    values.update(overrides)
    return Config(**values)


def test_all_non_inference_checks_pass():
    with mock_server() as base_url:
        report = SmokeRunner(config(base_url)).run()

    assert report["summary"] == {"passed": 8, "failed": 0, "skipped": 1}
    assert report_exit_code(report) == 0
    assert report["configuration"]["api_key_configured"] is True
    assert report["configuration"]["admin_api_key_configured"] is True


def test_text_inference_uses_discovered_model():
    with mock_server() as base_url:
        report = SmokeRunner(config(base_url, inference="text")).run()

    assert report["summary"] == {"passed": 9, "failed": 0, "skipped": 0}
    assert MockHandler.last_json["model"] == "test-model"
    assert MockHandler.last_json["temperature"] == 0


def test_admin_post_probe_uses_empty_json():
    with mock_server() as base_url:
        report = SmokeRunner(
            config(
                base_url,
                admin_path="/admin/checksum",
                admin_method="POST",
            )
        ).run()

    admin = [check for check in report["checks"] if check["name"].startswith("admin")]
    assert all(check["status"] == "passed" for check in admin)
    assert admin[-1]["status_code"] == 400
    assert MockHandler.last_json == {}


def test_multimodal_inference_requires_and_sends_image_url():
    image_url = "https://example.invalid/test.png"
    with mock_server() as base_url:
        report = SmokeRunner(
            config(base_url, inference="multimodal", image_url=image_url)
        ).run()

    assert report["summary"]["failed"] == 0
    content = MockHandler.last_json["messages"][0]["content"]
    assert content[1] == {"type": "image_url", "image_url": {"url": image_url}}


def test_minimax_h3_submits_and_polls_until_complete():
    with mock_server() as base_url:
        report = SmokeRunner(
            config(
                base_url,
                inference="minimax-h3",
                model="MiniMaxAI/MiniMax-H3",
                inference_timeout=1,
            )
        ).run()

    inference = next(
        check for check in report["checks"] if check["name"] == "inference"
    )
    assert inference["status"] == "passed"
    assert MockHandler.last_json["task"] == "t2va"
    assert MockHandler.last_json["target"]["duration_seconds"] == 4.0


def test_cors_failure_sets_exit_code_one():
    with mock_server(cors_enabled=False) as base_url:
        report = SmokeRunner(config(base_url)).run()

    cors = next(
        check for check in report["checks"] if check["name"] == "cors.preflight"
    )
    assert cors["status"] == "failed"
    assert report_exit_code(report) == 1


def test_keys_are_redacted_and_absent_from_report():
    redactor = Redactor(API_KEY, ADMIN_KEY)
    assert redactor.redact(f"{API_KEY}:{ADMIN_KEY}") == "[REDACTED]:[REDACTED]"

    with mock_server() as base_url:
        report = SmokeRunner(config(base_url)).run()

    serialized = json.dumps(report)
    assert API_KEY not in serialized
    assert ADMIN_KEY not in serialized


def test_open_server_without_keys_treats_auth_checks_as_open():
    class OpenHandler(MockHandler):
        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            elif self.path == "/v1/models":
                self._send(200, {"data": [{"id": "open-model"}]})
            else:
                self._send(404, {"error": "not found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), OpenHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        report = SmokeRunner(Config(base_url=base_url, timeout=1)).run()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert report["summary"] == {"passed": 4, "failed": 0, "skipped": 5}


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"base_url": "localhost:8000"}, "absolute http"),
        (
            {"base_url": "http://localhost:8000", "admin_api_key": ADMIN_KEY},
            "must be set together",
        ),
        (
            {
                "base_url": "http://localhost:8000",
                "admin_api_key": ADMIN_KEY,
                "admin_path": "/admin/status?token=unsafe",
            },
            "without a query",
        ),
        (
            {"base_url": "http://localhost:8000", "admin_method": "DELETE"},
            "must be GET or POST",
        ),
        (
            {"base_url": "http://localhost:8000", "inference": "multimodal"},
            "--image-url",
        ),
    ],
)
def test_invalid_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        SmokeRunner(Config(**kwargs))


def test_cli_writes_json_report(tmp_path):
    report_path = tmp_path / "report.json"
    with mock_server() as base_url:
        exit_code = main(
            ["--base-url", base_url, "--report", str(report_path), "--quiet"],
            environ={
                "MODEL_SERVING_API_KEY": API_KEY,
                "MODEL_SERVING_ADMIN_API_KEY": ADMIN_KEY,
                "MODEL_SERVING_ADMIN_PATH": "/admin/status",
            },
        )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["summary"]["failed"] == 0
    assert API_KEY not in report_path.read_text(encoding="utf-8")
    assert ADMIN_KEY not in report_path.read_text(encoding="utf-8")


def test_cli_returns_two_for_invalid_configuration(tmp_path):
    exit_code = main(
        ["--report", str(tmp_path / "unused.json"), "--quiet"],
        environ={"MODEL_SERVING_ADMIN_API_KEY": ADMIN_KEY},
    )
    assert exit_code == 2
