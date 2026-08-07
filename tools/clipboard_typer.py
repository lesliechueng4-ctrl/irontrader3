# -*- coding: utf-8 -*-
"""
剪贴板打字机：复制文本后，把光标放到目标输入框，按 Ctrl+Alt+V，
脚本会用模拟键盘（SendInput + Unicode）把剪贴板内容逐字敲进去。

用法:
    python clipboard_typer.py            # 常驻模式，Ctrl+Alt+V 触发，Ctrl+C 退出
    python clipboard_typer.py --once     # 单次模式：3 秒后直接开始打字（这 3 秒内点好输入框）
    python clipboard_typer.py --delay 50 # 每个字符间隔 50 毫秒（默认 20，目标程序反应慢就调大）
    python clipboard_typer.py --enter    # 打完后额外按一下回车

注意: 如果目标程序是以管理员身份运行的，本脚本也要用管理员身份运行，
      否则 Windows 会拦截模拟输入（UIPI 机制），表现为按了没反应。
"""
import argparse
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64 位下必须显式声明，否则返回的句柄/指针会被截断成 32 位
user32.GetClipboardData.restype = wintypes.HANDLE
user32.GetClipboardData.argtypes = [wintypes.UINT]
kernel32.GlobalLock.restype = wintypes.LPVOID
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
user32.VkKeyScanW.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [ctypes.c_wchar]

# ---------- SendInput 结构体定义 ----------
ULONG_PTR = ctypes.c_size_t

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

def _send_key_event(wVk, wScan, flags):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(wVk, wScan, flags, 0, 0)
    if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())

VK_LSHIFT = 0xA0

def _type_char_as_real_key(ch):
    """把字符转成真实虚拟键按下/抬起（含 Shift 组合）。
    按键录制器（如 MyKey）只认这种真实按键事件。映射不了返回 False。"""
    res = user32.VkKeyScanW(ch)
    if res == -1:
        return False
    vk = res & 0xFF
    shift_state = (res >> 8) & 0xFF
    if shift_state & ~1:  # 需要 Ctrl/Alt（如 AltGr 布局）的字符，走 Unicode 兜底
        return False
    if shift_state & 1:
        _send_key_event(VK_LSHIFT, 0, 0)
        time.sleep(0.005)
    _send_key_event(vk, 0, 0)
    time.sleep(0.005)
    _send_key_event(vk, 0, KEYEVENTF_KEYUP)
    if shift_state & 1:
        time.sleep(0.005)
        _send_key_event(VK_LSHIFT, 0, KEYEVENTF_KEYUP)
    return True

def type_text(text, char_delay_ms=20):
    """优先模拟真实按键（录制器/普通输入框都认）；
    键盘上打不出的字符（如中文）退回 KEYEVENTF_UNICODE 文本注入。"""
    for ch in text:
        if not _type_char_as_real_key(ch):
            # utf-16 code unit 逐个发（生僻字/emoji 是两个 code unit）
            for unit in memoryview(ch.encode("utf-16-le")).cast("H"):
                _send_key_event(0, unit, KEYEVENTF_UNICODE)
                _send_key_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(char_delay_ms / 1000.0)

def press_enter():
    VK_RETURN = 0x0D
    _send_key_event(VK_RETURN, 0, 0)
    _send_key_event(VK_RETURN, 0, KEYEVENTF_KEYUP)

# ---------- 剪贴板读取 ----------
CF_UNICODETEXT = 13

def get_clipboard_text():
    for _ in range(5):  # 剪贴板可能被别的程序短暂占用，重试几次
        if user32.OpenClipboard(None):
            try:
                handle = user32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return None
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return None
                try:
                    return ctypes.c_wchar_p(ptr).value
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        time.sleep(0.1)
    return None

# ---------- 等修饰键松开再打字（否则 Ctrl/Alt 还按着，字符会变成快捷键） ----------
VK_CONTROL, VK_MENU, VK_SHIFT = 0x11, 0x12, 0x10

def wait_modifiers_released(timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000
                   for vk in (VK_CONTROL, VK_MENU, VK_SHIFT)):
            return
        time.sleep(0.02)

def do_type(args):
    text = get_clipboard_text()
    if not text:
        print("[!] 剪贴板里没有文本")
        return
    wait_modifiers_released()
    type_text(text, args.delay)
    if args.enter:
        press_enter()
    print("[ok] 已输入 %d 个字符" % len(text))

# ---------- 全局热键 Ctrl+Alt+V ----------
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 1

def main():
    parser = argparse.ArgumentParser(description="复制文本后按 Ctrl+Alt+V 模拟键盘输入")
    parser.add_argument("--once", action="store_true", help="不注册热键，3 秒后直接打字一次")
    parser.add_argument("--delay", type=int, default=20, help="字符间隔毫秒数，默认 20")
    parser.add_argument("--enter", action="store_true", help="输入完成后按回车")
    args = parser.parse_args()

    if args.once:
        print("3 秒内请把光标点到目标输入框...")
        time.sleep(3)
        do_type(args)
        return

    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("V")):
        print("[!] 注册热键 Ctrl+Alt+V 失败（可能被其他程序占用）")
        sys.exit(1)
    print("已就绪：复制密码 -> 点到目标密码框 -> 按 Ctrl+Alt+V 自动输入。Ctrl+C 退出。")

    msg = wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                do_type(args)
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)

if __name__ == "__main__":
    main()
