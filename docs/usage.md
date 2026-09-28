# Usage guide / 使用手册

[English README](../README.md) | [中文 README](../README.zh-CN.md)

The README contains the default source-checkout workflow. Choose a section below
when you need another launch method or an optional check.

README 提供默认的源码运行流程，以下章节按使用场景补充配置。

## Authentication / 鉴权配置

The client reads keys from environment variables. It uses the normal key to select
the expected `/v1/models` behavior:

客户端从环境变量读取密钥，并据此确定 `/v1/models` 的预期行为：

| Variable / 变量 | Meaning / 含义 |
| --- | --- |
| `MODEL_SERVING_API_KEY` unset / 未设置 | Open mode: anonymous and wrong-key requests should succeed. 开放模式：无 Key 和错误 Key 请求均应成功。 |
| `MODEL_SERVING_API_KEY` set / 已设置 | Auth mode: anonymous and wrong-key requests should return 401/403; the configured key should succeed. 鉴权模式：无／错误 Key 应返回 401/403，配置的 Key 应成功。 |
| `MODEL_SERVING_ADMIN_API_KEY` + `MODEL_SERVING_ADMIN_PATH` | Enable the Admin probe together. 两项同时设置以启用 Admin 探测。 |
| `MODEL_SERVING_ADMIN_METHOD` | `GET` by default; also supports `POST`. 默认 GET，也支持 POST。 |

Use the server's existing credentials. Hidden input keeps values out of the typed
command; environment variables remain accessible to processes with sufficient host
privileges. Load `.env` through your own shell or secret manager. The CLI reads the
resulting environment.

使用服务端已有凭证。隐藏输入可避免密钥进入输入的命令文本，拥有足够宿主机权限的
进程仍可读取环境变量。`.env` 由 Shell 或密钥管理器加载，CLI 读取加载后的环境变量。

To select open mode in a reused Bash session, clear all authentication settings:

在复用的 Bash 会话中测试开放服务时，清理全部鉴权配置：

```bash
unset MODEL_SERVING_API_KEY MODEL_SERVING_ADMIN_API_KEY \
  MODEL_SERVING_ADMIN_PATH MODEL_SERVING_ADMIN_METHOD
```

## Admin probes / 管理员权限探测

Use distinct normal and Admin keys to test privilege separation. Select a route
whose documented behavior is safe under every tested credential. `POST` probes
send `{}`. Confirm that this empty body leaves server state unchanged.

使用两个不同的普通／Admin Key 验证权限隔离。根据实际部署选择安全的管理路由，
确认该路由在每一种测试凭证下的行为。POST 固定发送 `{}`，需确认空请求保持服务状态。

Example for a deployment exposing a read-only, Admin-protected
`GET /hicache/storage-backend`. Load the normal key using the README first.

以下示例适用于提供只读、Admin 鉴权的 `GET /hicache/storage-backend` 的部署。
普通 Key 按 README 提前加载。

```bash
read -r -s -p "Admin API key: " MODEL_SERVING_ADMIN_API_KEY
printf '\n'
export MODEL_SERVING_ADMIN_API_KEY
export MODEL_SERVING_ADMIN_PATH='/hicache/storage-backend'
export MODEL_SERVING_ADMIN_METHOD='GET'
PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:30000 --report smoke-report.json
```

Expected: anonymous and normal-key requests receive 401/403; the Admin-key request
reaches the route. The Admin check accepts responses below 500 except 401, 403, 404,
and 405. Interpret a 400/422 with the route's validation rules: it can show that a
request reached validation. Business-operation success requires separate evidence.

预期：匿名与普通 Key 请求返回 401/403，Admin Key 请求到达路由。Admin 检查接受
500 以下且排除 401、403、404、405 的响应。400/422 需结合路由参数校验规则解释，
它可能说明请求已进入校验阶段。管理操作成功需要独立的业务结果佐证。

## Other inference profiles / 其他推理配置

The README includes text and MiniMax-H3 commands. Image-and-text chat also requires
an image URL reachable by the model server. Replace the example URL with your image.

README 包含文本和 MiniMax-H3 命令。图文对话还需提供模型服务端可访问的图片 URL；
将示例地址替换为你自己的图片地址。

```bash
PYTHONPATH=src python3 -m model_serving_smoke_tests \
  --base-url http://127.0.0.1:8000 \
  --inference multimodal \
  --image-url https://YOUR-IMAGE-HOST/test.png \
  --inference-timeout 300 \
  --report multimodal-report.json
```

