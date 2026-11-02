"""llm_client 解析与重试测试（参照 icu-sepsis-intelligence LlmClientParseTest）。"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm_client as lc  # noqa: E402

# 医院网关（vLLM 0.29 + Qwen3）真实报文，去掉了与解析无关的字段
REAL_VLLM = {
    "id": "chatcmpl-b68db5c59fc03894", "object": "chat.completion", "model": "Qwen3.8-Next",
    "choices": [{"index": 0, "message": {
        "role": "assistant", "content": "\n\n你好！很高兴见到你 😊\n有什么我可以帮你的吗？",
        "refusal": None, "annotations": None, "audio": None, "function_call": None,
        "reasoning": "用户用中文打招呼\"你好\"。需要简短友好回应，并询问如何帮助。无需复杂分析。\n"},
        "logprobs": None, "finish_reason": "stop", "stop_reason": None}],
    "usage": {"prompt_tokens": 53, "total_tokens": 92, "completion_tokens": 39,
              "completion_tokens_details": {"reasoning_tokens": 22}},
}


def test_real_vllm_payload():
    out = lc.parse_response(REAL_VLLM)
    assert out["content"].startswith("你好！很高兴见到你")
    assert out["finish_reason"] == "stop"


@pytest.mark.parametrize("res,expected", [
    ({"choices": [{"message": {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]}, "ab"),
    ({"choices": [{"text": "legacy"}]}, "legacy"),
    ({"choices": [{"delta": {"content": "d"}}]}, "d"),
    ({"content": [{"type": "text", "text": "anthropic"}]}, "anthropic"),
    ({"output_text": "resp"}, "resp"),
    ({"code": 0, "data": {"choices": [{"message": {"content": "wrapped"}}]}}, "wrapped"),
    ({"choices": [{"message": {"content": "<think>xx</think>{\"a\":1}"}}]}, "{\"a\":1}"),
])
def test_formats(res, expected):
    assert lc.parse_response(res)["content"] == expected


def test_sse():
    raw = ('data: {"model":"m","choices":[{"delta":{"content":"你"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"好"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n')
    out = lc.parse_response(lc.from_sse(raw))
    assert out["content"] == "你好" and out["finish_reason"] == "stop"


def test_thinking_exhausted_detected():
    res = {"choices": [{"message": {"content": None, "reasoning": "想了很久"}, "finish_reason": "length"}]}
    with pytest.raises(lc.LlmError) as e:
        lc.parse_response(res)
    assert e.value.detail == "thinking_exhausted"


def test_missing_content_plain():
    with pytest.raises(lc.LlmError) as e:
        lc.parse_response({"choices": [{"message": {}, "finish_reason": "stop"}]})
    assert e.value.kind == "bad_response" and e.value.detail == ""


# ---------------- 本地假网关：验证真实 HTTP 往返与重试 ----------------
class _Gateway(BaseHTTPRequestHandler):
    mode = "ok"
    bodies = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Gateway.bodies.append({"body": body, "auth": self.headers.get("Authorization")})
        kw = body.get("chat_template_kwargs")
        if _Gateway.mode == "reject_kwargs" and kw is not None:
            return self._send(400, {"error": "unknown field chat_template_kwargs"})
        if _Gateway.mode == "think_exhaust" and (kw is None or kw.get("enable_thinking")):
            return self._send(200, {"choices": [{"message": {"content": None, "reasoning": "..."},
                                                 "finish_reason": "length"}]})
        self._send(200, REAL_VLLM)

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def gateway(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Gateway)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{srv.server_port}/llm/qwen")
    monkeypatch.setenv("LLM_CHAT_PATH", "/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "Qwen3.8-Next")
    monkeypatch.delenv("LLM_THINKING", raising=False)
    _Gateway.bodies = []
    yield _Gateway
    srv.shutdown()


def test_http_default_thinking_off(gateway):
    gateway.mode = "ok"
    assert lc.chat([{"role": "user", "content": "你好"}]).startswith("你好")
    b = gateway.bodies[0]
    assert b["auth"] == "Bearer test-key"
    assert b["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["body"]["stream"] is False


def test_http_thinking_exhausted_retries_without_thinking(gateway, monkeypatch):
    monkeypatch.setenv("LLM_THINKING", "on")
    gateway.mode = "think_exhaust"
    assert lc.chat([{"role": "user", "content": "x"}]).startswith("你好")
    assert [b["body"]["chat_template_kwargs"]["enable_thinking"] for b in gateway.bodies] == [True, False]


def test_http_default_mode_sends_no_kwargs(gateway, monkeypatch):
    monkeypatch.setenv("LLM_THINKING", "default")
    gateway.mode = "ok"
    lc.chat([{"role": "user", "content": "x"}])
    assert "chat_template_kwargs" not in gateway.bodies[0]["body"]


def test_http_400_retries_without_kwargs(gateway):
    gateway.mode = "reject_kwargs"
    assert lc.chat([{"role": "user", "content": "x"}]).startswith("你好")
    assert len(gateway.bodies) == 2 and "chat_template_kwargs" not in gateway.bodies[1]["body"]


def test_ai_analyzer_json_path(gateway, monkeypatch):
    import ai_analyzer
    monkeypatch.setattr(lc, "parse_response", lambda res, model="": {
        "content": '```json\n{"risk":"low"}\n```', "model": model, "finish_reason": "stop", "usage": {}})
    gateway.mode = "ok"
    assert ai_analyzer.call_llm_json_with_system("sys", "p") == {"risk": "low"}
    assert gateway.bodies[0]["body"]["response_format"] == {"type": "json_object"}


def test_unreachable():
    os.environ["LLM_BASE_URL"] = "http://127.0.0.1:1"
    try:
        with pytest.raises(lc.LlmError) as e:
            lc.chat([{"role": "user", "content": "x"}], timeout=3)
        assert e.value.kind == "unreachable"
    finally:
        del os.environ["LLM_BASE_URL"]


def test_reasoning_role_thinking_on_and_more_tokens(gateway):
    gateway.mode = "ok"
    lc.chat([{"role": "user", "content": "x"}], max_tokens=1200, role="reasoning")
    b = gateway.bodies[0]["body"]
    assert b["chat_template_kwargs"] == {"enable_thinking": True}
    assert b["max_tokens"] == 4000


def test_reasoning_role_can_be_turned_off(gateway, monkeypatch):
    monkeypatch.setenv("LLM_THINKING_REASONING", "off")
    gateway.mode = "ok"
    lc.chat([{"role": "user", "content": "x"}], max_tokens=1200, role="reasoning")
    b = gateway.bodies[0]["body"]
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    assert b["max_tokens"] == 1200
