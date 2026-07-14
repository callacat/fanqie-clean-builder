#!/usr/bin/env python3
"""build-and-sign.sh wrapper — Rebuild APK with apktool, sign with debug keystore.

Usage:
  bash build-and-sign.sh <apktool_project_dir> <output_apk_path>

Dependencies: apktool, keytool, jarsigner
"""

import subprocess, sys, os, shutil

def run(cmd, desc):
    print(f"[{desc}] {' '.join(cmd)}")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"FAIL: {desc}")
        sys.exit(r.returncode)
    return r

def main():
    # ponytail: memory check, add per-build profiling if builds still OOM
    import subprocess as _sp
    _mem_check = _sp.run(['bash', os.path.join(os.path.dirname(__file__), 'pre-build-check.sh')],
                          capture_output=True, text=True)
    print(_mem_check.stdout.strip())
    if _mem_check.returncode != 0:
        print("ERROR: Insufficient memory for build. Close other processes and retry.")
        sys.exit(1)

    project_dir = sys.argv[1] if len(sys.argv) > 1 else '_build/official'
    output_apk = sys.argv[2] if len(sys.argv) > 2 else 'fanqie-clean.apk'

    unsigned = output_apk.replace('.apk', '-unsigned.apk')
    aligned  = output_apk.replace('.apk', '-aligned.apk')
    keystore = 'debug.keystore'

    build_dir = os.path.dirname(output_apk) or '.'
    os.makedirs(build_dir, exist_ok=True)

    # Step 1: apktool build
    run(['apktool', 'b', project_dir, '-o', unsigned],
        'apktool build')

    # Step 2: Generate debug keystore if needed
    if not os.path.exists(keystore):
        run([
            'keytool', '-genkey', '-v', '-keystore', keystore,
            '-alias', 'debug', '-keyalg', 'RSA', '-keysize', '2048',
            '-validity', '10000', '-storepass', 'android', '-keypass', 'android',
            '-dname', 'CN=Debug,O=Clean,C=CN'
        ], 'generate debug keystore')

    # Step 3: zipalign (prefer SDK zipalign, fallback to none)
    zipalign = shutil.which('zipalign')
    if zipalign:
        run([zipalign, '-f', '-p', '4', unsigned, aligned], 'zipalign')
        sign_input = aligned
    else:
        print("[WARN] zipalign not found, skipping alignment")
        sign_input = unsigned

    # Step 4: sign
    run([
        'jarsigner', '-sigalg', 'SHA1withRSA', '-digestalg', 'SHA1',
        '-keystore', keystore, '-storepass', 'android',
        sign_input, 'debug'
    ], 'jarsigner sign')

    # Step 5: rename if needed
    if sign_input != output_apk:
        shutil.move(sign_input, output_apk)

    size = os.path.getsize(output_apk)
    print(f"\nDONE: {output_apk} ({size / 1024 / 1024:.1f} MB)")

if __name__ == '__main__':
    main()
