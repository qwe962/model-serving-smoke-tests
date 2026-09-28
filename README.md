# model-serving-smoke-tests

[English](README.md) | [简体中文](README.zh-CN.md)

Check a running model service after deployment or an image upgrade. Verify HTTP
health, model discovery, API-key behavior, and optional inference; save the results
as JSON for deployment scripts and handoffs.

**After setup, one command runs the checks.** The service must already be running,
and its credentials must be loaded into your environment.

## 1. Prepare once

Requires Python 3.10+ and a reachable model service. The client uses the Python
standard library and runs on a CPU machine.

Linux / Bash:

```bash
git clone https://github.com/qwe962/model-serving-smoke-tests.git
cd model-serving-smoke-tests
```

An existing checkout is ready to use from its project directory.

For a service with API-key authentication, enter the service's existing normal key
in each new shell session:

```bash
read -r -s -p "Normal API key: " MODEL_SERVING_API_KEY
printf '\n'
export MODEL_SERVING_API_KEY
```

For an open service, leave `MODEL_SERVING_API_KEY` unset. For a reused shell, see
[authentication setup](docs/usage.md#authentication--鉴权配置).

## 2. Run the checks

From the project directory, replace the address with your running service:

```bash
PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:8000 --report smoke-report.json
```

This checks `/health`, `/v1/models`, and CORS. With a normal key configured, it
expects missing/wrong keys to receive 401/403 and the configured key to succeed.
Real inference and Admin probes are optional.

To include one real inference request, choose the matching command:

| Service | Command from the project directory |
| --- | --- |
| Text / chat | `PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:8000 --inference text --report text-report.json` |
| MiniMax-H3 on SGLang | `PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:30011 --inference minimax-h3 --inference-timeout 7200 --report h20-report.json` |

Text inference uses the first model returned by `/v1/models`; `--model` overrides
it. MiniMax-H3 submits a four-second T2VA job and polls until `completed`. Real
inference consumes server resources; H3 generation can take a long time.

## 3. Read the result

Example summary for an open service with inference and Admin probes disabled:

```text
Summary: 4 passed, 0 failed, 5 skipped
Report: smoke-report.json
```

This is illustrative output. Your run reports each check's status, HTTP code, and
duration. `SKIPPED` means an optional check was disabled. Reports are written in the
current directory; a custom report directory must already exist.

| Exit code | Meaning |
| --- | --- |
| `0` | Every enabled check passed. Optional checks may be skipped. |
| `1` | At least one enabled check failed. Inspect that check's message. |
| `2` | Configuration error or report-writing failure. |

If the correct key gets 401/403, check the service address and loaded credential.
If an anonymous request succeeds while a key is configured, check the server's
authentication settings. See [failure diagnosis](docs/usage.md#diagnosis--结果排查).

## Scope and more options

Designed for SGLang, vLLM, and services exposing the tested HTTP endpoints.
Compatibility depends on the deployed routes, authentication policy, and CORS
configuration. A service exposing only part of the OpenAI API may fail the health
or CORS checks.

Coverage is HTTP deployment acceptance. MiniMax-H3 success means job completion;
media-file inspection is a separate acceptance step. Checks run against your
existing server configuration and source version.

[Usage guide](docs/usage.md): Windows, installed CLI, Admin keys, multimodal input,
Docker, report handling, and development.

Keys are supplied through environment variables. Configured keys are redacted from
diagnostics. Keep real keys in your runtime environment or secret manager; review
reports before sharing them.

## License

[MIT](LICENSE)
