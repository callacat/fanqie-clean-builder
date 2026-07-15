#!/usr/bin/env python3
"""Search ALL file types in apktool output for modder server strings.
Domain confirmed by Mihomo capture: sg-datahub.changzhi.top (8.222.131.165)
Not found in smali const-strings — try .so, resources.arsc, and other file types.
"""
import re
from pathlib import Path

APKTOOL = Path("/tmp/apktool_out/")
TARGETS = ["changzhi.top", "changzhi", "sg-datahub", "8.222.131", "47.245.87", "HelloWorld"]
# Also hex-encoded representations, byte-swapped IP formats
HEX_VARIANTS = [
    "08de83a5",  # 8.222.131.165 in hex (big endian bytes as string)
    "0822:1381:0165",  # with colons
    "8.222.131.165",  # exact IP
    "sg-datahub",     # subdomain prefix
]
FOUND = {}

# 1. Search ALL files in apktool_out (not just smali)
print("=== Phase 1: Full apktool_out search ===")
for f in sorted(APKTOOL.rglob("*")):
    if not f.is_file():
        continue
    r = str(f.relative_to(APKTOOL))
    if any(x in r for x in ["/androidx/", "/annotation/"]):
        continue

    # Binary files: use raw bytes search
    try:
        data = f.read_bytes()
    except:
        continue

    # Check all targets
    for target in TARGETS + HEX_VARIANTS:
        if target.encode() in data:
            if target not in FOUND:
                FOUND[target] = []
            # Try to get context (for text files)
            try:
                text = data.decode("utf-8", errors="replace")
                for i, ln in enumerate(text.splitlines()):
                    if target in ln:
                        FOUND[target].append(f"{r}:{i+1}  {ln.strip()[:150]}")
                        break
                else:
                    FOUND[target].append(f"{r} (binary, offset approx {data.find(target.encode())})")
            except:
                offset = data.find(target.encode())
                FOUND[target].append(f"{r} (binary, offset {offset})")
            break

# 2. Search .so libs separately with strings-like approach
print("\n=== Phase 2: .so native libraries ===")
for so in sorted(APKTOOL.rglob("lib/*/*.so")):
    r = str(so.relative_to(APKTOOL))
    try:
        data = so.read_bytes()
    except:
        continue
    for target in TARGETS:
        if target.encode() in data:
            if target not in FOUND:
                FOUND[target] = []
            FOUND[target].append(f"{r} (native lib, offset {data.find(target.encode())})")

# 3. Search resources.arsc
print("\n=== Phase 3: Resources ===")
for res_file in sorted(APKTOOL.rglob("resources.arsc")):
    try:
        data = res_file.read_bytes()
    except:
        continue
    # Search for ASCII strings inside binary arsc
    strings_found = set()
    # Method: search for the target bytes directly
    for target in TARGETS:
        if target.encode() in data:
            strings_found.add(target)
    for s in strings_found:
        if s not in FOUND:
            FOUND[s] = []
        FOUND[s].append(f"{res_file.relative_to(APKTOOL)} (arsc)")

# 4. Output
print("\n=== RESULTS ===")
for target, locations in sorted(FOUND.items()):
    print(f"\n  {target}:")
    for loc in locations[:5]:
        print(f"    {loc}")

summary_path = Path("/tmp/all-files-search.txt")
summary_path.write_text("\n".join(f"{t}: {locs[0]}" if len(locs)==1 else f"{t}: {len(locs)} hits" for t, locs in sorted(FOUND.items())))
print(f"\nSummary saved to {summary_path}")
print(f"Total unique targets found: {len(FOUND)}")
