# llm_client.py
# 医院内网大模型网关的 OpenAI 兼容客户端（仅标准库，无需 openai 包）。
# 逻辑参照 icu-sepsis-intelligence 的 LlmClient.java：
#   - 兼容多种返回形态：message.content 字符串/分段数组、text、delta、Anthropic content[]、
#     output_text、外层多包一层 data、网关强制流式（text/event-stream）
#   - 思考模式（Qwen3 等混合思考模型）经 chat_template_kwargs.enable_thinking 下发
#   - "有思考、没正文"（思考耗尽 max_tokens）时自动关闭思考重试一次
#   - 网关不认识 chat_template_kwargs（HTTP 400）时自动去掉该参数重试一次
#   - 空闲长连接被网关断开时重试一次；连接失败不重试
#   - 正文缺失时 info 日志打印网关原始返回，便于定位
from __future__ import annotations

import json
import logging
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request

log = logging.getLogger("llm_client")


class LlmError(RuntimeError):
    """kind: config / timeout / unreachable / http_<code> / bad_response；detail 用于内部分支。"""

    def __init__(self, kind: str, message: str, detail: str = ""):
        super().__init__(message)
        self.kind = kind
        self.detail = detail


# ------------------------------------------------------------------ 配置
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name).lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name)) if _env(name) else default
    except ValueError:
        return default


