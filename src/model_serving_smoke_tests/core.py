from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

AUTH_FAILURE_CODES = {401, 403}
TERMINAL_FAILURE_STATES = {"cancelled", "canceled", "failed", "error"}


class RequestError(RuntimeError):
    """Raised when no HTTP response was received."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str | None = None
    admin_api_key: str | None = None
    admin_path: str | None = None
    admin_method: str = "GET"
    model: str | None = None
    inference: str = "none"
    image_url: str | None = None
    origin: str = "https://smoke-tests.invalid"
    timeout: float = 10.0
    inference_timeout: float = 1800.0
    poll_interval: float = 2.0

    def validate(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base URL must be an absolute http:// or https:// URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "base URL must not contain credentials, a query, or a fragment"
            )
        if bool(self.admin_api_key) != bool(self.admin_path):
            raise ValueError(
                "MODEL_SERVING_ADMIN_API_KEY and MODEL_SERVING_ADMIN_PATH "
                "must be set together"
            )
        if self.admin_path:
            admin_path = urlsplit(self.admin_path)
            if (
                not self.admin_path.startswith("/")
                or admin_path.scheme
                or admin_path.netloc
                or admin_path.query
                or admin_path.fragment
            ):
                raise ValueError(
                    "MODEL_SERVING_ADMIN_PATH must be a path starting with '/' "
                    "without a query or fragment"
                )
        if self.admin_method not in {"GET", "POST"}:
            raise ValueError("MODEL_SERVING_ADMIN_METHOD must be GET or POST")
        if self.inference not in {"none", "text", "multimodal", "minimax-h3"}:
            raise ValueError(f"unsupported inference profile: {self.inference}")
        if self.inference == "multimodal" and not self.image_url:
            raise ValueError("--image-url is required for multimodal inference")
        if self.timeout <= 0 or self.inference_timeout <= 0:
            raise ValueError("timeouts must be greater than zero")
        if self.poll_interval <= 0:
            raise ValueError("poll interval must be greater than zero")


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    duration_ms: int
    status_code: int | None = None
    message: str = ""


class Redactor:
    def __init__(self, *values: str | None):
        self._values = sorted(
            {value for value in values if value}, key=len, reverse=True
        )

    def redact(self, value: str) -> str:
        for secret in self._values:
            value = value.replace(secret, "[REDACTED]")
        return value


class HttpClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        key: str | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Response:
        request_headers = dict(headers or {})
        data = None
        if key:
            request_headers["Authorization"] = f"Bearer {key}"
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")
        url = urljoin(self.base_url, path.lstrip("/"))
        request = Request(url, data=data, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                return Response(
                    status=response.status,
                    headers={
                        key.lower(): value for key, value in response.headers.items()
                    },
                    body=response.read(),
                )
        except HTTPError as error:
            return Response(
                status=error.code,
                headers={key.lower(): value for key, value in error.headers.items()},
                body=error.read(),
            )
        except (OSError, URLError) as error:
            raise RequestError(str(error)) from error


class SmokeRunner:
    def __init__(self, config: Config):
        config.validate()
        self.config = config
        self.invalid_key = "smoke-test-invalid-" + secrets.token_hex(16)
        self.redactor = Redactor(config.api_key, config.admin_api_key, self.invalid_key)
        self.client = HttpClient(config.base_url, config.timeout)
        self.results: list[CheckResult] = []
        self.discovered_model: str | None = None

    def run(self) -> dict[str, Any]:
        self.results.append(self._health())
        self.results.append(self._models("models.no_key", None, self._normal_open()))
        self.results.append(
            self._models("models.wrong_key", self.invalid_key, self._normal_open())
        )
        if self.config.api_key:
            self.results.append(
                self._models("models.correct_key", self.config.api_key, True)
            )
        else:
            self.results.append(
                self._skip("models.correct_key", "API key is not configured")
            )
        self.results.append(self._cors())
        self.results.extend(self._admin_checks())
        self.results.append(self._inference())
        return self.report()

    def report(self) -> dict[str, Any]:
        counts = {
            name: sum(result.status == name for result in self.results)
            for name in ("passed", "failed", "skipped")
        }
        return {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "target": safe_target(self.config.base_url),
            "configuration": {
                "api_key_configured": bool(self.config.api_key),
                "admin_api_key_configured": bool(self.config.admin_api_key),
                "admin_path": self.config.admin_path,
                "admin_method": self.config.admin_method,
                "inference": self.config.inference,
                "model": self.config.model or self.discovered_model,
            },
            "summary": counts,
            "checks": [asdict(result) for result in self.results],
        }

    def _normal_open(self) -> bool:
        return not self.config.api_key

    def _health(self) -> CheckResult:
        return self._request_check(
            "health", "GET", "/health", key=None, expect_success=True
        )

    def _models(self, name: str, key: str | None, expect_success: bool) -> CheckResult:
        started = time.monotonic()
        try:
            response = self.client.request("GET", "/v1/models", key=key)
            if expect_success:
                if not 200 <= response.status < 300:
                    return self._result(
                        name,
                        False,
                        started,
                        response.status,
                        "expected a successful response",
                    )
                try:
                    payload = response.json()
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return self._result(
                        name,
                        False,
                        started,
                        response.status,
                        "response is not valid JSON",
                    )
                models = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(models, list) or not models:
                    return self._result(
                        name,
                        False,
                        started,
                        response.status,
                        "response does not contain a non-empty data list",
                    )
                model_id = models[0].get("id") if isinstance(models[0], dict) else None
                if not isinstance(model_id, str) or not model_id:
                    return self._result(
                        name,
                        False,
                        started,
                        response.status,
                        "first model does not contain a string id",
                    )
                self.discovered_model = model_id
                return self._result(
                    name, True, started, response.status, "model list is valid"
                )
            return self._result(
                name,
                response.status in AUTH_FAILURE_CODES,
                started,
                response.status,
                "request was rejected"
                if response.status in AUTH_FAILURE_CODES
                else ("expected HTTP 401 or 403"),
            )
        except RequestError as error:
            return self._transport_failure(name, started, error)

    def _cors(self) -> CheckResult:
        started = time.monotonic()
        try:
            response = self.client.request(
                "OPTIONS",
                "/v1/models",
                headers={
                    "Origin": self.config.origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization, Content-Type",
                },
            )
            allowed_origin = response.headers.get("access-control-allow-origin")
            passed = response.status in {200, 204} and allowed_origin in {
                "*",
                self.config.origin,
            }
            message = (
                "preflight accepted"
                if passed
                else "expected HTTP 200/204 and a matching access-control-allow-origin"
            )
            return self._result(
                "cors.preflight", passed, started, response.status, message
            )
        except RequestError as error:
            return self._transport_failure("cors.preflight", started, error)

    def _admin_checks(self) -> list[CheckResult]:
        if not self.config.admin_api_key or not self.config.admin_path:
            reason = "admin key and read-only admin path are not configured"
            return [
                self._skip("admin.no_key", reason),
                self._skip("admin.user_key", reason),
                self._skip("admin.correct_key", reason),
            ]
        checks = [
            self._request_check(
                "admin.no_key",
                self.config.admin_method,
                self.config.admin_path,
                key=None,
                json_body={} if self.config.admin_method == "POST" else None,
                expected_statuses=AUTH_FAILURE_CODES,
            )
        ]
        if self.config.api_key:
            checks.append(
                self._request_check(
                    "admin.user_key",
                    self.config.admin_method,
                    self.config.admin_path,
                    key=self.config.api_key,
                    json_body={} if self.config.admin_method == "POST" else None,
                    expected_statuses=AUTH_FAILURE_CODES,
                )
            )
        else:
            checks.append(self._skip("admin.user_key", "API key is not configured"))
        checks.append(
            self._request_check(
                "admin.correct_key",
                self.config.admin_method,
                self.config.admin_path,
                key=self.config.admin_api_key,
                json_body={} if self.config.admin_method == "POST" else None,
                expect_authenticated=True,
            )
        )
        return checks

    def _inference(self) -> CheckResult:
        if self.config.inference == "none":
            return self._skip("inference", "inference profile is disabled")
        if self.config.inference == "minimax-h3":
            return self._minimax_h3()
        model = self.config.model or self.discovered_model
        if not model:
            return self._fail_without_request("inference", "no model was selected")
        content: str | list[dict[str, Any]] = "Reply with exactly: smoke ok"
        if self.config.inference == "multimodal":
            content = [
                {"type": "text", "text": "Describe this image in one short sentence."},
                {"type": "image_url", "image_url": {"url": self.config.image_url}},
            ]
        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 32,
            "temperature": 0,
        }
        started = time.monotonic()
        try:
            response = self.client.request(
                "POST",
                "/v1/chat/completions",
                key=self.config.api_key,
                json_body=body,
                timeout=self.config.inference_timeout,
            )
            if not 200 <= response.status < 300:
                return self._result(
                    "inference",
                    False,
                    started,
                    response.status,
                    "expected a successful inference response",
                )
            try:
                payload = response.json()
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._result(
                    "inference", False, started, response.status, "response is not JSON"
                )
            choices = payload.get("choices") if isinstance(payload, dict) else None
            passed = isinstance(choices, list) and bool(choices)
            return self._result(
                "inference",
                passed,
                started,
                response.status,
                "inference returned choices"
                if passed
                else "response does not contain choices",
            )
        except RequestError as error:
            return self._transport_failure("inference", started, error)

    def _minimax_h3(self) -> CheckResult:
        model = self.config.model or self.discovered_model or "MiniMaxAI/MiniMax-H3"
        body = {
            "model": model,
            "prompt": (
                "A paper airplane glides across a quiet studio, "
                "with soft ambient sound."
            ),
            "seconds": 4,
            "task": "t2va",
            "conditions": [],
            "target": {
                "short_edge": 768,
                "aspect_ratio": "16:9",
                "duration_seconds": 4.0,
            },
            "num_outputs_per_prompt": 1,
            "num_inference_steps": 50,
            "flow_shift": 12.0,
            "audio_flow_shift": 3.0,
            "seed": 1101,
        }
        started = time.monotonic()
        try:
            response = self.client.request(
                "POST", "/v1/videos", key=self.config.api_key, json_body=body
            )
            if not 200 <= response.status < 300:
                return self._result(
                    "inference",
                    False,
                    started,
                    response.status,
                    "MiniMax-H3 job submission failed",
                )
            try:
                payload = response.json()
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._result(
                    "inference",
                    False,
                    started,
                    response.status,
                    "job submission response is not JSON",
                )
            job_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(job_id, str) or not job_id:
                return self._result(
                    "inference",
                    False,
                    started,
                    response.status,
                    "job submission response does not contain an id",
                )
            deadline = started + self.config.inference_timeout
            while time.monotonic() < deadline:
                status_response = self.client.request(
                    "GET", f"/v1/videos/{job_id}", key=self.config.api_key
                )
                if not 200 <= status_response.status < 300:
                    return self._result(
                        "inference",
                        False,
                        started,
                        status_response.status,
                        "job status request failed",
                    )
                try:
                    status_payload = status_response.json()
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return self._result(
                        "inference",
                        False,
                        started,
                        status_response.status,
                        "job status response is not JSON",
                    )
                state = (
                    status_payload.get("status")
                    if isinstance(status_payload, dict)
                    else None
                )
                if state == "completed":
                    return self._result(
                        "inference",
                        True,
                        started,
                        status_response.status,
                        "MiniMax-H3 job completed",
                    )
                if isinstance(state, str) and state in TERMINAL_FAILURE_STATES:
                    return self._result(
                        "inference",
                        False,
                        started,
                        status_response.status,
                        f"MiniMax-H3 job ended with status {state}",
                    )
                time.sleep(self.config.poll_interval)
            return self._result(
                "inference",
                False,
                started,
                None,
                "MiniMax-H3 job timed out",
            )
        except RequestError as error:
            return self._transport_failure("inference", started, error)

    def _request_check(
        self,
        name: str,
        method: str,
        path: str,
        *,
        key: str | None,
        json_body: dict[str, Any] | None = None,
        expect_success: bool = False,
        expect_authenticated: bool = False,
        expected_statuses: set[int] | None = None,
    ) -> CheckResult:
        started = time.monotonic()
        try:
            response = self.client.request(method, path, key=key, json_body=json_body)
            if expect_authenticated:
                passed = (
                    response.status < 500
                    and response.status not in AUTH_FAILURE_CODES
                    and response.status not in {404, 405}
                )
            elif expect_success:
                passed = 200 <= response.status < 300
            else:
                passed = response.status in (expected_statuses or set())
            if passed and expect_authenticated:
                message = "admin authentication was accepted"
            elif passed:
                message = (
                    "request succeeded" if expect_success else "request was rejected"
                )
            elif expect_authenticated:
                message = "admin authentication was rejected or route is unavailable"
            elif expect_success:
                message = "expected a successful response"
            else:
                expected = "/".join(
                    str(code) for code in sorted(expected_statuses or [])
                )
                message = f"expected HTTP {expected}"
            return self._result(name, passed, started, response.status, message)
        except RequestError as error:
            return self._transport_failure(name, started, error)

    def _transport_failure(
        self, name: str, started: float, error: Exception
    ) -> CheckResult:
        return self._result(
            name,
            False,
            started,
            None,
            "transport error: " + self.redactor.redact(str(error)),
        )

    def _result(
        self,
        name: str,
        passed: bool,
        started: float,
        status_code: int | None,
        message: str,
    ) -> CheckResult:
        return CheckResult(
            name=name,
            status="passed" if passed else "failed",
            duration_ms=round((time.monotonic() - started) * 1000),
            status_code=status_code,
            message=self.redactor.redact(message),
        )

    @staticmethod
    def _skip(name: str, message: str) -> CheckResult:
        return CheckResult(name=name, status="skipped", duration_ms=0, message=message)

    @staticmethod
    def _fail_without_request(name: str, message: str) -> CheckResult:
        return CheckResult(name=name, status="failed", duration_ms=0, message=message)


def safe_target(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def report_exit_code(report: dict[str, Any]) -> int:
    return 1 if report["summary"]["failed"] else 0
