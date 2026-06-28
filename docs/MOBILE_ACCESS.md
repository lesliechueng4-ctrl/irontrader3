# 手机访问 IronTrader（推荐 Tailscale 私有组网）

目标：在手机上安全地访问运行在你电脑上的 IronTrader，**无需公网 IP、无需端口转发、全程加密**，外人碰不到。

> 为什么用 Tailscale 而不是直接开公网端口/ngrok：
> IronTrader 没有完整的多用户鉴权，直接暴露到公网有风险（本项目历史上发生过凭据泄露）。
> Tailscale 把你的手机和电脑组进同一个私有虚拟局域网，只有你自己的设备能访问，安全且零配置。

---

## 一、让 IronTrader 监听局域网（默认只监听本机）

`start.bat` 默认绑定 `127.0.0.1`（仅本机）。要让其它设备能连，需绑定 `0.0.0.0`：

方式 A（临时，单次）——在 PowerShell 里：
```powershell
$env:FLASK_HOST = "0.0.0.0"
.\.venv\Scripts\python.exe run_background.py
```

方式 B（永久）——把 `start.bat` 里这一行改成：
```bat
set "FLASK_HOST=0.0.0.0"
```
> 仅在你打算让手机/局域网访问时这么做；只在本机用就保持 `127.0.0.1` 更安全。
> 服务器用的是 waitress（生产级），已支持多设备并发。

放行 Windows 防火墙（首次会弹窗，点“允许”）；或手动放行 5002 端口：
```powershell
New-NetFirewallRule -DisplayName "IronTrader 5002" -Direction Inbound -LocalPort 5002 -Protocol TCP -Action Allow
```

---

## 二、安装 Tailscale（电脑 + 手机各一次）

1. 电脑：到 https://tailscale.com/download 下载 Windows 版，安装后用同一个账号登录（Google/微软/GitHub 均可）。
2. 手机：App Store / Google Play 搜索 **Tailscale**，安装后用**同一个账号**登录。
3. 两台设备都登录后，会各自分配一个 `100.x.x.x` 的私有 IP。

查看电脑的 Tailscale IP：
```powershell
tailscale ip -4
```
（形如 `100.101.102.103`）

---

## 三、手机访问

手机连上 Tailscale（开关打开）后，浏览器访问：
```
http://<电脑的Tailscale-IP>:5002
```
例如 `http://100.101.102.103:5002`

> 提示：可在 Tailscale 后台给电脑设个易记的设备名（如 `home-pc`），
> 之后手机直接访问 `http://home-pc:5002` 即可（MagicDNS）。

---

## 四、可选：再加一道 API 密钥

即便在 Tailscale 私网内，也可以再开一层密钥：
```powershell
$env:IRONTRADER_API_KEY = "你的密钥"
```
重启后，手机首次访问 `http://home-pc:5002/?key=你的密钥` 写入 Cookie，之后正常使用。

---

## 五、常见问题

- **手机打不开**：确认①电脑端 `FLASK_HOST=0.0.0.0` 已生效；②手机和电脑 Tailscale 都已登录且开关打开；③Windows 防火墙已放行 5002。
- **页面没更新**：本应用模板会被缓存，改完代码用 `start.bat` 重启服务；手机端按需强制刷新。
- **想让局域网（同一 WiFi）也能直接连**：用电脑的局域网 IP（`ipconfig` 里的 `192.168.x.x`）+ `:5002`，同样需要 `FLASK_HOST=0.0.0.0` 和防火墙放行。Tailscale 的好处是换网络（如手机用 4G/5G）也能连。
