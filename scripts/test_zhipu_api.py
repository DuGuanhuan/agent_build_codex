#!/usr/bin/env python3
"""Test whether a Zhipu/BigModel API key can call chat completions."""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.7-flash"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Send one small request to Zhipu AI and report whether the API key works.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY"),
        help="API key. Defaults to ZAI_API_KEY or ZHIPU_API_KEY.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("ZHIPU_BASE_URL") or os.getenv("ZAI_BASE_URL") or DEFAULT_BASE_URL,
        help=f"OpenAI-compatible base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("ZHIPU_MODEL") or os.getenv("ZAI_MODEL") or DEFAULT_MODEL,
        help=f"Model to test. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("ZHIPU_TIMEOUT", "30")),
        help="Request timeout in seconds. Default: 30",
    )
    parser.add_argument(
        "--prompt",
        default="请只回复：智谱 API 可用",
        help="Prompt used for the connectivity test.",
    )
    parser.add_argument(
        "--thinking",
        choices=("disabled", "enabled", "none"),
        default=os.getenv("ZHIPU_THINKING", "disabled"),
        help="Zhipu thinking mode. Default: disabled",
    )
    return parser


def request_chat_completion(api_key, base_url, model, prompt, timeout, thinking):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 64,
        "stream": False,
    }
    if thinking != "none":
        payload["thinking"] = {"type": thinking}

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started_at = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        body = response.read().decode("utf-8")
        return response.status, elapsed_ms, json.loads(body)


def print_success(status, elapsed_ms, data):
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = data.get("usage") or {}

    print("OK: Zhipu API key is usable.")
    print(f"HTTP status: {status}")
    print(f"Latency: {elapsed_ms} ms")
    print(f"Model: {data.get('model', '-')}")
    print(f"Request ID: {data.get('request_id') or data.get('id') or '-'}")
    print(f"Reply: {message.get('content', '').strip() or '-'}")
    if usage:
        print("Usage: " + json.dumps(usage, ensure_ascii=False))


def print_http_error(error):
    body = error.read().decode("utf-8", errors="replace")
    print(f"FAILED: Zhipu API returned HTTP {error.code}.", file=sys.stderr)
    print(body, file=sys.stderr)


def main():
    args = build_parser().parse_args()
    if not args.api_key:
        print(
            "FAILED: missing API key. Set ZAI_API_KEY or ZHIPU_API_KEY, "
            "or pass --api-key.",
            file=sys.stderr,
        )
        return 2

    try:
        status, elapsed_ms, data = request_chat_completion(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            prompt=args.prompt,
            timeout=args.timeout,
            thinking=args.thinking,
        )
    except urllib.error.HTTPError as error:
        print_http_error(error)
        return 1
    except urllib.error.URLError as error:
        print(f"FAILED: request error: {error.reason}", file=sys.stderr)
        return 1
    except (TimeoutError, socket.timeout):
        print("FAILED: request timed out.", file=sys.stderr)
        return 1
    except json.JSONDecodeError as error:
        print(f"FAILED: response was not valid JSON: {error}", file=sys.stderr)
        return 1

    print_success(status, elapsed_ms, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
