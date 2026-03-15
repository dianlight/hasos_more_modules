# haos\_more\_modules

> **Note:** this project is community-maintained and is not affiliated with Nabu Casa / official Home Assistant.
>
> **Warning:** installing custom kernel modules on HAOS is **unsupported** and may lead to system instability or security issues. Use at your own risk.
>
> **Alert:** the modules provided by this project are compiled with the same configuration as the official HAOS releases, but they are **not** signed with the HAOS private key. This means that they can be loaded on HAOS, but they will not be loaded automatically at boot and may require manual intervention to load.
>
> **Disclaimer:** the modules provided by this project are intended for advanced users who understand the risks and implications of installing custom kernel modules on HAOS. The maintainers of this project are not responsible for any issues that may arise from using these modules.
>
> **Very Big Alert:** the project is created and maintained with a heavy use of AI tools (GitHub Copilot, ChatGPT, etc.) to automate the generation of code and documentation. While this allows for rapid development and updates, it may also introduce errors or inconsistencies. Users are encouraged to review the code and documentation carefully before use.

Extra kernel modules for **Home Assistant OS (HAOS)** – automatically compiled for every new release.

Supported architectures: **x86\_64** and **aarch64** (Odroid, Raspberry Pi, Home Assistant Yellow).

---

## Table of Contents

