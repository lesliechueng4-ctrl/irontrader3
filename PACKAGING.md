# IronTrader Windows 便携版

## 使用

1. 解压 `IronTrader-Windows.zip`。
2. 双击文件夹中的 `IronTrader.exe`。
3. 保持弹出的命令行窗口开启；浏览器会自动打开应用。
4. 使用结束后，在该窗口按 `Ctrl+C` 停止服务。

目标电脑不需要安装 Python。便携版仅支持 64 位 Windows；行情和扫描依赖互联网及上游数据源。

运行产生的缓存、导出和日志默认存放在 `%LOCALAPPDATA%\IronTrader`。如需改到其他磁盘，在启动前设置环境变量 `IRONTRADER_DATA_DIR`。

## 构建

在开发电脑的项目根目录运行：

```powershell
.\scripts\build_windows.ps1 -Clean
```

构建完成后，把 `dist\IronTrader-Windows.zip` 发给其他 Windows 电脑即可。
