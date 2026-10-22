# 停止微信 AI webhook —— 只停本项目的进程,不碰 gold-scalper 交易隧道
$conn = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; "server stopped" } else { "server not running" }

$tun = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" | Where-Object { $_.CommandLine -like '*wechat-ai*' }
if ($tun) {
    $tun | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "tunnel stopped (PID $($_.ProcessId))" }
} else { "tunnel not running" }
