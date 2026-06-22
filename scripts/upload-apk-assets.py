#!/usr/bin/env python3
"""upload-apk-assets.py — Upload official and modded APKs as GitHub Release assets.

Usage:
  python3 upload-apk-assets.py --official /path/to/official.apk --modded /path/to/modded.apk

This stores APKs as release assets so GHA workflows can download them without
relying on external CDNs.
"""

import argparse, os, subprocess, sys, hashlib

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--official', required=True, help='Official APK path')
    parser.add_argument('--modded', required=True, help='Modded APK path')
    args = parser.parse_args()

    token = os.environ.get('GITHUB_TOKEN') or open(os.path.expanduser('~/.github-token')).read().strip()
    repo = 'callacat/fanqie-clean-builder'

    # Get or create release
    tag = 'apk-assets'
    r = subprocess.run([
        'curl', '-s', '-H', f'Authorization: token {token}',
        f'https://api.github.com/repos/{repo}/releases/tags/{tag}'
    ], capture_output=True, text=True)

    import json
    release = json.loads(r.stdout)
    if 'id' not in release:
        print(f'Creating release {tag}...')
        r = subprocess.run([
            'curl', '-s', '-X', 'POST', '-H', f'Authorization: token {token}',
            '-H', 'Content-Type: application/json',
            f'https://api.github.com/repos/{repo}/releases',
            '-d', json.dumps({'tag_name': tag, 'name': tag, 'prerelease': True})
        ], capture_output=True, text=True)
        release = json.loads(r.stdout)
        if 'id' not in release:
            print(f'FAILED: {release}')
            sys.exit(1)

    release_id = release['id']

    for label, path in [('official', args.official), ('modded', args.modded)]:
        name = os.path.basename(path)
        h = sha256(path)
        size = os.path.getsize(path)

        print(f'Uploading {label}: {name} ({size/1024/1024:.1f} MB) SHA256: {h}')

        r = subprocess.run([
            'curl', '-s', '-X', 'POST', '-H', f'Authorization: token {token}',
            f'https://uploads.github.com/repos/{repo}/releases/{release_id}/assets',
            '-H', f'Content-Type: application/vnd.android.package-archive',
            '--data-binary', f'@{path}',
            '-G', '--data-urlencode', f'name={name}'
        ], capture_output=True, text=True)

        result = json.loads(r.stdout)
        if 'id' in result:
            print(f'  ✅ Uploaded: {result["browser_download_url"]}')
        else:
            print(f'  ❌ Failed: {result}')

if __name__ == '__main__':
    main()
