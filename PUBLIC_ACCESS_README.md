# 📱 IronTrader 3.0 - 公网访问配置指南

## 🎯 最简单方案：Ngrok（推荐）

### 步骤 1️⃣: 下载 Ngrok

**方法一：官网下载**
1. 访问 https://ngrok.com/download
2. 下载 Windows 版本
3. 解压到任意目录（建议放在 `C:\Program Files\ngrok`）
4. 将 ngrok.exe 所在目录添加到系统 PATH

**方法二：使用 Chocolatey**
```powershell
choco install ngrok
```

### 步骤 2️⃣: 注册 Ngrok 账号（免费）

1. 访问 https://dashboard.ngrok.com/signup
2. 使用 Google/GitHub 账号快速注册
3. 登录后访问 https://dashboard.ngrok.com/get-started/your-authtoken
4. 复制你的 authtoken

### 步骤 3️⃣: 配置 authtoken

打开 PowerShell，运行：
```powershell
ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
```

### 步骤 4️⃣: 一键启动（推荐）

**双击运行**: `start_public.ps1`

或在 PowerShell 中运行：
```powershell
.\start_public.ps1
```

### 步骤 5️⃣: 获取公网地址

1. 查看自动弹出的 Ngrok 窗口
2. 找到 `Forwarding` 行，复制 HTTPS 地址
3. 格式类似：`https://abcd-12-34-56-78.ngrok-free.app`

### 步骤 6️⃣: 手机访问

在手机浏览器输入刚才复制的地址即可！

---

## 🛑 停止服务

**双击运行**: `stop_public.ps1`

或手动关闭两个 PowerShell 窗口

---

## 📋 手动启动（如果需要）

### 启动 IronTrader
```powershell
python app.py
```

### 启动 Ngrok（新窗口）
```powershell
ngrok http 5002
```

---

## 🔒 安全建议

### 1. 添加访问密码（推荐）

编辑 `config.py`，添加：
```python
class FlaskConfig:
    # ... 其他配置
    BASIC_AUTH_USERNAME = 'admin'
    BASIC_AUTH_PASSWORD = 'your-strong-password'
```

安装 Flask-BasicAuth：
```bash
pip install Flask-BasicAuth
```

修改 `app.py`：
```python
from flask_basicauth import BasicAuth

app = Flask(__name__)
app.config.from_object(FlaskConfig)

# 添加基本认证
basic_auth = BasicAuth(app)

# 在路由上添加装饰器
@app.route('/api/market-state')
@basic_auth.required
def market_state():
    # ...
```

### 2. 使用固定域名（Ngrok 付费版）

免费版每次重启地址都会变，付费版可以固定域名：
```powershell
ngrok http 5002 --domain=your-fixed-domain.ngrok-free.app
```

### 3. 限制访问 IP（高级）

在 `app.py` 中添加 IP 白名单：
```python
from flask import request, abort

ALLOWED_IPS = ['你的IP地址']

@app.before_request
def limit_remote_addr():
    if request.remote_addr not in ALLOWED_IPS:
        abort(403)  # Forbidden
```

---

## 📱 测试 API

### 手机浏览器访问
```
https://your-ngrok-url.ngrok-free.app/
```

### 测试 API 端点
```
https://your-ngrok-url.ngrok-free.app/api/market-state
https://your-ngrok-url.ngrok-free.app/api/hotzt
https://your-ngrok-url.ngrok-free.app/api/search?q=平安
```

---

## 🚀 其他方案

### 方案 2: Cloudflare Tunnel（免费，稳定）

```powershell
# 安装
choco install cloudflared

# 登录
cloudflared tunnel login

# 创建隧道
cloudflared tunnel create irontrader

# 运行
cloudflared tunnel --url http://localhost:5002 run irontrader
```

### 方案 3: Serveo（无需注册，临时使用）

```powershell
ssh -R 80:localhost:5002 serveo.net
```

### 方案 4: Localtunnel（NPM）

```powershell
# 安装
npm install -g localtunnel

# 运行
lt --port 5002
```

---

## 💡 常见问题

### Q1: Ngrok 提示 "authtoken is not configured"
**解决**: 运行 `ngrok config add-authtoken YOUR_TOKEN`

### Q2: 手机访问显示 "Visit Site" 按钮
**原因**: Ngrok 免费版的防滥用机制  
**解决**: 点击 "Visit Site" 按钮继续访问（仅第一次需要）

### Q3: 地址访问不了
**检查**:
1. IronTrader 是否正常启动（访问 http://localhost:5002 测试）
2. Ngrok 是否正常运行
3. 防火墙是否阻止

### Q4: 每次重启地址都变
**解决**: 
- 使用 Ngrok 付费版固定域名
- 或使用 Cloudflare Tunnel（免费且固定）

### Q5: 想要自定义域名
**推荐**: Cloudflare Tunnel + 自己的域名（完全免费）

---

## 📞 快速帮助

如需帮助，查看：
- Ngrok 文档: https://ngrok.com/docs
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps

---

**更新日期**: 2026-06-10  
**适用版本**: IronTrader 3.0
