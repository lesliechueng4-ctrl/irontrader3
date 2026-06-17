"""
IronTrader 3.0 - 公网访问配置指南

使用内网穿透工具将 IronTrader 暴露到公网，支持手机访问
"""

# ==========================================
# 方案 1: Ngrok（推荐）
# ==========================================

"""
1. 下载 Ngrok
   访问: https://ngrok.com/download
   或直接下载: https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip

2. 注册账号（免费）
   访问: https://dashboard.ngrok.com/signup

3. 获取 authtoken
   登录后访问: https://dashboard.ngrok.com/get-started/your-authtoken

4. 配置 authtoken
   打开 PowerShell，运行:
   ```
   ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
   ```

5. 启动 IronTrader
   ```
   python app.py
   ```

6. 启动 Ngrok（新窗口）
   ```
   ngrok http 5002
   ```

7. 复制公网地址
   终端会显示类似:
   Forwarding    https://abcd-1234-5678.ngrok-free.app -> http://localhost:5002

   用手机访问: https://abcd-1234-5678.ngrok-free.app
"""

# ==========================================
# 方案 2: Cloudflare Tunnel（推荐给长期使用）
# ==========================================

"""
1. 安装 Cloudflared
   下载: https://github.com/cloudflare/cloudflared/releases
   或通过 Chocolatey:
   ```
   choco install cloudflared
   ```

2. 登录 Cloudflare
   ```
   cloudflared tunnel login
   ```

3. 创建隧道
   ```
   cloudflared tunnel create irontrader
   ```

4. 配置域名（可选，或使用默认域名）
   ```
   cloudflared tunnel route dns irontrader irontrader.yourdomain.com
   ```

5. 运行隧道
   ```
   cloudflared tunnel --url http://localhost:5002 run irontrader
   ```

优点:
- 免费
- 稳定
- 可以绑定自定义域名
- 支持 HTTPS
"""

# ==========================================
# 方案 3: frp（国内速度快）
# ==========================================

"""
1. 下载 frp
   访问: https://github.com/fatedier/frp/releases
   下载 Windows 版本

2. 找一个有公网 IP 的服务器，或使用公共 frp 服务
   公共服务列表: http://www.frp.plus

3. 配置 frpc.ini
   ```ini
   [common]
   server_addr = frp服务器地址
   server_port = 7000

   [irontrader]
   type = http
   local_port = 5002
   custom_domains = your-subdomain.frp.domain.com
   ```

4. 启动客户端
   ```
   frpc.exe -c frpc.ini
   ```
"""

# ==========================================
# 方案 4: Serveo（最简单，无需注册）
# ==========================================

"""
1. 启动 IronTrader
   ```
   python app.py
   ```

2. 使用 SSH 转发
   ```
   ssh -R 80:localhost:5002 serveo.net
   ```

3. 会自动分配一个公网地址

注意: Serveo 不太稳定，仅适合临时测试
"""

# ==========================================
# 推荐脚本：一键启动 Ngrok + IronTrader
# ==========================================

STARTUP_SCRIPT_PS1 = """
# start_irontrader_public.ps1

# 启动 IronTrader
Write-Host "Starting IronTrader..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python app.py"

# 等待应用启动
Start-Sleep -Seconds 3

# 启动 Ngrok
Write-Host "Starting Ngrok..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "ngrok http 5002"

Write-Host "Done! Check Ngrok window for public URL" -ForegroundColor Cyan
"""

# ==========================================
# 安全建议
# ==========================================

SECURITY_NOTES = """
⚠️ 安全注意事项：

1. 添加访问认证
   - 使用 Flask 的 Basic Auth
   - 或添加 API Token 验证

2. 使用 HTTPS
   - Ngrok 和 Cloudflare 默认支持
   - 保护数据传输安全

3. 限制访问频率
   - 添加 Rate Limiting
   - 防止 API 滥用

4. 监控访问日志
   - 定期检查日志文件
   - 发现异常访问及时处理

5. 不要暴露敏感数据
   - 确保不在响应中返回密钥、密码等
   - 使用配置文件管理敏感信息
"""

# ==========================================
# 使用说明
# ==========================================

if __name__ == "__main__":
    print(__doc__)
    print("\n" + "="*60)
    print("推荐使用 Ngrok（方案1）- 最简单快速")
    print("="*60)
    print("\n快速开始:")
    print("1. 下载 Ngrok: https://ngrok.com/download")
    print("2. 注册并获取 authtoken")
    print("3. 运行: ngrok config add-authtoken YOUR_TOKEN")
    print("4. 启动应用: python app.py")
    print("5. 启动 Ngrok: ngrok http 5002")
    print("6. 复制公网地址，手机访问即可！")
