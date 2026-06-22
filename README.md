# Fanqie Novel Clean Builder

Build a clean, ad-free, anti-ban version of 番茄免费小说 (Fanqie Novel) from the official APK.

## Pipeline

```
Official APK + Modded APK → Smali Diff Harvester → Patch & Debloat → Build & Sign → Emulator Verify
```

## How it works

1. **Content-hash pairing**: Compares official vs modded smali files by SHA256 (not by path)
2. **Smart patching**: Extracts only logical changes (signature spoofing, device fingerprinting)
3. **Ad removal**: Removes LuckyCat, full push alliance, stubs Pangle SDK init
4. **Emulator verification**: Installs on Android emulator and checks for crashes/hook loading

## Usage

Trigger the GHA workflow with:
```bash
gh workflow run clean-build.yml
```

Or dispatch via GitHub UI → Actions → Fanqie Clean Build Pipeline → Run workflow.

## Dependencies

- apktool 3.0.2
- JDK 17
- Python 3
- Android SDK (for emulator verification)
