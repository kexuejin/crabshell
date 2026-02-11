# CrabShell GUI (Tauri + React)

Desktop application for the CrabShell APK/AAB hardening tool.

## Tech Stack

- Tauri 2 (Rust backend)
- React + TypeScript + Vite (frontend)
- Material UI

## Features

- Select APK/AAB input file
- Configure output path and output format (APK/AAB/Auto)
- Configure signing (debug or custom keystore)
- Configure advanced packer flags (keep class/prefix/lib, encrypt assets, skip build/sign)
- Start/cancel hardening process
- Real-time progress and log events from backend process

## Development

### Prerequisites

- Node.js 18+
- Rust toolchain
- Python 3.10+
- Tauri system dependencies (platform-specific)

### Install

```bash
npm install
```

### Run Dev

```bash
npm run dev
```

### Build App

```bash
npm run build
```

This project uses a stable two-step packaging flow:

1. `npm run build:app` (Tauri builds `.app` bundle)
2. `npm run build:dmg` (custom `hdiutil` script builds `.dmg`)

If you only need the app bundle:

```bash
npm run build:app
```

## Architecture

- `src/renderer`: React UI
- `src/renderer/api/tauri.ts`: frontend ↔ backend bridge (`invoke`/`listen`)
- `src/shared/types.ts`: shared TypeScript types
- `src-tauri/src/main.rs`: Tauri commands + Python subprocess orchestration

## Notes

Old Electron implementation is intentionally removed and no longer maintained.


## Managed Toolchain

`pack.py` now prefers a managed toolchain directory to reduce host environment dependency:

- Default path: `$CODEX_HOME/tools/crabshell-toolchain`
- Override: `CRABSHELL_TOOLCHAIN_DIR=/custom/path`

Managed artifacts:

- `bundletool-<version>.jar` (auto-download)
- `apktool-<version>.jar` (auto-download when `apktool` binary missing)
- `uber-apk-signer-<version>.jar` (auto-download fallback when `apksigner` unavailable)

Signing behavior:

- First choice: `apksigner` (managed path / PATH / Android SDK build-tools)
- Fallback: `uber-apk-signer` via managed Java runtime discovery
- Debug keystore can auto-fallback to temp directory when `~/.android` is not writable
