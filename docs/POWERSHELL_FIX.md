# PowerShell 执行策略问题解决方案

## ❌ 问题

运行 `.ps1` 脚本时出现错误：
```
无法加载文件，因为在此系统上禁止运行脚本
```

---

## ✅ 解决方案

### 方案 1：使用批处理文件（推荐，无需修改系统设置）⭐

**直接双击运行**：
- `start_public.bat` - 启动服务
- `stop_public.bat` - 停止服务

批处理文件（.bat）不受 PowerShell 执行策略限制，功能完全相同！

---

### 方案 2：临时允许当前脚本

右键点击 `start_public.ps1`，选择"属性"，勾选"解除锁定"，然后运行：

```powershell
PowerShell -ExecutionPolicy Bypass -File .\start_public.ps1
```

---

### 方案 3：修改 PowerShell 执行策略（需要管理员权限）

**以管理员身份**打开 PowerShell，运行：

```powershell
# 仅允许本地脚本运行（推荐）
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser

# 或者允许所有脚本（不推荐）
Set-ExecutionPolicy Unrestricted -Scope CurrentUser
```

然后就可以正常运行 `.ps1` 脚本了。

---

### 方案 4：每次临时绕过

```powershell
PowerShell -ExecutionPolicy Bypass -File .\start_public.ps1
```

或在当前 PowerShell 会话中运行：
```powershell
Set-ExecutionPolicy Bypass -Scope Process
.\start_public.ps1
```

---

## 🎯 推荐方案

**直接使用 .bat 文件**（方案 1），最简单无风险：

1. 双击 `start_public.bat` - 启动
2. 双击 `stop_public.bat` - 停止

功能完全相同，不需要修改任何系统设置！

---

## 📚 更多信息

PowerShell 执行策略详解：
https://docs.microsoft.com/zh-cn/powershell/module/microsoft.powershell.core/about/about_execution_policies

---

**更新日期**: 2026-06-10
