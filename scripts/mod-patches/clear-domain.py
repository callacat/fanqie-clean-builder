#!/usr/bin/env python3
"""
clear-domain.py — 清空 const-string 中的黑产域名，使 URL 构造失败抛出异常
从而达到不卡启动 + 不弹更新弹窗的效果。

原理: 域名替换为 "" → new URL("") → MalformedURLException → app 捕获异常放行
比 domain poison (127.0.0.1) 更好，因为不触发同步阻塞连接。

用法:
  python3 clear-domain.py /tmp/apktool_out

可在 TARGETS 中添加多个域名，脚本会逐一清空所有匹配的 const-string。
"""
import re, sys
from pathlib import Path

APK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/apktool_out")
TARGETS = ["oneseeker.top", "dongle.oneseeker.top", "changzhi.top"]
MODS = HITS = 0

for sd in sorted(APK.glob("smali*")):
    if not sd.is_dir(): continue
    for f in sd.rglob("*.smali"):
        r = str(f.relative_to(APK))
        if "/androidx/" in r: continue
        text = f.read_text("utf-8", errors="replace")
        # Check if any target exists in this file
        has_target = any(t in text for t in TARGETS)
        if not has_target: continue
        lines = text.splitlines(keepends=True)
        dirty = False
        new_lines = []
        for i, ln in enumerate(lines):
            matched = any(t in ln for t in TARGETS)
            if matched and ("const-string" in ln or "const-string/jumbo" in ln):
                indent = re.match(r"^(\s*)", ln).group(1)
                reg_match = re.search(r'(const-string\s+(?:/jumbo\s+)?[vp]\d+)', ln)
                target_name = next(t for t in TARGETS if t in ln)
                if reg_match:
                    new_lines.append(f"{indent}{reg_match.group(1)}, \"\"  # {target_name} blocked\n")
                else:
                    new_lines.append(f"{indent}# {target_name} blocked\n")
                HITS += 1
                print(f"  {r}:{i+1} emptied ({target_name})")
                dirty = True
            else:
                new_lines.append(ln)
        if dirty:
            f.write_text("".join(new_lines), encoding="utf-8")
            MODS += 1
print(f"=== 方案B Done: {MODS} files, {HITS} hits ===")
