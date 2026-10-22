# wechat-ai-webhook

An AI auto-reply webhook for a WeChat Official Account, small enough to read in one
sitting. WeChat posts each user message to this server; the server verifies the
signature, asks a language model, and returns the reply as WeChat's passive-reply XML,
all inside WeChat's five-second deadline.

```
User message in WeChat
  -> WeChat servers POST https://<your-hostname>/wechat
  -> Cloudflare tunnel (no inbound port, no public IP)
  -> Flask on 127.0.0.1:8787  (server.py)
       signature check -> parse XML -> Gemini (3.5 s budget) -> XML reply
```

Built in June 2026 to test whether an AI auto-reply for small-business WeChat accounts
was worth pursuing. It runs against the free WeChat sandbox account; the notes at the bottom
say what a production account would add.

## Design points

- **Five-second contract.** WeChat drops the connection after five seconds and
  retries the same message up to three times. The model call is capped at 3.5 s to
  leave room for the tunnel round trip; on timeout the user gets a fixed fallback
  line instead of silence.
- **Idempotent on retries.** Replies are cached by `MsgId` for five minutes, so a
  WeChat retry returns the same answer instead of calling the model again.
- **Fails safe without a key.** With no `GEMINI_API_KEY` the server runs in echo mode
  and still completes the whole chain, which is how the tunnel and signature path were
  verified before any model was attached.
- **No shipped secrets.** The signature token is read from `.env` and the server
  refuses to start without it. Model "thinking" is disabled for the chat model so
  replies land inside the budget.
- **Replies fit WeChat's limits.** Output is clipped to 750 characters (the passive
  reply cap is 2048 bytes, and CJK text is 3 bytes per character), and `]]>` is
  escaped so a reply can never break out of the CDATA block.

## Files

| File | Purpose |
|---|---|
| `server.py` | Flask app: `GET /wechat` (one-time verification), `POST /wechat` (messages), `GET /` (health) |
| `test_webhook.py` | Simulates WeChat: signed GET verification, signed POST text message, and a bad-signature request that must get 403 |
| `start.ps1`, `stop.ps1` | Start and stop the server and its tunnel; touch only this project's processes |
| `.env.example` | Configuration keys; copy to `.env` |
| `cloudflared-wechat.example.yml` | Tunnel config template; copy to `cloudflared-wechat.yml` |

## Run it

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
copy .env.example .env            # set WECHAT_TOKEN (any private string); GEMINI_API_KEY optional
.venv\Scripts\python.exe server.py
.venv\Scripts\python.exe test_webhook.py                 # against localhost
.venv\Scripts\python.exe test_webhook.py https://<your-hostname>   # through the tunnel
```

Expected test output: `PASS` for the GET verification, a `200` with an XML body for the
message, and `PASS` for the rejected signature.

### Expose it with a Cloudflare tunnel

```
cloudflared tunnel create wechat-ai
copy cloudflared-wechat.example.yml cloudflared-wechat.yml   # fill in the tunnel uuid and hostname
cloudflared tunnel --config cloudflared-wechat.yml route dns --overwrite-dns wechat-ai wechat.example.com
cloudflared tunnel --config cloudflared-wechat.yml run wechat-ai
```

Pass `--config` explicitly: `cloudflared` otherwise reads `~/.cloudflared/config.yml`,
which may belong to a different tunnel on the same machine.

### Point the WeChat sandbox at it

1. Open the WeChat sandbox (test account) page and sign in by QR code.
2. Under the interface configuration section enter the URL `https://<your-hostname>/wechat` and the same
   `WECHAT_TOKEN` as in `.env`, then submit. WeChat calls `GET /wechat` with a
   signature and expects the `echostr` back.
3. Follow the sandbox account with your phone and send a text message.

## What a production account would add

- AES encrypted message mode (the sandbox is plaintext).
- `access_token` based active replies for the 48-hour customer-service window, when
  an answer needs more than five seconds.
- A host that is not a laptop: the obvious move is a Cloudflare Worker, which removes
  the tunnel and the local process entirely.

## License

MIT
