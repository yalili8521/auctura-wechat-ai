"""Auctura AI — 微信公众号(测试号)AI 自动回复 webhook。

微信服务器把用户消息 POST 到 /wechat,这里调 Gemini 生成回复,
按微信被动回复 XML 格式在 5 秒内返回。
没配 GEMINI_API_KEY 时走"无 AI 回显模式",仍可跑通全链路。

运行:  .venv\\Scripts\\python.exe server.py
配置:  同目录 .env(WECHAT_TOKEN / GEMINI_API_KEY / GEMINI_MODEL / PORT)
"""
import hashlib
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv
from flask import Flask, make_response, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

WECHAT_TOKEN = os.getenv("WECHAT_TOKEN", "").strip()
if not WECHAT_TOKEN:
    sys.exit("WECHAT_TOKEN is not set: copy .env.example to .env and fill it in")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PORT = int(os.getenv("PORT", "8787"))

AI_TIMEOUT = 3.5       # 微信 5 秒断开;留出隧道往返余量
MAX_REPLY_CHARS = 750  # 被动回复上限 2048 字节,中文按 3 字节算留余量
DEDUPE_TTL = 300       # 微信超时会重试同一 MsgId,5 分钟内去重

SYSTEM_PROMPT = (
    "你是 Auctura AI 搭建的微信公众号智能客服 demo。"
    "用简体中文回答,友好、口语化,每次回复不超过 150 字。"
    "如果用户问你是谁:你是 Auctura AI 的 AI 自动回复演示,"
    "Auctura AI 帮商家搭建微信 AI 客服和自动化。"
)
WELCOME = "你好!我是 Auctura AI 的公众号 AI 客服 demo,直接发文字消息试试吧 🙂"
NON_TEXT = "我目前只能处理文字消息,发段文字试试~"
FALLBACK_ERROR = "AI 这会儿没回上话,请再发一次~"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BASE_DIR, "server.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("wechat-ai")

app = Flask(__name__)
_seen = {}  # MsgId -> (收到时间, 回复文本)


def check_signature(args):
    """微信签名校验:sha1(字典序排序的 [token, timestamp, nonce] 拼接)。"""
    raw = "".join(sorted([WECHAT_TOKEN, args.get("timestamp", ""), args.get("nonce", "")]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest() == args.get("signature", "")


def ask_ai(user_text):
    if not GEMINI_API_KEY:
        return f"✅ 链路已打通!(无 AI 回显模式:还没配 GEMINI_API_KEY)你说的是:{user_text[:100]}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {
            "maxOutputTokens": 1000,
            "temperature": 0.7,
            # 2.5 系列默认开 thinking,客服场景关掉以保证 5 秒内出话
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        r = requests.post(url, json=payload, timeout=AI_TIMEOUT,
                          headers={"x-goog-api-key": GEMINI_API_KEY})
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
        return text[:MAX_REPLY_CHARS] if text else FALLBACK_ERROR
    except Exception as e:
        log.warning("Gemini 调用失败: %s", e)
        return FALLBACK_ERROR


def reply_xml(recipient_openid, account_id, content):
    content = content.replace("]]>", "]] >")  # 防 CDATA 截断
    body = (
        f"<xml><ToUserName><![CDATA[{recipient_openid}]]></ToUserName>"
        f"<FromUserName><![CDATA[{account_id}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        f"<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content></xml>"
    )
    resp = make_response(body)
    resp.content_type = "application/xml; charset=utf-8"
    return resp


@app.get("/")
def health():
    return "Auctura AI WeChat webhook OK"


@app.get("/wechat")
def verify():
    """微信保存服务器配置时的一次性校验:验签后原样返回 echostr。"""
    if not check_signature(request.args):
        return ("signature mismatch", 403)
    return request.args.get("echostr", "")


@app.post("/wechat")
def incoming():
    if not check_signature(request.args):
        return ("signature mismatch", 403)
    try:
        msg = ET.fromstring(request.get_data())
    except ET.ParseError:
        return ("bad xml", 400)

    msg_type = msg.findtext("MsgType", "")
    from_user = msg.findtext("FromUserName", "")  # 用户 openid
    account = msg.findtext("ToUserName", "")      # 公众号原始 ID
    msg_id = msg.findtext("MsgId", "")

    now = time.time()
    for k in [k for k, (ts, _) in _seen.items() if now - ts > DEDUPE_TTL]:
        _seen.pop(k, None)

    if msg_id and msg_id in _seen:
        reply = _seen[msg_id][1]  # 微信重试同一条消息 → 回缓存答案
    elif msg_type == "text":
        user_text = (msg.findtext("Content") or "").strip()
        log.info("收到 %s…: %s", from_user[:8], user_text[:200])
        reply = ask_ai(user_text)
        log.info("回复: %s", reply[:200])
        if msg_id:
            _seen[msg_id] = (now, reply)
    elif msg_type == "event" and (msg.findtext("Event") or "").lower() == "subscribe":
        reply = WELCOME
    else:
        reply = NON_TEXT
    return reply_xml(from_user, account, reply)


if __name__ == "__main__":
    mode = f"Gemini: {GEMINI_MODEL}" if GEMINI_API_KEY else "无 AI 回显模式(GEMINI_API_KEY 未配置)"
    log.info("启动 — 端口 %s — %s", PORT, mode)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
