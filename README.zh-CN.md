# model-serving-smoke-tests

[English](README.md) | [简体中文](README.zh-CN.md)

模型服务部署或镜像升级后，检查 HTTP 健康状态、模型列表、API Key 和可选真实推理，
并生成 JSON 报告，用于部署验收、自动化脚本和交接。

**完成准备后，一条命令执行检查。** 前提是模型服务已经启动，所需密钥已经加载到环境变量。

## 1. 首次准备

需要 Python 3.10+，以及一个可以访问的模型服务。客户端使用 Python 标准库，普通 CPU 机器即可运行。

Linux / Bash：

```bash
git clone https://github.com/qwe962/model-serving-smoke-tests.git
cd model-serving-smoke-tests
```

已经下载项目的用户，进入项目目录即可。

服务启用了 API Key 时，在每个新 Shell 会话中输入服务端已经配置的普通 Key：

```bash
read -r -s -p "Normal API key: " MODEL_SERVING_API_KEY
printf '\n'
export MODEL_SERVING_API_KEY
```

开放服务请保持 `MODEL_SERVING_API_KEY` 未设置。复用 Shell 时的清理方法见
[鉴权配置](docs/usage.md#authentication--鉴权配置)。

## 2. 执行测试

在项目目录执行，地址替换为你的模型服务地址：

```bash
PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:8000 --report smoke-report.json
```

这条命令检查 `/health`、`/v1/models` 和 CORS。设置普通 Key 后，还会验证无 Key、
错误 Key 返回 401/403，以及配置的 Key 能成功访问。真实推理和 Admin 探测按需启用。

需要同时完成一次真实推理时，选择对应命令：

| 服务 | 在项目目录执行的命令 |
| --- | --- |
| 文本／聊天模型 | `PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:8000 --inference text --report text-report.json` |
| SGLang MiniMax-H3 | `PYTHONPATH=src python3 -m model_serving_smoke_tests --base-url http://127.0.0.1:30011 --inference minimax-h3 --inference-timeout 7200 --report h20-report.json` |

文本推理默认使用 `/v1/models` 返回的第一个模型，可通过 `--model` 指定。
MiniMax-H3 提交一个 4 秒 T2VA 任务，轮询至 `completed`。真实推理会占用服务端资源，
H3 生成可能耗时较长。

## 3. 查看结果

开放服务关闭推理和 Admin 探测时的汇总示例：

```text
Summary: 4 passed, 0 failed, 5 skipped
Report: smoke-report.json
```

以上为输出示意。实际运行会逐项显示状态、HTTP 状态码和耗时。
`SKIPPED` 表示该可选检查处于关闭状态。报告默认写入当前目录；
自定义报告目录需要提前创建。

| 退出码 | 含义 |
| --- | --- |
| `0` | 所有已启用检查通过，允许可选项跳过。 |
| `1` | 至少一项检查失败，查看对应检查的信息。 |
| `2` | 配置错误或报告写入失败。 |

正确 Key 返回 401/403 时，核对服务地址和环境变量中的密钥。
配置 Key 后匿名请求仍成功时，核对服务端鉴权设置。
更多说明见[结果排查](docs/usage.md#diagnosis--结果排查)。

## 适用范围与更多用法

面向 SGLang、vLLM 和提供上述 HTTP 接口的模型服务，实际兼容性取决于部署的路由、
鉴权策略及 CORS 配置。仅实现部分 OpenAI API 的服务，健康或 CORS 检查可能失败。

测试范围是 HTTP 部署验收。MiniMax-H3 通过表示任务完成，媒体文件检查可作为独立验收步骤。
工具直接测试已有服务的配置与源码版本。

[使用手册](docs/usage.md)：Windows、安装 CLI、Admin Key、多模态输入、Docker、
报告处理和开发检查。

密钥通过环境变量传入，诊断信息会脱敏配置的密钥。真实密钥保存在运行环境或密钥管理器中，
分享报告前请检查其内容。

## License

[MIT](LICENSE)