def config() -> dict:
    """每次调用时读取环境变量（python-dotenv 可能晚于导入才加载）。"""
    base = _env("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    path = _env("LLM_CHAT_PATH", "/chat/completions")
    if path and not path.startswith("/"):
        path = "/" + path
    return {
        "base_url": base,
        "chat_path": path,
        "api_key": _env("LLM_API_KEY"),
        "model": _env("LLM_MODEL", "gpt-4o-mini"),
        "thinking": _env("LLM_THINKING", "off").lower(),
        # 推理类任务（脓毒性休克确认）单独设置：思考更准但更慢，需要更多 token 和更长超时
        "thinking_reasoning": _env("LLM_THINKING_REASONING", "on").lower(),
        "reasoning_max_tokens": _env_int("LLM_REASONING_MAX_TOKENS", 4000),
        "reasoning_timeout": _env_int("LLM_REASONING_TIMEOUT_S", 120),
        "min_max_tokens": _env_int("LLM_MAX_TOKENS", 0),
        "timeout": _env_int("LLM_TIMEOUT_S", 60),
        "json_mode": _env_bool("LLM_JSON_MODE", True),
        "tls_insecure": _env_bool("LLM_TLS_INSECURE", False),
        "tls_ca_file": _env("LLM_TLS_CA_FILE"),
    }


def thinking_flag(value: str | None):
    """on/true -> True；off/false -> False；default/空 -> None（不下发参数，用模型默认）。"""
    v = (value or "").strip().lower()
    if v in ("on", "true", "1"):
        return True
    if v in ("off", "false", "0"):
        return False
    return None


def describe_config() -> str:
    c = config()
    return (f"LLM config: base={c['base_url']} path={c['chat_path']} model={c['model']} "
            f"thinking(fast={c['thinking']}, reasoning={c['thinking_reasoning']}) json_mode={c['json_mode']} timeout={c['timeout']}s "
            f"key={'已配置' if c['api_key'] else '未配置'}")


# ------------------------------------------------------------------ 解析
def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def unwrap(res: dict) -> dict:
    """部分网关外面多包一层 {"code":0,"data":{...choices...}}。"""
    if isinstance(res, dict) and "choices" not in res and isinstance(res.get("data"), dict) \
            and "choices" in res["data"]:
        return res["data"]
    return res


def _first_choice(root: dict) -> dict:
    ch = root.get("choices") if isinstance(root, dict) else None
    if isinstance(ch, list) and ch and isinstance(ch[0], dict):
        return ch[0]
    return {}


def extract_content(root: dict) -> str | None:
    """OpenAI 兼容的几种正文形态；取不到返回 None（空字符串视为取到）。"""
    if not isinstance(root, dict):
        return None
    choice = _first_choice(root)
    msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [p.get("text") for p in c if isinstance(p, dict) and isinstance(p.get("text"), str)]
        if parts:
            return "".join(parts)
    if isinstance(choice.get("text"), str):
        return choice["text"]
    delta = choice.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return delta["content"]
    a = root.get("content")
    if isinstance(a, list) and a and isinstance(a[0], dict) and isinstance(a[0].get("text"), str):
        return "".join(p.get("text", "") for p in a if isinstance(p, dict) and p.get("type", "text") == "text")
    if isinstance(root.get("output_text"), str):
        return root["output_text"]
    return None


def from_sse(raw: str) -> dict | None:
    """网关强制流式时，把 data: 分片拼回一个普通响应。"""
    if "data:" not in raw:
        return None
    text, finish, model, any_piece = [], None, None, False
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        d = line[5:].strip()
        if not d or d == "[DONE]":
            continue
        try:
            n = json.loads(d)
        except ValueError:
            continue
        ch = _first_choice(n)
        piece = (ch.get("delta") or {}).get("content") if isinstance(ch.get("delta"), dict) else None
        if not isinstance(piece, str):
            piece = (ch.get("message") or {}).get("content") if isinstance(ch.get("message"), dict) else None
        if isinstance(piece, str):
            text.append(piece)
            any_piece = True
        if ch.get("finish_reason") is not None:
            finish = ch["finish_reason"]
        if n.get("model"):
            model = n["model"]
    if not any_piece:
        return None
    out = {"choices": [{"message": {"role": "assistant", "content": "".join(text)}}]}
    if model:
        out["model"] = model
    if finish:
        out["choices"][0]["finish_reason"] = finish
    return out


def strip_thinking(s: str | None) -> str:
    """推理模型可能把思考过程内联在 <think>…</think> 里；不展示、不解析。"""
    if not s:
        return ""
    out = re.sub(r"(?s)<think>.*?</think>", "", s)
    i = out.find("<think>")
    if i >= 0:
        out = out[:i]
    return out.strip()


def parse_response(res: dict, model: str = "") -> dict:
    """返回 {content, model, finish_reason, usage}；无正文时抛 LlmError。"""
    root = unwrap(res)
    choice = _first_choice(root)
    text = extract_content(root)
    finish = choice.get("finish_reason") or ""
    if text is None or (not strip_thinking(text) and finish == "length"):
        msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        thought = bool(msg.get("reasoning_content") or msg.get("reasoning"))
        log.info("AI chat response without content (model=%s, finish=%s): %s",
                 model, finish, _clip(json.dumps(res, ensure_ascii=False), 800))
        if thought and finish in ("length", ""):
            raise LlmError("bad_response",
                           "模型思考过程耗尽 max_tokens 未输出正文；可调大 LLM_MAX_TOKENS 或设 LLM_THINKING=off",
                           detail="thinking_exhausted")
        raise LlmError("bad_response", "模型返回缺少 content" + (f"（finish_reason={finish}）" if finish else ""))
    return {
        "content": strip_thinking(text),
        "model": root.get("model") or model,
        "finish_reason": finish or None,
        "usage": root.get("usage") if isinstance(root.get("usage"), dict) else {},
    }


# ------------------------------------------------------------------ HTTP
import http.client as _hc

_STALE_ERRORS = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                 _hc.RemoteDisconnected, _hc.BadStatusLine, _hc.IncompleteRead)