`--model` selects an explicit served model ID. `--timeout` controls individual HTTP
requests; `--inference-timeout` controls chat requests or the H3 job polling budget.
The H3 polling interval defaults to two seconds and can be set with `--poll-interval`.
GPU requirements belong to the deployed model server. Coverage is limited to HTTP;
WebSocket behavior and generated-media integrity require separate checks.

`--model` 显式指定服务端模型 ID。`--timeout` 控制单次 HTTP 请求超时；
`--inference-timeout` 控制聊天请求或 H3 任务轮询时限。H3 默认每两秒轮询一次，
可通过 `--poll-interval` 调整。GPU 需求由模型服务决定。测试覆盖 HTTP；
WebSocket 行为与生成媒体完整性需要单独验证。

## Windows / PowerShell

From a checkout with Python 3.10+ available / 在已有源码目录和 Python 3.10+ 环境中：

```powershell
$env:PYTHONPATH = 'src'
python -m model_serving_smoke_tests --base-url http://127.0.0.1:8000 --report smoke-report.json
```

For authentication, load the key before that command / 启用鉴权时，先加载密钥：

```powershell
$secret = Read-Host 'Normal API key' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
  $env:MODEL_SERVING_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}
```

## Installed CLI / 安装 CLI

For regular use, install from the checkout into a virtual environment. This provides
the `model-serving-smoke-tests` command; the same options apply.

长期使用可在虚拟环境中安装项目，获得 `model-serving-smoke-tests` 命令，参数保持一致。

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
model-serving-smoke-tests --base-url http://127.0.0.1:8000 --report smoke-report.json
```

## Docker

Build from the project directory. On Linux, this example connects to a service on
the host and writes reports using the current user's permissions. It passes existing
environment variables by name. Building requires access to the base image and build
dependencies; the source-checkout workflow is suitable for offline clients.

在项目目录构建。Linux 示例连接宿主机服务，以当前用户权限写入报告，并按变量名传递
已有环境变量。构建需要基础镜像与构建依赖；离线客户端可使用 README 的源码运行方式。

```bash
docker build -t model-serving-smoke-tests:local .
mkdir -p reports
docker run --rm --network host \
  --user "$(id -u):$(id -g)" \
  -e MODEL_SERVING_API_KEY \
  -e MODEL_SERVING_ADMIN_API_KEY \
  -e MODEL_SERVING_ADMIN_PATH \
  -e MODEL_SERVING_ADMIN_METHOD \
  -v "$PWD/reports:/reports" \
  model-serving-smoke-tests:local \
  --base-url http://127.0.0.1:8000 --report /reports/smoke-report.json
```

Docker Desktop: use `http://host.docker.internal:8000` as the address and remove
`--network host` / 使用该地址连接宿主机，并移除 `--network host`。

## Diagnosis / 结果排查

| Result / 结果 | Next check / 排查方向 |
| --- | --- |
| Connection refused / 连接被拒绝 | Verify the address, listener, and container port mapping. 核对地址、监听端口与容器端口映射。 |
| `health` or `models` gets 404 | Verify the endpoint paths in this deployment. 核对部署的接口路径。 |
| Correct key gets 401/403 | Verify the target service and configured key. 核对目标服务与配置密钥。 |
| Anonymous request succeeds in auth mode | Verify server-side authentication configuration. 核对服务端鉴权设置。 |
| `cors.preflight` fails | Check the OPTIONS status and allowed origin. 核对预检状态码与允许的 Origin。 |
| `inference` is skipped | Select a profile using `--inference`. 通过该参数选择推理类型。 |
| Report write fails | Check directory existence and write permission. 核对目录是否存在及写入权限。 |

Reports include configuration flags, model ID, check status, HTTP code, elapsed time,
and a short message. Review identifiers before sharing. Capture the exit code
immediately after the test: `$?` in Bash or `$LASTEXITCODE` in PowerShell. Reusing a
report filename overwrites its previous contents.

报告包含配置标记、模型 ID、检查状态、HTTP 状态码、耗时和简短说明。分享前检查环境标识。
测试结束后立即保存退出码：Bash 使用 `$?`，PowerShell 使用 `$LASTEXITCODE`。
重复使用同一报告文件名会覆盖上次结果。

## Development / 开发

From an activated virtual environment / 在已激活的虚拟环境中：

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
```

GitHub Actions runs these checks on Python 3.10, 3.11, and 3.12 with local mock
servers. Real-model E2E runs are opt-in; record the server revision, client revision,
runtime environment, and observed result when sharing deployment evidence.

GitHub Actions 在 Python 3.10、3.11、3.12 上使用本地模拟服务执行检查。
真实模型 E2E 按需运行；发布部署证据时记录服务端版本、客户端版本、运行环境和实际结果。
