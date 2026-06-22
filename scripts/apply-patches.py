#!/usr/bin/env python3
"""apply-patches.py — Apply smali patches to official APK decompile output.

Usage:
  python3 apply-patches.py --source <official_smali_root> --patches <patches_dir> [--dry-run]

The patches directory is produced by smali_diff_harvester.py.
Files are matched by class name (.class directive), NOT by filesystem path,
to handle dex re-shuffling between APK versions.

Patch types:
  - smali/pandora-core/    → full file copy (new files from modded APK)
  - smali/lancet-hooks/    → unified diff apply
  - smali/sign-checks/     → unified diff apply
  - smali/device-spoof/    → unified diff apply
  - smali/metadata/        → skipped (debug metadata only, no logic change)
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

PATCH_CATEGORIES = {
    'pandora-core': 'copy',    # New files, just copy into source
    'lancet-hooks': 'diff',    # Apply unified diff
    'sign-checks': 'diff',     # Apply unified diff
    'device-spoof': 'diff',    # Apply unified diff
    'manifest': 'manifest',    # Handled by modify-manifest.py, skip here
    'metadata': 'skip',        # Debug metadata only, no logic change
}

CLASS_RE = re.compile(r'^\.class\s+(?:public\s+|final\s+|abstract\s+)*L([\w/$-]+);', re.MULTILINE)


def find_smali_by_class_name(source_root: Path, class_name: str) -> Path | None:
    """Find a smali file by its class name (from .class directive), ignoring directory structure."""
    for f in source_root.rglob('*.smali'):
        content = f.read_bytes()
        m = CLASS_RE.search(content.decode('utf-8', errors='replace'))
        if m and m.group(1) == class_name:
            return f
    return None


def apply_diff_file(target_path: Path, diff_content: str) -> bool:
    """Apply a unified diff to a smali file. Returns True on success."""
    # Parse the patch header to get the target class name
    # Format: # Official: smali_classes18/zo4/b.smali
    # The diff body is a standard unified diff
    # We use the file's .class directive as the anchor, then apply line-by-line

    if not target_path.exists():
        print(f"  ERROR: target not found: {target_path}")
        return False

    lines = target_path.read_text(encoding='utf-8').splitlines(keepends=True)
    patch_lines = diff_content.splitlines(keepends=True)

    # Simple line-based patch application:
    # Parse the unified diff hunks and apply them
    # A hunk looks like:
    # @@ -start,count +start,count @@
    #  context line
    # -removed line
    # +added line
    #  context line

    result = list(lines)
    current_line = 0  # 0-based
    applied = False

    for line in patch_lines:
        # Skip header lines (---, +++, # comments)
        if line.startswith('--- ') or line.startswith('+++ ') or line.startswith('#'):
            continue
        # Skip @@ hunk headers - we track position from original lines
        if line.startswith('@@'):
            # Parse: @@ -old_start,old_count +new_start,new_count @@
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if m:
                current_line = int(m.group(1)) - 1  # Convert 1-based to 0-based
            continue

        if line.startswith('-'):
            # Remove line: line should exist in source
            stripped = line[1:]
            if current_line < len(result) and result[current_line].rstrip('\n') == stripped.rstrip('\n'):
                result.pop(current_line)
                # Don't increment - next line shifts into this position
            else:
                print(f"  WARNING: remove mismatch at line {current_line+1}")
                print(f"    expected: {stripped.rstrip()}")
                print(f"    actual:   {result[current_line].rstrip() if current_line < len(result) else 'EOF'}")
                current_line += 1
        elif line.startswith('+'):
            # Add line: insert before current position
            stripped = line[1:]
            result.insert(current_line, stripped)
            current_line += 1
            applied = True
        else:
            # Context line: skip (ensure it matches? optional validation)
            current_line += 1

    if applied:
        target_path.write_text(''.join(result), encoding='utf-8')
        return True

    print("  SKIP: no changes applied (patch already present?)")
    return False


def copy_new_files(source_root: Path, patches_dir: Path, category: str) -> int:
    """Copy new files from patches/pandora-core/ into source."""
    src_dir = patches_dir / 'smali' / category
    if not src_dir.exists():
        return 0

    count = 0
    for patch_file in src_dir.rglob('*.smali.patch'):
        content = patch_file.read_text(encoding='utf-8')

        # Parse patch header to find modded path
        # # Modded: smali_classes24/com/pandora/core/AppFactory.smali
        modded_match = re.search(r'^# Modded:\s+(.+\.smali)', content, re.MULTILINE)
        if not modded_match:
            print(f"  SKIP {patch_file.name}: no modded path header")
            continue

        rel_path = modded_match.group(1).strip()

        # Check if this is a new file (--- /dev/null in diff header)
        if '--- /dev/null' not in content:
            # This is a modified file, handled by diff category
            continue

        # Extract the actual smali content from the patch (lines after diff body)
        # The actual content should be after the last @@ hunk
        lines = content.splitlines()
        smali_lines = []
        in_hunk = False
        for line in lines:
            if line.startswith('@@'):
                in_hunk = True
                continue
            if in_hunk and line.startswith('+'):
                smali_lines.append(line[1:])

        if not smali_lines:
            print(f"  SKIP {patch_file.name}: no content found")
            continue

        # Determine target path - use class name to locate target directory
        smali_content = '\n'.join(smali_lines)
        class_m = CLASS_RE.search(smali_content)
        if not class_m:
            print(f"  SKIP {patch_file.name}: no class name in content")
            continue

        class_name = class_m.group(1)
        # Find the target directory by looking for existing files in the same package
        pkg_dir = class_name.rsplit('/', 1)[0] if '/' in class_name else ''
        # Put in smali_classes29 (the last dex slot) to avoid offset overflow
        target_dir = source_root / 'smali_classes29' / pkg_dir
        target_file = target_dir / f'{class_name.rsplit("/", 1)[-1]}.smali'

        target_dir.mkdir(parents=True, exist_ok=True)
        target_file.write_text(smali_content + '\n', encoding='utf-8')
        count += 1
        print(f"  COPY {rel_path} -> {target_file.relative_to(source_root)}")

    return count


def apply_diff_patches(source_root: Path, patches_dir: Path, category: str) -> int:
    """Apply unified diff patches from a category directory."""
    src_dir = patches_dir / 'smali' / category
    if not src_dir.exists():
        return 0

    count = 0
    for patch_file in sorted(src_dir.glob('*.smali.patch')):
        content = patch_file.read_text(encoding='utf-8')
        if '--- /dev/null' in content:
            continue  # new files handled by copy_new_files

        # Extract official class name from patch header
        # # Official: smali_classes18/zo4/b.smali
        off_match = re.search(r'^# Official:\s+(.+\.smali)', content, re.MULTILINE)
        if not off_match:
            print(f"  SKIP {patch_file.name}: no official path header")
            continue

        # Get the class name from the path
        rel_path = off_match.group(1).strip()
        # Remove smali_classesN/ prefix to get relative path
        smali_rel = re.sub(r'^smali(_classes\d+)?/', '', rel_path)
        class_name = smali_rel.replace('.smali', '')

        target = find_smali_by_class_name(source_root, class_name)
        if not target:
            print(f"  SKIP {class_name}: not found in source by class name")
            print(f"    (tried: {smali_rel})")
            continue

        if apply_diff_file(target, content):
            count += 1
            print(f"  PATCH {patch_file.name} -> {target.relative_to(source_root)}")

    return count


def main():
    parser = argparse.ArgumentParser(description='Apply smali patches to official APK')
    parser.add_argument('--source', required=True, help='Official smali root (apktool out)')
    parser.add_argument('--patches', default='patches', help='Patches directory')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    args = parser.parse_args()

    source_root = Path(args.source).resolve()
    patches_dir = Path(args.patches).resolve()

    if not source_root.is_dir():
        print(f"ERROR: source directory not found: {source_root}")
        sys.exit(1)
    if not patches_dir.is_dir():
        print(f"ERROR: patches directory not found: {patches_dir}")
        sys.exit(1)

    total = 0

    for category, action in PATCH_CATEGORIES.items():
        cat_patches = patches_dir / 'smali' / category
        if not cat_patches.exists():
            continue

        print(f"\n=== {category} ({action}) ===")

        if args.dry_run:
            files = list(cat_patches.rglob('*.smali.patch'))
            print(f"  Would process {len(files)} files")
            total += len(files)
            continue

        if action == 'copy':
            n = copy_new_files(source_root, patches_dir, category)
            total += n
            print(f"  Copied {n} new files")
        elif action == 'diff':
            n = apply_diff_patches(source_root, patches_dir, category)
            total += n
            print(f"  Applied {n} diffs")
        elif action == 'skip':
            n = len(list(cat_patches.rglob('*.smali.patch')))
            total += n
            print(f"  Skipped {n} metadata-only patches")

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Total patches processed: {total}")


if __name__ == '__main__':
    main()
