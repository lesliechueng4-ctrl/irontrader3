# -*- coding: utf-8 -*-
"""
MyKey 模版生成器：把文本（默认读剪贴板）转成 MyKey"高级键鼠组合动作"模版 yml。
在 MyKey 里"载入模版" -> "下载到设备"，之后按硬件键即可在 BIOS 等环境敲出该文本。

用法:
    python mykey_template_gen.py                      # 读剪贴板，输出 mykey_password.yml
    python mykey_template_gen.py --text "Abc123!"     # 指定文本（注意会留在命令行历史里）
    python mykey_template_gen.py --enter              # 末尾追加回车
    python mykey_template_gen.py --name pwd --slot 1 -o C:\\Users\\Admin\\Documents\\out.yml
    python mykey_template_gen.py --decode 2.yml       # 反解已有模版，核对按键序列

格式（逆向自 MyKey V5.53 保存的模版）:
    software_info = [1, 7, 1, N] + N 条记录
    每条记录 7 个字节 = 一帧标准 USB HID 键盘报文 [modifier, keycode, 0,0,0,0,0]
    modifier: bit1=左Shift(2)；keycode: HID Usage ID（a=4 ... 1=30 ... 回车=40）
    末尾: [252,0,0,0,0,0,0] 终止标记 + [0]*7 填充
"""
import argparse
import os
import sys

# ---------- 字符 -> (HID 键码, 是否需要 Shift)，美式布局 ----------
CHAR_MAP = {}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    CHAR_MAP[_c] = (4 + _i, False)
    CHAR_MAP[_c.upper()] = (4 + _i, True)
for _i, _c in enumerate("1234567890"):
    CHAR_MAP[_c] = (30 + _i, False)
for _i, _c in enumerate("!@#$%^&*()"):
    CHAR_MAP[_c] = (30 + _i, True)
for _c, _code in {"\n": 40, "\t": 43, " ": 44, "-": 45, "=": 46, "[": 47,
                  "]": 48, "\\": 49, ";": 51, "'": 52, "`": 53, ",": 54,
                  ".": 55, "/": 56}.items():
    CHAR_MAP[_c] = (_code, False)
for _c, _code in {"_": 45, "+": 46, "{": 47, "}": 48, "|": 49, ":": 51,
                  '"': 52, "~": 53, "<": 54, ">": 55, "?": 56}.items():
    CHAR_MAP[_c] = (_code, True)

MOD_LSHIFT = 2
END_MARK = 252
ENTER = 40
BACKSPACE = 42

def text_to_reports(text, add_enter=False):
    """每个字符生成 按下/抬起 HID 报文；带 Shift 的字符是 Shift按下->键按下->键抬起->Shift抬起"""
    reports = []
    bad = []
    for ch in text:
        if ch not in CHAR_MAP:
            bad.append(ch)
            continue
        code, shift = CHAR_MAP[ch]
        if shift:
            reports.append([MOD_LSHIFT, 0])   # Shift 按下
            reports.append([MOD_LSHIFT, code])  # 键按下（Shift 保持）
            reports.append([MOD_LSHIFT, 0])   # 键抬起
            reports.append([0, 0])            # Shift 抬起
        else:
            reports.append([0, code])
            reports.append([0, 0])
    if add_enter:
        reports.append([0, ENTER])
        reports.append([0, 0])
    return reports, bad

def build_yaml(reports, name="password", slot=1):
    nums = [1, 7, 1, len(reports) + 2]
    for mod, code in reports:
        nums += [mod, code, 0, 0, 0, 0, 0]
    nums += [END_MARK, 0, 0, 0, 0, 0, 0]
    nums += [0, 0, 0, 0, 0, 0, 0]
    lines = ["---", "keyboardType: Single1Advanced", "%d:" % slot,
             "  text: %s" % name, "  software_info:"]
    lines += ["  - %d" % n for n in nums]
    lines.append("  hardware_info: []")
    return "\n".join(lines) + "\n"

# ---------- 反解模版（核对用） ----------
REV = {}
for _ch, (_code, _shift) in CHAR_MAP.items():
    REV[(_code, _shift)] = _ch

def decode_file(path, mask=False):
    nums = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("- ") and s[2:].lstrip("-").isdigit():
                nums.append(int(s[2:]))
    if len(nums) < 4 or nums[1] != 7:
        print("[!] 不像是按键模版（头部 %r）" % nums[:4])
        return
    out = []
    body = nums[4:]
    for i in range(0, len(body) - 6, 7):
        mod, code = body[i], body[i + 1]
        if mod == END_MARK:
            break
        if code == 0:
            continue  # 抬起帧 / 单独的修饰键帧
        shift = bool(mod & MOD_LSHIFT)
        if code == BACKSPACE:
            out.append("[退格]")
        elif code == ENTER:
            out.append("[回车]")
        else:
            out.append(REV.get((code, shift), "[?%d%s]" % (code, "+Shift" if shift else "")))
    if mask:
        shown = "".join("*" if len(t) == 1 else t for t in out)
    else:
        shown = "".join(out)
    print("共 %d 个键: %s" % (len(out), shown))

def get_clipboard():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from clipboard_typer import get_clipboard_text
    return get_clipboard_text()

def main():
    p = argparse.ArgumentParser(description="剪贴板文本 -> MyKey 高级键鼠模版 yml")
    p.add_argument("--text", help="要输入的文本（默认读剪贴板）")
    p.add_argument("--enter", action="store_true", help="末尾追加回车")
    p.add_argument("--name", default="password", help="宏名称，默认 password")
    p.add_argument("--slot", type=int, default=1, help="按键槽位号，默认 1")
    p.add_argument("-o", "--out", default=os.path.join(os.path.expanduser("~"), "Documents", "mykey_password.yml"))
    p.add_argument("--decode", metavar="YML", help="反解已有模版文件并打印按键序列")
    p.add_argument("--mask", action="store_true", help="反解时用 * 遮住字符")
    args = p.parse_args()

    if args.decode:
        decode_file(args.decode, args.mask)
        return

    text = args.text if args.text is not None else get_clipboard()
    if not text:
        print("[!] 剪贴板里没有文本")
        sys.exit(1)
    text = text.strip("\r\n")

    reports, bad = text_to_reports(text, args.enter)
    if bad:
        print("[!] 这些字符打不出来，已跳过: %s" % "".join(sorted(set(bad))))
    total = len(reports) + 2
    if total > 70:
        print("[!] 警告: 共 %d 帧，超过设备 70 帧上限，可能存不下" % total)

    with open(args.out, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(build_yaml(reports, args.name, args.slot))
    print("[ok] 已生成 %s（%d 个字符, %d 帧）" % (args.out, len(text), total))
    print("下一步: MyKey -> 高级键鼠组合动作 -> 载入模版 -> 选这个文件 -> 下载到设备")

if __name__ == "__main__":
    main()
