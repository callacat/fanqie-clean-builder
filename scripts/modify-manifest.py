#!/usr/bin/env python3
"""modify-manifest.py — 修改 AndroidManifest.xml。

功能:
  1. appComponentFactory 替换
  2. 权限白名单过滤
  3. cleartext 关闭
  4. 自动删除所有 android:name 引用已删除包的组件声明

原地修改，自动备份原始文件为 AndroidManifest.xml.bak。
"""

from __future__ import annotations

import argparse, json, re, shutil, sys
from pathlib import Path


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_permissions(path: str) -> set[str]:
    perms: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                perms.add(line)
    return perms


# ── 1. appComponentFactory ──

def replace_component_factory(manifest_path: Path, new_factory: str) -> bool:
    content = manifest_path.read_text(encoding="utf-8")
    pattern = re.compile(r'(android:appComponentFactory\s*=\s*)"([^"]*)"')
    new_content, n = pattern.subn(lambda m: f'{m.group(1)}"{new_factory}"', content)
    if n > 0:
        manifest_path.write_text(new_content, encoding="utf-8")
        print(f"  ✓ appComponentFactory → {new_factory} ({n} 处)")
        return True
    print("  ! appComponentFactory 未找到，跳过")
    return False


# ── 2. 权限白名单 ──

def filter_permissions(manifest_path: Path, keep: set[str]) -> int:
    content = manifest_path.read_text(encoding="utf-8")
    pattern = re.compile(r'<uses-permission\s+android:name\s*=\s*"([^"]*)"\s*/?\s*>', re.DOTALL)
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


# ── 3. Cleartext ──

def disable_cleartext(manifest_path: Path) -> bool:
    content = manifest_path.read_text(encoding="utf-8")
    if 'android:usesCleartextTraffic="true"' in content:
        content = content.replace('android:usesCleartextTraffic="true"', 'android:usesCleartextTraffic="false"')
        manifest_path.write_text(content, encoding="utf-8")
        print("  ✓ Cleartext true → false")
        return True
    print("  ! usesCleartextTraffic=\"true\" 未找到，跳过")
    return False


# ── 4. 自动删除组件声明 ──

# 匹配 <activity/service/receiver/provider android:name="xxx">
# 同时支持自闭合和配对标签
RE_COMPONENT = re.compile(
    r'<(activity|service|receiver|provider)\s+'
    r'[^>]*?android:name\s*=\s*"([^"]*)"'
    r'[^>]*?(?:/>|>.*?</\1>)',
    re.DOTALL,
)


def extract_package_prefixes(deleted_packages: list[str]) -> list[str]:
    """从删除列表中提取包名前缀。
    支持 package.name 格式和 fully.qualified.ClassName 格式。
    """
    prefixes: set[str] = set()
    for p in deleted_packages:
        p = p.replace("/", ".")  # ponytail: config paths use /, manifest uses .
        parts = p.split(".")
        # 找到第一个大写字母开头的部分（类名开始）
        for i, part in enumerate(parts):
            if part and part[0].isupper():
                # 类名之前的都是包名
                prefix = ".".join(parts[:i])
                if prefix:
                    prefixes.add(prefix)
                break
        else:
            # 没有大写部分 = 纯包名
            prefixes.add(p)
    return sorted(prefixes)


def remove_dead_components(manifest_path: Path, prefix_list: list[str]) -> int:
    """找到所有 android:name 以 prefix_list 任意一项开头的组件声明，
    将它们替换为注释。"""
    content = manifest_path.read_text(encoding="utf-8")
    total = 0
    seen: set[str] = set()

    for match in list(RE_COMPONENT.finditer(content)):
        comp_type = match.group(1)
        comp_name = match.group(2)
        full_match = match.group(0)

        if comp_name in seen:
            continue
        seen.add(comp_name)

        matched_prefix = None
        for prefix in prefix_list:
            if comp_name.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix is not None:
            placeholder = f"<!-- removed {comp_type}: {comp_name} -->"
            content = content.replace(full_match, placeholder, 1)
            total += 1
            print(f"  ✓ 移除 {comp_type}: {comp_name} (匹配: {matched_prefix})")

    if total > 0:
        manifest_path.write_text(content, encoding="utf-8")
    return total


# ── main ──

DEFAULT_FACTORY = "com.pandora.core.AppFactory"


def main() -> int:
    parser = argparse.ArgumentParser(description="修改 AndroidManifest.xml")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--push-config", required=True)
    parser.add_argument("--permissions-keep", required=True)
    parser.add_argument("--component-factory", default=DEFAULT_FACTORY,
                        help=f"默认: {DEFAULT_FACTORY}")
    parser.add_argument("--skip-component-factory", action="store_true")
    args = parser.parse_args()

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"[错误] Manifest 文件不存在", file=sys.stderr)
        return 1

    bak = manifest.with_suffix(".xml.bak")
    shutil.copy2(str(manifest), str(bak))
    print(f"  → 备份: {bak}")

    push_config = load_json(args.push_config)
    keep_perms = load_permissions(args.permissions_keep)
    changes = 0

    # 1. appComponentFactory
    print("\n--- 1. appComponentFactory ---")
    if args.skip_component_factory:
        print("  (跳过)")
    elif replace_component_factory(manifest, args.component_factory):
        changes += 1

    # 2. 权限
    print("\n--- 2. 权限 ---")
    if keep_perms:
        n = filter_permissions(manifest, keep_perms)
        print(f"  → 移除 {n} 个权限")
        if n:
            changes += 1
    else:
        print("  (空，跳过)")

    # 3. Cleartext
    print("\n--- 3. Cleartext ---")
    if disable_cleartext(manifest):
        changes += 1

    # 4. 自动删除组件
    print("\n--- 4. 删除关联已删除包的组件 ---")
    deleted_packages = push_config.get("push_packages", [])
    if deleted_packages:
        prefixes = extract_package_prefixes(deleted_packages)
        print(f"  → 检测到 {len(prefixes)} 个包前缀: {', '.join(prefixes)}")
        n = remove_dead_components(manifest, prefixes)
        print(f"  → 移除 {n} 个组件声明")
        if n:
            changes += 1
    else:
        print("  (空，跳过)")

    if changes == 0:
        bak.replace(manifest)
        print("\n! 未做修改，已恢复")
    else:
        print(f"\n✓ 完成: {changes} 类修改")

    return 0


if __name__ == "__main__":
    sys.exit(main())