def _ssl_context(c: dict):
    if c["tls_ca_file"]:
        return ssl.create_default_context(cafile=c["tls_ca_file"])
    if c["tls_insecure"]:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def _post(c: dict, body: dict, timeout: float) -> dict:
    url = c["base_url"] + c["chat_path"]
    if not url.startswith(("http://", "https://")):
        raise LlmError("config", "AI 服务地址无效")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if c["api_key"]:
        headers["Authorization"] = "Bearer " + c["api_key"]
    ctx = _ssl_context(c)
    for attempt in range(2):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            log.info("AI gateway HTTP %s: %s", e.code, _clip(err_body, 400))
            raise LlmError(f"http_{e.code}", f"AI 服务返回 HTTP {e.code}", detail=err_body)
        except (TimeoutError, socket.timeout, ssl.SSLError) as e:
            if isinstance(e, (TimeoutError, socket.timeout)) or "timed out" in str(e):
                raise LlmError("timeout", "AI 服务响应超时")
            raise LlmError("unreachable", f"AI 服务 TLS 失败：{_clip(str(e), 120)}")
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason):
                raise LlmError("timeout", "AI 服务响应超时")
            # 网关关掉的空闲长连接重试一次；连接被拒绝/地址不可达不重试
            if attempt == 0 and isinstance(reason, _STALE_ERRORS):
                continue
            raise LlmError("unreachable", f"AI 服务不可达：{type(reason).__name__} {_clip(str(reason), 120)}")
        except _STALE_ERRORS as e:
            if attempt == 0:
                continue
            raise LlmError("unreachable", f"AI 服务不可达：{type(e).__name__}")
    try:
        return json.loads(raw)
    except ValueError:
        sse = from_sse(raw)
        if sse is not None:
            return sse
        log.info("AI gateway returned non-JSON: %s", _clip(raw, 400))
        raise LlmError("bad_response", "AI 服务返回非 JSON：" + _clip(re.sub(r"\s+", " ", raw), 80))


# ------------------------------------------------------------------ 对外
def chat(messages: list, *, max_tokens: int = 400, temperature: float = 0.2,
         json_mode: bool = False, thinking: str | None = None, model: str | None = None,
         timeout: float | None = None, role: str = "fast") -> str:
    """发起一次对话，返回正文（已去掉 <think>）。失败抛 LlmError。

    role: fast（默认，用 LLM_THINKING）/ reasoning（用 LLM_THINKING_REASONING，
          并把 max_tokens、超时提高到 LLM_REASONING_MAX_TOKENS / LLM_REASONING_TIMEOUT_S）。
    thinking: on / off / default；显式传入时覆盖 role 的配置。
    """
    c = config()
    model = model or c["model"]
    if not model:
        raise LlmError("config", "未配置 LLM_MODEL")
    reasoning = role == "reasoning"
    default_thinking = c["thinking_reasoning"] if reasoning else c["thinking"]
    flag = thinking_flag(default_thinking if thinking is None else thinking)
    tokens = max(1, int(max_tokens), c["min_max_tokens"])
    if reasoning and flag is not False:
        tokens = max(tokens, c["reasoning_max_tokens"])
    json_mode = json_mode and c["json_mode"]
    timeout = float(timeout or (max(c["timeout"], c["reasoning_timeout"]) if reasoning else c["timeout"]))

    def send(flag_, send_kwargs=True):
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": tokens, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if flag_ is not None and send_kwargs:
            body["chat_template_kwargs"] = {"enable_thinking": bool(flag_)}
        t0 = time.time()
        res = _post(c, body, timeout)
        out = parse_response(res, model)
        log.debug("AI chat ok model=%s %.0fms finish=%s", out["model"], (time.time() - t0) * 1000,
                  out["finish_reason"])
        return out["content"]

    try:
        return send(flag)
    except LlmError as e:
        if e.detail == "thinking_exhausted" and flag is not False:
            log.info("AI 思考耗尽 max_tokens，关闭思考重试一次")
            return send(False)
        if e.kind == "http_400" and flag is not None:
            log.info("网关返回 400，去掉 chat_template_kwargs 重试一次")
            return send(flag, send_kwargs=False)
        raise
