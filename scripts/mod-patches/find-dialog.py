#!/usr/bin/env python3
"""Find the exact smali class containing the dialog text '7.2.8.32' or '2026.7.11'"""
import re, sys
from pathlib import Path
APK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/apktool_out")
TEXTS = ["7.2.8.32", "2026.7.11", "温馨提示", "立即更新", "会员纯净", "精简版"]
found = []
for sd in sorted(APK.glob("smali*")):
    if not sd.is_dir(): continue
    for f in sd.rglob("*.smali"):
        try:
            t = f.read_text("utf-8", errors="replace")
            for txt in TEXTS:
                if txt in t:
                    r = str(f.relative_to(APK))
                    print(f"  {r}  -> '{txt}'")
                    found.append((r, txt))
                    break
        except: continue
print(f"\n=== Found {len(found)} matches ===")
