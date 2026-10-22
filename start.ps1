# 启动微信 AI webhook(Flask 服务器 + wechat-ai 隧道);已在跑的部分自动跳过
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue) {
    "server already listening on 8787"
} else {
    Start-Process -FilePath "$proj\.venv\Scripts\python.exe" -ArgumentList "`"$proj\server.py`"" -WorkingDirectory $proj -WindowStyle Minimized
    "server started (port 8787)"
}

$tun = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object { $_.CommandLine -like '*wechat-ai*' }
if ($tun) {
    "tunnel already running (PID $($tun.ProcessId))"
} else {
    Start-Process -FilePath "C:\Program Files (x86)\cloudflared\cloudflared.exe" -ArgumentList "tunnel --config `"$proj\cloudflared-wechat.yml`" run wechat-ai" -WindowStyle Minimized
    "tunnel started (wechat-ai)"
}
