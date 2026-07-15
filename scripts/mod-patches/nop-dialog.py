#!/usr/bin/env python3
"""Hongguo v19 — Precision patch: NOP InsertScreenView.showView() dialog show.

Target: com/ss/android/excitingvideo/InsertScreenView.smali
  .method public showView()V
    iget-object v0, p0, ...->mAlertDialog:Landroid/app/AlertDialog;
    ...
    invoke-virtual {v0}, Landroid/app/AlertDialog;->show()V   ← NOP this

This is safe because show() returns void → no VerifyError from NOP.
Also patches RewardAdNativeFragment dialog show as secondary target.

Usage: python3 hg-update-patch.py /tmp/apktool_out
"""
import re, sys
from pathlib import Path

SMALI = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/apktool_out")
PATCHED = 0

def is_blacklisted(path: str) -> bool:
    return any(x in path for x in ["/androidx/", "/annotation/", "/org/junit/"])

# ── Phase 1: InsertScreenView dialog show ──────────────────────
print("=== Phase 1: InsertScreenView.showView() dialog ===")
target1 = SMALI / "smali_classes17" / "com" / "ss" / "android" / "excitingvideo" / "InsertScreenView.smali"
if target1.exists():
    text = target1.read_text("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    dirty = False
    for i, ln in enumerate(lines):
        if "invoke-virtual {v0}, Landroid/app/AlertDialog;->show()V" in ln:
            indent = re.match(r"^(\s*)", ln).group(1)
            lines[i] = f"{indent}nop  # AlertDialog.show() disabled\n"
            dirty = True
            PATCHED += 1
            print(f"  ✅ {target1.relative_to(SMALI)}:{i+1}")

    if dirty:
        target1.write_text("".join(lines), encoding="utf-8")

# ── Phase 2: RewardAdNativeFragment dialog show ─────────────────
print("\n=== Phase 2: RewardAdNativeFragment dialog ===")
target2 = SMALI / "smali_classes17" / "com" / "ss" / "android" / "excitingvideo" / "sdk" / "RewardAdNativeFragment.smali"
if target2.exists():
    text = target2.read_text("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    dirty = False
    for i, ln in enumerate(lines):
        if "invoke-virtual {v0}, Landroid/app/AlertDialog;->show()V" in ln:
            indent = re.match(r"^(\s*)", ln).group(1)
            lines[i] = f"{indent}nop  # AlertDialog.show() disabled\n"
            dirty = True
            PATCHED += 1
            print(f"  ✅ {target2.relative_to(SMALI)}:{i+1}")
    if dirty:
        target2.write_text("".join(lines), encoding="utf-8")

# ── Phase 3: Dialog.show() in com.ss.android.excitingvideo package ──
print("\n=== Phase 3: excitingvideo Dialog.show() ===")
for f in sorted((SMALI / "smali_classes17" / "com" / "ss" / "android" / "excitingvideo").rglob("*.smali")):
    rel = str(f.relative_to(SMALI))
    if is_blacklisted(rel):
        continue
    text = f.read_text("utf-8", errors="replace")
    if "invoke-super" in text and "Dialog;->show()V" in text:
        lines = text.splitlines(keepends=True)
        dirty = False
        for i, ln in enumerate(lines):
            if "invoke-super {p0}, Landroid/app/Dialog;->show()V" in ln:
                indent = re.match(r"^(\s*)", ln).group(1)
                lines[i] = f"{indent}nop  # Dialog.show() disabled\n"
                dirty = True
                PATCHED += 1
                print(f"  ✅ {rel}:{i+1}  (invoke-super)")
        if dirty:
            f.write_text("".join(lines), encoding="utf-8")

print(f"\n=== Patch complete: {PATCHED} modifications ===")
