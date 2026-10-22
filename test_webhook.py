"""模拟微信服务器:对 webhook 做 GET 签名验证 + POST 文本消息测试。

用法: .venv\\Scripts\\python.exe test_webhook.py [base_url]
默认 base_url = http://127.0.0.1:8787(本地);
公网测试: .venv\\Scripts\\python.exe test_webhook.py https://<your-hostname>
"""
import hashlib
import pathlib
import sys
import time
import uuid

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8787"

TOKEN = ""
env = pathlib.Path(__file__).parent / ".env"
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("WECHAT_TOKEN="):
            TOKEN = line.split("=", 1)[1].strip()
if not TOKEN:
    sys.exit("WECHAT_TOKEN missing in .env")

ts, nonce = str(int(time.time())), uuid.uuid4().hex[:10]
sig = hashlib.sha1("".join(sorted([TOKEN, ts, nonce])).encode()).hexdigest()
q = f"signature={sig}&timestamp={ts}&nonce={nonce}"

# 1) GET 验证(微信保存服务器配置时做的事)
r = requests.get(f"{base}/wechat?{q}&echostr=echo_test_42", timeout=20)
ok = r.status_code == 200 and r.text == "echo_test_42"
print(f"[GET 验证] {'PASS' if ok else 'FAIL'} status={r.status_code} body={r.text[:80]!r}")

# 2) POST 文本消息(模拟用户在微信里发"你好")
xml = (
    "<xml><ToUserName><![CDATA[gh_demo_account]]></ToUserName>"
    "<FromUserName><![CDATA[oTestUser123]]></FromUserName>"
    f"<CreateTime>{ts}</CreateTime><MsgType><![CDATA[text]]></MsgType>"
    "<Content><![CDATA[你好,用一句话介绍你自己]]></Content>"
    f"<MsgId>{int(time.time() * 1000)}</MsgId></xml>"
)
r = requests.post(f"{base}/wechat?{q}", data=xml.encode("utf-8"), timeout=20,
                  headers={"Content-Type": "text/xml"})
print(f"[POST 消息] status={r.status_code}")
print(r.text)

# 3) 错误签名应被拒绝
r = requests.get(f"{base}/wechat?signature=bad&timestamp={ts}&nonce={nonce}&echostr=x", timeout=20)
print(f"[错误签名] {'PASS' if r.status_code == 403 else 'FAIL'} status={r.status_code}")