- [hasos\_more\_modules](#hasos_more_modules)
  - [Table of Contents](#table-of-contents)
  - [Available modules](#available-modules)
  - [Scope of the project](#scope-of-the-project)
  - [How the project works](#how-the-project-works)
  - [Installing modules on HAOS (Unsupported)](#installing-modules-on-haos-unsupported)
    - [Prerequisites](#prerequisites)
    - [Step 1 – Download the module](#step-1--download-the-module)
    - [Step 2 – Upload the module to the system](#step-2--upload-the-module-to-the-system)
    - [Step 3 – Remount `/` as read-write](#step-3--remount--as-read-write)
    - [Step 4 – Load the module](#step-4--load-the-module)
  - [Making modules persistent](#making-modules-persistent)
    - [Directory structure](#directory-structure)
    - [Startup script](#startup-script)
  - [Warning about Kernel Version Magic](#warning-about-kernel-version-magic)
  - [Local development](#local-development)
    - [Requirements](#requirements)
    - [Check for missing releases](#check-for-missing-releases)
    - [Add a new module](#add-a-new-module)
    - [Test the configuration patch](#test-the-configuration-patch)
    - [Regenerate README module table](#regenerate-readme-module-table)
  - [Testing a specific workflow variant locally](#testing-a-specific-workflow-variant-locally)
  - [Repository structure](#repository-structure)
  - [License](#license)

---

## Available modules

<!-- MODULE_TABLE_START -->

The table below is generated automatically from `config/modules.json`.

Legend:
✅ Built normally · ⚠️ Built in **safe mode** (no NEON AES acceleration — auto-detected at build time when `kernel_neon_begin` is `EXPORT_SYMBOL_GPL`) · ❌ Not available (hard exclusion)

| Module | Description | License | x86_64 | odroid-c4 | odroid-n2 | rpi3 | rpi4 | rpi5 | yellow | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `xfs.ko` | XFS filesystem support | GPL-2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| `nfsd.ko` | NFS server daemon | GPL-2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| `nfs.ko` | NFS client support | GPL-2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| `quic.ko` | QUIC transport (RFC 9000) – from lxin/quic | GPL-2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| `avl.ko` | ZFS AVL tree library – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: built in **safe mode** (no NEON AES acceleration) when `kernel_neon_begin` is `EXPORT_SYMBOL_GPL` — detected automatically at build time. |
| `icp.ko` | ZFS ICP (Illumos Crypto Provider) – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `lua.ko` | ZFS Lua scripting engine – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `nvpair.ko` | ZFS name-value pair library – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `unicode.ko` | ZFS Unicode support – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `zcommon.ko` | ZFS common library – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `zstd.ko` | ZFS Zstandard compression – from openzfs/zfs | CDDL AND BSD-3 | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: same as above. |
| `zfs.ko` | ZFS filesystem support – from openzfs/zfs | CDDL | ✅ | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ On `rpi3`, `rpi4`, `rpi5`, `yellow`: built in **safe mode** (no NEON AES acceleration) when `kernel_neon_begin` is `EXPORT_SYMBOL_GPL` — detected automatically at build time. |

> **About ⚠️ safe mode (ZFS on RPi / Yellow)**
>
> ZFS is licensed as CDDL. On Linux ≥ 6.2 / aarch64 (Raspberry Pi Foundation
> kernel tree), `kernel_neon_begin` and `kernel_neon_end` are exported as
> `EXPORT_SYMBOL_GPL`, which makes them inaccessible to CDDL modules.
>
> The build system runs `scripts/probe_gpl_symbols.sh` against the target
> kernel's `Module.symvers` at compile time:
>
> - If the symbols are **not** GPL-only → ZFS is built normally with NEON acceleration (AES-NI, SHA extensions).
> - If they **are** GPL-only → ZFS is built with `--without-neon` and `-DZFS_NO_TRACEPOINTS`. All functionality is preserved; only hardware crypto acceleration is disabled (≈ 20–30% slower for AES-heavy workloads).
>
> The `build_info_{version}_{board}.json` asset in each release records `"zfs_safe_mode": true/false` so you can verify which mode was used.
>
> See [`docs/zfs-license-compatibility.md`](docs/zfs-license-compatibility.md) for a full technical explanation.

<!-- MODULE_TABLE_END -->

---

## Scope of the project

This project provides **pre-compiled kernel modules** for Home Assistant OS (HAOS) that are not included in the official HAOS releases. The modules are compiled for each HAOS release and made available as assets in the GitHub Releases of this repository.

The primary use is by [SambaNAS2](https://github.com/dianlight/hassio-addons) (add-on) to provide support for the XFS filesystem and NFS server/client capabilities on HAOS. However, the modules can be used for any purpose that requires them.

---

## How the project works

```
┌─────────────────────────────────────────────────────────┐
│  GitHub Actions (.github/workflows/main_build.yml)      │
│                                                         │
│  1. check_releases.py                                   │
│     └─ compares HAOS releases with already-built        │
│        assets; outputs missing_versions.json            │
│                                                         │
│  2. build_matrix.py                                     │
│     └─ generates CI matrix: one job per                 │
│        (version, board) pair                            │
│                                                         │
│  3. Per-job: configure Buildroot + build kernel         │
│     └─ patch_config.sh enables CONFIG_* symbols         │
│                                                         │
│  4. Per-job: probe_gpl_symbols.sh  ← NEW                │
│     └─ detects kernel_neon_begin GPL-only status        │
│        → sets safe_mode flag for ZFS                    │
│                                                         │
│  5. Per-job: build in-tree modules                      │
│     └─ make linux-rebuild → *.ko (xfs, nfs, nfsd, …)   │
│                                                         │
│  6. Per-job: build_zfs.sh (out-of-tree)  ← NEW         │
│     └─ builds OpenZFS modules with auto NEON fallback   │
│        safe_mode=0: full NEON + tracepoints             │
│        safe_mode=1: --without-neon, -DZFS_NO_TRACEPOINTS│
│                                                         │
│  7. GitHub Release                                      │
│     └─ uploads {mod}_{ver}_{arch}.ko + build_info.json  │
└─────────────────────────────────────────────────────────┘
```

The workflow runs:

- **Automatically** every day at 06:00 UTC (cron).
- **Manually** from the *Actions* tab of the repository.
- **Via API** with a `repository_dispatch` event of type `build-modules`.

---

## Installing modules on HAOS (Unsupported)

### Prerequisites

- SSH access enabled on HAOS (see *Settings → System → SSH Access*).
- HAOS version matching the module to install.

### Step 1 – Download the module

Download the `.ko` file matching your version and architecture from the
[Releases](https://github.com/dianlight/hasos_more_modules/releases) page.

Example: `xfs_17.1_x86_64.ko` or `zfs_17.1_aarch64.ko`.

> **RPi/Yellow note:** ZFS modules built in safe mode are functionally equivalent to
> the normal build. The filename is the same — check `build_info_*.json` in the release
> assets if you need to confirm safe vs. normal mode.

### Step 2 – Upload the module to the system

```bash
scp xfs_17.1_x86_64.ko root@homeassistant.local:/tmp/
```

### Step 3 – Remount `/` as read-write

```bash
mount -o remount,rw /
mkdir -p /lib/modules/$(uname -r)/extra
cp /tmp/xfs_17.1_x86_64.ko /lib/modules/$(uname -r)/extra/xfs.ko
depmod -a
```

### Step 4 – Load the module

```bash
modprobe xfs
# or
insmod /lib/modules/$(uname -r)/extra/xfs.ko
```

**ZFS requires loading sub-modules in dependency order:**

```bash
for mod in spl avl nvpair unicode zcommon lua icp zstd zfs; do
    modprobe "$mod" && echo "  ✓ $mod" || echo "  ✗ $mod"
done
```

---

## Making modules persistent

### Directory structure

```
/mnt/data/
└── modules/
    └── <kernel-version>/
        └── extra/
            ├── xfs.ko
            ├── zfs.ko
            └── ...
```

### Startup script

Create `/mnt/data/modules/load_modules.sh`:

```bash
#!/bin/sh
# Load extra modules at HAOS boot.

KERNEL_VER=$(uname -r)
MODULE_DIR="/mnt/data/modules/${KERNEL_VER}/extra"

if [ ! -d "${MODULE_DIR}" ]; then
    echo "[haos_more_modules] Module directory not found: ${MODULE_DIR}"
    exit 0
fi

mount -o remount,rw /
mkdir -p "/lib/modules/${KERNEL_VER}/extra"
cp "${MODULE_DIR}"/*.ko "/lib/modules/${KERNEL_VER}/extra/" 2>/dev/null || true
depmod -a
mount -o remount,ro /

# Load in dependency order (ZFS sub-modules first)
for mod in spl avl nvpair unicode zcommon lua icp zstd zfs xfs nfsd; do
    modprobe "${mod}" 2>/dev/null && \
        echo "[haos_more_modules] Module ${mod} loaded." || \
        echo "[haos_more_modules] Module ${mod} not found or already built-in."
done
```

---

## Warning about Kernel Version Magic

Linux kernel modules embed a **version magic** string that must exactly match
the running kernel:

```bash
uname -r                             # running kernel version
modinfo xfs.ko | grep vermagic       # module's expected kernel
```

If they do not match, loading fails with `Invalid module format`.
After every HAOS update you must replace modules with the versions built for
the new kernel version.

---

## Local development

### Requirements

- Python ≥ 3.10
- `pip install -r requirements.txt`
- `gcc-aarch64-linux-gnu` (for aarch64 cross-builds)

### Check for missing releases

```bash
export GITHUB_TOKEN=ghp_...   # optional, increases rate-limit

python3 scripts/check_releases.py \
    --haos-repo home-assistant/operating-system \
    --this-repo dianlight/hasos_more_modules \
    --output missing_versions.json
```

### Add a new module

Edit `config/modules.json` and add an entry:

```json
{
  "name": "mymod",
  "description": "My new module",
  "kconfig": ["CONFIG_MYMOD"],
  "license": "GPL-2.0"
}
```

For external (out-of-tree) modules, add a `source` block and implement
a build step in the workflow.

### Test the configuration patch

```bash
cp /boot/config-$(uname -r) /tmp/test.config

KERNEL_CONFIG=/tmp/test.config \
TARGET_ARCH=x86_64 \
TARGET_BOARD=x86_64 \
REPO_ROOT=$(pwd) \
bash scripts/patch_config.sh /tmp/test.config x86_64 x86_64

grep -E "CONFIG_XFS|CONFIG_NFSD|CONFIG_MODULES" /tmp/test.config
```

### Regenerate README module table

```bash
python3 scripts/update_readme_modules.py
# Or dry-run (print without modifying):
python3 scripts/update_readme_modules.py --dry-run
```

---

## Testing a specific workflow variant locally

See [`docs/testing-specific-variant.md`](docs/testing-specific-variant.md) for
step-by-step instructions to reproduce a single `(version, board)` CI build
on your local machine.

---

## Repository structure

```
hasos_more_modules/
├── .github/
│   └── workflows/
│       └── main_build.yml          # Main CI/CD workflow
├── config/
│   └── modules.json                # Single source of truth for modules, boards, ZFS config
├── docs/
│   ├── testing-specific-variant.md # Local build guide
│   └── zfs-license-compatibility.md# CDDL/GPL technical deep-dive
├── scripts/
│   ├── check_releases.py           # HAOS missing-release detection
│   ├── build_matrix.py             # GitHub Actions matrix generator  ← NEW
│   ├── modules_config.py           # Shared library for modules.json  ← REFACTORED
│   ├── patch_config.sh             # kernel.config patch
│   ├── probe_gpl_symbols.sh        # GPL-only symbol detector         ← NEW
│   ├── build_zfs.sh                # Out-of-tree ZFS build            ← NEW
│   └── update_readme_modules.py    # Regenerates README module table
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```

---

## License

This project is distributed under the **MIT** license.
See the [LICENSE](LICENSE) file for full details.

The kernel modules themselves retain their original licenses:
- In-tree modules (`xfs`, `nfs`, `nfsd`): GPL-2.0 (same as the kernel)
- OpenZFS modules (`zfs`, `icp`, etc.): CDDL-1.0
- QUIC module (`quic`): GPL-2.0
