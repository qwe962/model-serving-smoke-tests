from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from model_serving_smoke_tests import __version__
from model_serving_smoke_tests.core import (
    Config,
    Redactor,
    SmokeRunner,
    report_exit_code,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model-serving-smoke-tests",
        description=(
            "Run lightweight checks against SGLang, vLLM, or an "
            "OpenAI-compatible model server."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--base-url",
        help="server root URL (default: MODEL_SERVING_BASE_URL or http://127.0.0.1:8000)",
    )
    parser.add_argument("--model", help="served model name; defaults to /v1/models")
    parser.add_argument(
        "--inference",
        choices=("none", "text", "multimodal", "minimax-h3"),
        default="none",
        help="optional real inference profile (default: none)",
    )
    parser.add_argument("--image-url", help="image URL for multimodal inference")
    parser.add_argument(
        "--origin",
        default="https://smoke-tests.invalid",
        help="Origin header used for the CORS preflight",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--inference-timeout", type=float, default=1800.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--report", default="smoke-report.json")
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    api_key = env.get("MODEL_SERVING_API_KEY") or None
    admin_api_key = env.get("MODEL_SERVING_ADMIN_API_KEY") or None
    redactor = Redactor(api_key, admin_api_key)
    config = Config(
        base_url=args.base_url
        or env.get("MODEL_SERVING_BASE_URL", "http://127.0.0.1:8000"),
        api_key=api_key,
        admin_api_key=admin_api_key,
        admin_path=env.get("MODEL_SERVING_ADMIN_PATH") or None,
        model=args.model,
        inference=args.inference,
        image_url=args.image_url,
        origin=args.origin,
        timeout=args.timeout,
        inference_timeout=args.inference_timeout,
        poll_interval=args.poll_interval,
    )
    try:
        runner = SmokeRunner(config)
        report = runner.run()
        report_path = Path(args.report)
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as error:
        print(f"ERROR {redactor.redact(str(error))}", file=sys.stderr)
        return 2

    if not args.quiet:
        for check in report["checks"]:
            code = f" HTTP {check['status_code']}" if check["status_code"] else ""
            print(
                f"{check['status'].upper():7} {check['name']}{code} "
                f"({check['duration_ms']} ms) - {check['message']}"
            )
        summary = report["summary"]
        print(
            f"Summary: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['skipped']} skipped"
        )
        print(f"Report: {report_path}")
    return report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
