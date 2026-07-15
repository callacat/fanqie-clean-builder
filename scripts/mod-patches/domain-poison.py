#!/usr/bin/env python3
"""Hongguo v7.2.7.32 — poison domains + disable checkUpdate"""
import re, sys
from pathlib import Path

APK = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/apktool_out")
# Don't use 127.0.0.1 - RST makes app detect "server error" and hang.
# Use 1.1.1.1 (Cloudflare) - always online, server responds 404 → app treats it as "no update"
POISON_HOST = "127.0.0.1"
# Only poison the explicit update server — CDN/API domains are needed for normal operation.
# These came from Mihomo logs during update-check, not from startup traffic.
TARGETS = ["oneseeker.top", "dongle.oneseeker.top", "changzhi.top"]

MODS = HITS = 0
# Match full URL pattern OR bare domain name / IP
RE_PATTERN = r'const-string\s+([vp\d]+)\s*,\s*"(https?://[^"]*'  # prefix before target
RE_SUFFIX = r'[^"]*)"'  # suffix after target
RE_BARE = r'const-string\s+([vp\d]+)\s*,\s*"([^"]*'  # bare match (no protocol prefix)

for sd in sorted(APK.glob("smali*")):
    if not sd.is_dir():
        continue
    for f in sd.rglob("*.smali"):
        r = str(f.relative_to(APK))
        if "/androidx/" in r or "/annotation/" in r:
            continue
        t = f.read_text("utf-8", errors="replace")
        lines = t.splitlines(keepends=True)
        dirty = False

        for i, ln in enumerate(lines):
            for target in TARGETS:
                if target not in ln:
                    continue
                # First try full URL pattern
                pattern = RE_PATTERN + re.escape(target) + RE_SUFFIX
                m = re.search(pattern, ln)
                if m:
                    reg, url = m.group(1), m.group(2)
                    indent = re.match(r"^(\s*)", ln).group(1)
                    lines[i] = f'{indent}const-string {reg}, "http://{POISON_HOST}"  # blocked (no update)\n'
                    dirty = True
                    HITS += 1
                    print(f"  {f.relative_to(APK)}:{i+1}  poison: {url[:50]}")
                    break
                # Try bare domain match (no protocol prefix)
                pattern2 = RE_BARE + re.escape(target) + r')"'
                m2 = re.search(pattern2, ln)
                if m2:
                    reg, val = m2.group(1), m2.group(2)
                    indent = re.match(r"^(\s*)", ln).group(1)
                    lines[i] = f'{indent}const-string {reg}, "{POISON_HOST}"  # blocked (no update)\n'
                    dirty = True
                    HITS += 1
                    print(f"  {f.relative_to(APK)}:{i+1}  poison(bare): {val[:50]}")
                    break

        if "UpdateServiceImpl.smali" == f.name:
            for i, ln in enumerate(lines):
                if ".method public checkUpdate(" in ln:
                    close_paren = ln.find(")")
                    after_sig = ln[close_paren + 1:].lstrip() if close_paren >= 0 else ""
                    is_void = after_sig.startswith("V")
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if ".locals" in lines[j]:
                            indent = re.match(r"^(\s*)", lines[j]).group(1)
                            locals_m = re.search(r"\.locals\s+(\d+)", lines[j])
                            loc = int(locals_m.group(1)) if locals_m else 0
                            nls = [lines[j]]
                            if loc == 0 and not is_void:
                                nls[0] = f"{indent}.locals 1\n"
                            if is_void:
                                nls.append(f"{indent}return-void  # disabled\n")
                            else:
                                nls.append(f"{indent}const/4 v0, 0x0\n")
                                nls.append(f"{indent}return v0  # disabled (false)\n")
                            lines[j:j+1] = nls
                            dirty = True
                            HITS += 1
                            print(f"  {f.relative_to(APK)}:{i+1}  checkUpdate disabled (ret={'V' if is_void else 'Z'})")
                            break
                    break

        if dirty:
            f.write_text("".join(lines))
            MODS += 1

print(f"\n=== Done: {MODS} files, {HITS} hits ===")
