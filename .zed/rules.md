# Project: hasos_more_modules

## Overview

Community-maintained project that automatically compiles extra Linux kernel
modules for **Home Assistant OS (HAOS)** on every new upstream release.

Supported modules: `xfs.ko` (XFS filesystem), `nfsd.ko` (NFS server),
`nfs.ko` (NFS client).  
Supported architectures: `x86_64` and `aarch64`.

---

## Repository structure

```text
hasos_more_modules/
├── .github/
│   └── workflows/
│       └── main_build.yml   # CI/CD pipeline (detect → build → release)
├── scripts/
│   ├── check_releases.py    # Detects HAOS versions not yet compiled
│   └── patch_config.sh      # Patches the kernel.config for module builds
├── .gitignore
├── .markdownlint.json
├── LICENSE                  # MIT
├── README.md
└── requirements.txt         # Python dev/type-check extras (stdlib-only runtime)
```

---

## Tech stack & tooling

| Layer | Technology |
| :--- | :--- |
| CI/CD | GitHub Actions (`ubuntu-24.04`) |
| Release detection | Python 3.10+ — stdlib only (`urllib`, `json`, `argparse`) |
| Kernel patching | Bash (`patch_config.sh`) |
| Build system | Buildroot + Linux `make linux-modules` |
| Cross-compilation | `gcc-x86-64-linux-gnu` / `gcc-aarch64-linux-gnu` |
| Release hosting | GitHub Releases (assets named `{mod}_{ver}_{board}.ko`) |

---

## Coding conventions

### Python (`scripts/check_releases.py`)

- Target **Python ≥ 3.10**; use `from __future__ import annotations` for
  forward-compatible type hints.
- **stdlib only** at runtime — do not add third-party imports without updating
  `requirements.txt` and clearly marking them as optional.
- Use `sys.stderr` for all diagnostic/log output; use `sys.stdout` only for
  machine-readable data (tags, versions) meant to be captured by the shell.
- Exit codes are meaningful: `0` = work to do, `1` = nothing to do,
  `2` = fatal error.
- Keep functions small and single-purpose with clear docstrings.
- Use `typing.Any` sparingly; prefer concrete types.

### Bash (`scripts/patch_config.sh`)

- Always start with `set -euo pipefail`.
- Prefix every log line with `[INFO]`, `[WARN]`, or `[ERROR]`.
- Helper functions must be clearly commented.
- Quote all variables (`"${VAR}"`).
- Avoid external commands when shell builtins suffice.

### GitHub Actions (`.github/workflows/main_build.yml`)

- Pin action versions with a full SHA or a `@vN` tag (e.g. `actions/checkout@v4`).
- Use `permissions` blocks scoped to the minimum needed (`contents: read` /
  `contents: write`).
- Use `concurrency` to prevent redundant parallel runs.
- Set `fail-fast: false` on matrix jobs so one failing board doesn't abort
  the rest.
- Capture multi-line shell outputs via `>> "$GITHUB_OUTPUT"`.
- Log verbosely (`echo "[INFO] ..."`) so CI runs are easy to audit.

---

## CI/CD pipeline — job order

1. **detect-boards** — queries the HAOS repo's `buildroot-external/configs/`
   to discover all `*_defconfig` files and outputs a JSON array of board names.
2. **detect-versions** — runs `check_releases.py` (or uses a manual input) to
   find HAOS versions not yet released; outputs a JSON array capped at
   `MAX_VERSIONS` (default `5`), sorted newest-first.
3. **build** — matrix job (`version × board`); clones HAOS, patches the kernel
   config, runs `make linux-modules`, and uploads `.ko` artifacts.
4. **release** — per-version job; downloads all artifacts and creates/updates a
   GitHub Release with the `.ko` files attached.

---

## Debugging

1. If a build fails, check the CI logs for any error messages.
2. Use `echo "[DEBUG] ..." >> "$GITHUB_OUTPUT"` to log debug messages that will be displayed in the CI run summary.
3. Use github MCP to investigate and debug any issues in the CI run.

---

## Naming conventions

- Release assets: `{module}_{haos_version}_{board}.ko`
  (e.g. `xfs_13.2_generic_x86_64.ko`).
- GitHub Release tags mirror HAOS version tags exactly (e.g. `13.2`).
- Pre-releases are detected by the presence of `b`, `rc`, or `dev` in the
  version string.

---

## External dependencies and references

1. Use the original [HASOS](https://github.com/home-assistant/operating-system) repository for information on board-specific kernel configurations.
2. Use buildroot for cross-compilation and kernel module building.

---

## Adding a new kernel module

1. Enable the relevant `CONFIG_*` symbols in `scripts/patch_config.sh` using
   `set_config_m`.
2. Add the module name to the `MODULE_NAMES` array in the **build** job of
   `main_build.yml`.
3. Update the release body template in the **release** job to document the new
   module.
4. Update the module table in `README.md`.

---

## Key constraints & gotchas

- **Version magic must match exactly.** A module compiled for HAOS 13.2 will
  fail on 13.1 or 13.3 with `Invalid module format`. Never mix versions.
- `CONFIG_LOCALVERSION` must be set to `"-haos"` to reproduce the exact version
  magic string of the running HAOS kernel.
- HAOS mounts `/` read-only; modules must be copied to `/mnt/data/` to survive
  updates.
- `check_releases.py` uses only the GitHub REST API with `urllib` — no
  `requests` or `PyGithub`. Keep it that way unless a strong reason arises.
- The workflow intentionally limits builds to `MAX_VERSIONS` per run to avoid
  exhausting GitHub Actions minutes on large backlogs.

---

## Environment variables used in CI

| Variable | Source | Purpose |
| :--- | :--- | :--- |
| `GITHUB_TOKEN` | Automatically injected / secret | GitHub API auth |
| `HAOS_REPO` | `env:` block | Source HAOS repository slug |
| `THIS_REPO` | `env:` block (`github.repository`) | This repo slug |
| `MAX_VERSIONS` | `env:` block | Max versions to build per run |

---

## Commit message style

Follow **Conventional Commits** with a **gitmoji** prefix:

```text
✨ feat(ci): add arm32 board support
🐛 fix(be): handle missing defconfig gracefully
📝 docs: update module installation instructions
```

Allowed types: `feat`, `fix`, `docs`, `ci`, `refactor`, `perf`, `test`,
`build`, `chore`, `revert`, `style`.  
Allowed scopes: `be`, `fe`, `doc`, `ci` (combine with `+`, e.g. `fe+doc`).
