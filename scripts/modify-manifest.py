#!/usr/bin/env python3
"""modify-manifest.py — 只修改 AndroidManifest.xml。

功能:
  1. appComponentFactory 替换
  2. 权限白名单过滤
  3. cleartext 关闭
  4. 删除推送组件声明（从 push_config 读取 <receiver>/<service> 列表）

原地修改，自动备份原始文件为 AndroidManifest.xml.bak。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_permissions(path: str) -> set[str]:
    """加载权限白名单，跳过空行和 # 注释行。"""
    perms: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                perms.add(line)
    return perms


# ---------------------------------------------------------------------------
# 功能 1: appComponentFactory 替换
# ---------------------------------------------------------------------------

def replace_component_factory(manifest_path: Path, new_factory: str) -> bool:
    """替换 application 标签中的 android:appComponentFactory 值。"""
    content = manifest_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r'(android:appComponentFactory\s*=\s*)"([^"]*)"',
    )

    def _replacer(m):
        return f'{m.group(1)}"{new_factory}"'

    new_content, n = pattern.subn(_replacer, content)

    if n > 0:
        manifest_path.write_text(new_content, encoding="utf-8")
        print(f"  ✓ appComponentFactory 替换 → {new_factory} ({n} 处)")
        return True

    print("  ! android:appComponentFactory 未找到，跳过")
    return False


# ---------------------------------------------------------------------------
# 功能 2: 权限白名单过滤
# ---------------------------------------------------------------------------

def filter_permissions(manifest_path: Path, keep: set[str]) -> int:
    """删除不在白名单中的 <uses-permission> 行。"""
    content = manifest_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r'<uses-permission\s+android:name\s*=\s*"([^"]*)"\s*/?\s*>',
        re.DOTALL,
    )

    removed = 0

    def _replacer(m):
        nonlocal removed
        name = m.group(1)
        if name not in keep:
            removed += 1
            print(f"  ✓ 移除权限: {name}")
            return ""
        return m.group(0)

    new_content = pattern.sub(_replacer, content)
    if removed > 0:
        manifest_path.write_text(new_content, encoding="utf-8")
    return removed


# ---------------------------------------------------------------------------
# 功能 3: Cleartext 关闭
# ---------------------------------------------------------------------------

def disable_cleartext(manifest_path: Path) -> bool:
    """android:usesCleartextTraffic="true" → "false" """
    content = manifest_path.read_text(encoding="utf-8")
    old = 'android:usesCleartextTraffic="true"'
    new = 'android:usesCleartextTraffic="false"'
    if old in content:
        content = content.replace(old, new)
        manifest_path.write_text(content, encoding="utf-8")
        print("  ✓ Cleartext true → false")
        return True
    print("  ! usesCleartextTraffic=\"true\" 未找到，跳过")
    return False


# ---------------------------------------------------------------------------
# 功能 4: 删除推送组件声明
# ---------------------------------------------------------------------------

def remove_push_components(manifest_path: Path, components: list[str]) -> int:
    """从 AndroidManifest.xml 删除推送 <receiver>/<service>/<provider>。"""
    content = manifest_path.read_text(encoding="utf-8")
    total = 0

    for comp in components:
        escaped = re.escape(comp)

        # 自闭合标签
        pattern1 = re.compile(
            rf'<(receiver|service|provider)\s+[^>]*?android:name\s*=\s*"{escaped}"[^>]*?/>',
            re.DOTALL,
        )

        def _replacer1(m, c=comp):
            return f"<!-- removed: {c} -->"

        content, n1 = pattern1.subn(_replacer1, content)
        total += n1

        # 配对标签
        pattern2 = re.compile(
            rf'<(receiver|service|provider)\s+[^>]*?android:name\s*=\s*"{escaped}"[^>]*?>.*?</\1>',
            re.DOTALL,
        )

        def _replacer2(m, c=comp):
            return f"<!-- removed: {c} -->"

        content, n2 = pattern2.subn(_replacer2, content)
        total += n2

        if n1 + n2 > 0:
            print(f"  ✓ 移除推送组件 ({n1 + n2} 处): {comp}")
        else:
            print(f"  ! 组件未找到: {comp}")

    if total > 0:
        manifest_path.write_text(content, encoding="utf-8")

    return total


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

DEFAULT_FACTORY = "com.pandora.core.AppFactory"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="独立修改 AndroidManifest.xml — appComponentFactory、权限、cleartext、推送",
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="AndroidManifest.xml 路径",
    )
    p.add_argument(
        "--push-config",
        required=True,
        help="推送删除配置文件路径 (JSON)",
    )
    p.add_argument(
        "--permissions-keep",
        required=True,
        help="权限白名单文件路径 (txt, 一行一条)",
    )
    p.add_argument(
        "--component-factory",
        default=DEFAULT_FACTORY,
        help=f"appComponentFactory 替换值 (默认: {DEFAULT_FACTORY}; "
             "传空字符串则不修改)",
    )
    p.add_argument(
        "--skip-component-factory",
        action="store_true",
        help="完全跳过 appComponentFactory 替换",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"[错误] Manifest 文件不存在: {args.manifest}", file=sys.stderr)
        return 1

    # 备份
    bak = manifest.with_suffix(".xml.bak")
    shutil.copy2(str(manifest), str(bak))
    print(f"  → 备份已创建: {bak}")

    push_config = load_json(args.push_config)
    keep_perms = load_permissions(args.permissions_keep)

    changes = 0

    # 1. appComponentFactory 替换
    print("\n--- 1. appComponentFactory 替换 ---")
    if args.skip_component_factory:
        print("  (跳过)")
    elif replace_component_factory(manifest, args.component_factory):
        changes += 1

    # 2. 权限白名单过滤
    print("\n--- 2. 权限白名单过滤 ---")
    if keep_perms:
        n = filter_permissions(manifest, keep_perms)
        print(f"  → 移除 {n} 个权限")
        if n:
            changes += 1
    else:
        print("  (权限白名单为空，跳过)")

    # 3. Cleartext 关闭
    print("\n--- 3. Cleartext 关闭 ---")
    if disable_cleartext(manifest):
        changes += 1

    # 4. 删除推送组件声明
    print("\n--- 4. 删除推送组件声明 ---")
    push_receivers = push_config.get("push_receivers_in_manifest", [])
    if push_receivers:
        n = remove_push_components(manifest, push_receivers)
        print(f"  → 移除 {n} 个推送组件")
        if n:
            changes += 1
    else:
        print("  (push_receivers_in_manifest 为空，跳过)")

    # 如果什么都没改，恢复备份
    if changes == 0:
        bak.replace(manifest)
        print("\n! 未做任何修改，已恢复原始文件")
    else:
        print(f"\n✓ 完成: {changes} 类修改已应用，备份: {bak.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
