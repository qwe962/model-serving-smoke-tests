# model-serving-smoke-tests

Small, dependency-free runtime checks for SGLang, vLLM, and other
OpenAI-compatible model servers.

The first release checks:

- `GET /health`
- `GET /v1/models` with no key, a generated wrong key, and the correct key
- an optional read-only admin endpoint with no key, the user key, and the admin key
- CORS `OPTIONS /v1/models`
- optional text, image-and-text, or MiniMax-H3 inference
- a JSON report and stable process exit codes

Real inference is off by default. The normal smoke test is lightweight and does not
require a GPU on the client machine.

## Requirements

- Python 3.10 or newer
- a reachable HTTP service
- NVIDIA GPUs only on the model-server side when the selected model requires them

The installed CLI has no third-party runtime dependencies.

## Install

```bash
git clone https://github.com/qwe962/model-serving-smoke-tests.git
cd model-serving-smoke-tests
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

PowerShell activation:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Quick start

An unauthenticated local server:

```bash
model-serving-smoke-tests \
  --base-url http://127.0.0.1:8000 \
  --report smoke-report.json
```

An authenticated server:

```bash
export MODEL_SERVING_API_KEY='replace-with-the-real-service-key'

model-serving-smoke-tests \
  --base-url http://127.0.0.1:8000 \
  --report smoke-report.json
```

`MODEL_SERVING_API_KEY` is intentionally not available as a command-line option.
This keeps keys out of shell history and process listings. The CLI does not read
`.env` files; load them with your shell or secret manager.

For PowerShell:

```powershell
$env:MODEL_SERVING_API_KEY = 'replace-with-the-real-service-key'
model-serving-smoke-tests --base-url http://127.0.0.1:8000 --report smoke-report.json
```

## SGLang admin-key check

SGLang supports a separate admin API key. vLLM does not expose the same unified
admin-key contract, so leave these variables unset for vLLM.

Set both variables and choose a read-only `GET` endpoint that is protected by the
admin key in the deployed SGLang version. Current SGLang LLM servers expose
`/hicache/storage-backend` as a read-only admin endpoint when HiCache is available:

```bash
export MODEL_SERVING_API_KEY='replace-with-the-user-key'
export MODEL_SERVING_ADMIN_API_KEY='replace-with-the-admin-key'
export MODEL_SERVING_ADMIN_PATH='/hicache/storage-backend'
export MODEL_SERVING_ADMIN_METHOD='GET'

model-serving-smoke-tests --base-url http://127.0.0.1:30000
```

The three expected results are anonymous denied, user key denied, and admin key
accepted. `MODEL_SERVING_ADMIN_METHOD` may be `GET` or `POST`; POST probes always send
an empty JSON object and cannot carry an operator-supplied management payload. Never
configure an endpoint where an empty object changes server state. Both admin key/path
variables are required together so a typo cannot silently skip the test.

For the MiniMax-H3 authentication branch, use its read-only tensor-checker route. The
probe sends `{}` deliberately: the admin key reaches request validation and returns
HTTP 400, while missing/user keys return 401 or 403. No weight operation is started:

```bash
export MODEL_SERVING_ADMIN_PATH='/update_weights_from_tensor_checker'
export MODEL_SERVING_ADMIN_METHOD='POST'

model-serving-smoke-tests \
  --base-url http://127.0.0.1:30010
```

SGLang's authentication behavior and vLLM's authentication scope can change between
versions. Check the deployed version against the
[SGLang server arguments](https://github.com/sgl-project/sglang/blob/main/docs_new/docs/advanced_features/server_arguments.mdx)
and [vLLM security documentation](https://github.com/vllm-project/vllm/blob/main/docs/usage/security.md).

## Optional inference

### Text

The model is discovered from the first `/v1/models` entry unless `--model` is set.

```bash
export MODEL_SERVING_API_KEY='replace-with-the-real-service-key'

model-serving-smoke-tests \
  --base-url http://127.0.0.1:8000 \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --inference text \
  --inference-timeout 120 \
  --report text-report.json
```

### Multimodal chat

The image URL must be reachable by the model server. Restrict allowed media domains
on internet-facing services.

```bash
export MODEL_SERVING_API_KEY='replace-with-the-real-service-key'

model-serving-smoke-tests \
  --base-url http://127.0.0.1:8000 \
  --model your-vision-model \
  --inference multimodal \
  --image-url https://example.com/test-image.png \
  --inference-timeout 300 \
  --report multimodal-report.json
```

### MiniMax-H3

The MiniMax-H3 profile submits a four-second T2VA job to `POST /v1/videos`, polls
`GET /v1/videos/{id}`, and passes only after the job reaches `completed`. It does not
download the generated MP4. This is a real, potentially long-running GPU test and is
never run by default or by unit-test CI.

```bash
export MODEL_SERVING_API_KEY='replace-with-the-real-service-key'

model-serving-smoke-tests \
  --base-url http://127.0.0.1:30010 \
  --model MiniMaxAI/MiniMax-H3 \
  --inference minimax-h3 \
  --inference-timeout 1800 \
  --poll-interval 2 \
  --report minimax-h3-report.json
```

The request follows SGLang's documented asynchronous
[MiniMax-H3 `/v1/videos` API](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/diffusion/MiniMax/MiniMax-H3.mdx).

## Docker

Build the client image:

```bash
docker build -t model-serving-smoke-tests:local .
```

Run it on a Linux host against a service bound on the host. `-e NAME` passes the
existing environment variable without putting its value in the Docker command:

```bash
mkdir -p reports
export MODEL_SERVING_API_KEY='replace-with-the-real-service-key'

docker run --rm --network host \
  -e MODEL_SERVING_API_KEY \
  -v "$PWD/reports:/reports" \
  model-serving-smoke-tests:local \
  --base-url http://127.0.0.1:8000 \
  --report /reports/smoke-report.json
```

On Docker Desktop, use `http://host.docker.internal:8000` and omit
`--network host`.

## Report and exit codes

The report contains status codes and short diagnostic messages, but never request
headers, response bodies, or key values.

```json
{
  "schema_version": 1,
  "target": "http://127.0.0.1:8000",
  "configuration": {
    "api_key_configured": true,
    "admin_api_key_configured": false,
    "admin_path": null,
    "admin_method": "GET",
    "inference": "none",
    "model": "served-model"
  },
  "summary": {"passed": 4, "failed": 0, "skipped": 5},
  "checks": []
}
```

| Exit code | Meaning |
| --- | --- |
| `0` | Every enabled check passed; skipped optional checks are allowed. |
| `1` | One or more enabled checks failed. |
| `2` | Invalid configuration or the JSON report could not be written. |

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
```

GitHub Actions runs the same checks on Python 3.10, 3.11, and 3.12. It uses the local
mock server only; no model, GPU, API key, or external service is required.

## Security

- Pass user and admin keys only through `MODEL_SERVING_API_KEY` and
  `MODEL_SERVING_ADMIN_API_KEY`.
- `.env`, reports, build outputs, and Python caches are ignored by Git.
- Generated wrong keys and configured keys are redacted from diagnostics.
- The JSON report records only whether a key was configured.
- Do not expose model servers directly to untrusted networks. Network controls are
  still required, especially for non-OpenAI management endpoints.

## License

MIT
