#!/usr/bin/env python3
import json, sys

d = json.load(open(sys.argv[1]))
s = d['stats']
print('== Stats ==')
for k, v in s.items():
    print(f'  {k}: {v}')
print(f'  lancet_hooks: {len(d.get("lancet_hooks", []))}')
print(f'  dpatch_files: {len(d.get("dpatch_files", []))}')

# Summary line for quick reading
changes = s.get('logical_change', 0)
added = s.get('only_modded', 0)
print(f'\n→ {changes} files modified, {added} files added in clean APK')
