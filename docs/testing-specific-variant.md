# Testing a Specific Workflow Variant Locally

This guide explains how to reproduce a single `(version, board)` build matrix
entry locally, without triggering the full GitHub Actions workflow.

---

## Prerequisites

- Linux host (Ubuntu 22.04 recommended; also works in Docker)
- `git`, `make`, `python3 >= 3.10`, `gcc-aarch64-linux-gnu` (for aarch64 builds)
- ~20 GB free disk space (Buildroot + kernel)
- `pip install -r requirements.txt`

---

## Step 1 — Generate the matrix locally

```bash
# Detect what needs building (requires GITHUB_TOKEN for rate-limit)
export GITHUB_TOKEN=ghp_...

python3 scripts/check_releases.py \
    --haos-repo home-assistant/operating-system \
    --this-repo dianlight/hasos_more_modules \
    --output missing_versions.json

# Or force a specific version:
python3 scripts/check_releases.py \
    --haos-repo home-assistant/operating-system \
    --this-repo dianlight/hasos_more_modules \
    --output missing_versions.json \
    --force-version 17.1

# Build the matrix
python3 scripts/build_matrix.py \
    --missing missing_versions.json \
    --modules config/modules.json \
    --output  matrix.json

cat matrix.json   # inspect the entries
```

---

## Step 2 — Pick one matrix entry

Each entry in `matrix.json > include[]` corresponds to a single CI job.
Pick the one you want to test, e.g.:

```json
{
  "version":        "17.1",
  "board":          "rpi4_64",
  "arch":           "aarch64",
  "kernel_arch":    "arm64",
  "defconfig":      "rpi4_defconfig",
  "cross_compile":  "aarch64-buildroot-linux-musl-",
  "has_zfs":        true,
  "has_soft_neon":  true,
  "zfs_modules":    ["avl","nvpair","unicode","zcommon","lua","icp","zstd","zfs"]
}
```

Export the relevant variables:

```bash
export HAOS_VERSION=17.1
export BOARD=rpi4_64
export ARCH=aarch64
export CROSS_COMPILE=aarch64-buildroot-linux-musl-
```

---

## Step 3 — Checkout HAOS at the target version

```bash
git clone \
    --branch "${HAOS_VERSION}" \
    --depth 1 \
    https://github.com/home-assistant/operating-system \
    haos
cd haos
git submodule update --init --recursive
```

---

## Step 4 — Configure Buildroot

```bash
# Inside the haos/ checkout:
make BR2_EXTERNAL=../ha-build O=output "${BOARD}_defconfig"
```

> **Tip:** Set `BR2_DL_DIR` to a shared location to cache downloads across runs:
> ```bash
> mkdir -p ~/buildroot-dl
> echo 'BR2_DL_DIR="/home/$(whoami)/buildroot-dl"' >> output/.config
> ```

---

## Step 5 — Build the kernel (headers + module support files only)

```bash
# Build just enough to support out-of-tree module compilation:
make -C output linux-rebuild

# The goal is to produce:
#   output/build/linux-*/Module.symvers   <- needed by probe_gpl_symbols.sh
#   output/build/linux-*/include/         <- kernel headers
#   output/build/linux-*/scripts/         <- module build infrastructure
```

Expected duration: **10–40 minutes** depending on your machine.
Subsequent runs are faster because of Buildroot's incremental build.

---

## Step 6 — Patch the kernel config

```bash
# From repo root (not inside haos/):
KCONFIG=$(find haos/output/build/linux-* -name .config -maxdepth 1 | head -1)

KERNEL_CONFIG="$KCONFIG" \
TARGET_ARCH="${ARCH}" \
TARGET_BOARD="${BOARD}" \
REPO_ROOT="$(pwd)" \
bash scripts/patch_config.sh "$KCONFIG" "${ARCH}" "${BOARD}" \
    | tee patch_result.json
```

---

## Step 7 — Probe GPL symbols (ZFS only)

```bash
LINUX_DIR=$(find haos/output/build/linux-* -maxdepth 0 -type d | head -1)

ARCH="${ARCH}" VERBOSE=1 \
bash scripts/probe_gpl_symbols.sh "$LINUX_DIR" "$LINUX_DIR"
echo "Probe exit code: $?"
# 0 = safe (full NEON build)
# 1 = GPL conflict (safe mode, no NEON)
# 2 = inconclusive (treated as unsafe)
```

---

## Step 8 — Build ZFS modules (if applicable)

```bash
mkdir -p output_modules

ZFS_REF=$(python3 -c "import json; print(json.load(open('config/modules.json'))['zfs_build']['ref'])")

VERBOSE=1 \
BOARD="${BOARD}" \
bash scripts/build_zfs.sh \
    --linux-dir    "$LINUX_DIR" \
    --linux-obj    "$LINUX_DIR" \
    --output-dir   output_modules \
    --arch         "${ARCH}" \
    --cross-compile "${CROSS_COMPILE}" \
    --zfs-ref      "$ZFS_REF" \
    --board        "${BOARD}" \
    --jobs         "$(nproc)"

ls -lh output_modules/
```

---

## Step 9 — Verify the built modules

```bash
# Check vermagic of each .ko against the running kernel
for ko in output_modules/*.ko; do
    echo "--- $ko ---"
    "${CROSS_COMPILE}objdump" -s --section=.modinfo "$ko" \
        | grep -A1 'vermagic\|name\|license' || true
done

# Or use modinfo if you have access to the target system:
# modinfo output_modules/zfs.ko
```

---

## Using Docker for a clean environment

```bash
docker run --rm -it \
    -v "$(pwd):/work" \
    -w /work \
    ubuntu:22.04 \
    bash -c "
        apt-get update -qq &&
        apt-get install -y --no-install-recommends \
            build-essential bc bison flex libssl-dev libelf-dev \
            libncurses-dev cpio rsync wget unzip git python3 python3-pip \
            gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu gawk file &&
        pip3 install -r requirements.txt &&
        export HAOS_VERSION=17.1 BOARD=rpi4_64 ARCH=aarch64 &&
        export CROSS_COMPILE=aarch64-linux-gnu- &&
        bash docs/testing-specific-variant.md  # not executable, just reference
    "
```

---

## Troubleshooting

### `ERROR: modpost: GPL-incompatible module zfs.ko uses GPL-only symbol`

The GPL probe missed the conflict. Force safe mode manually:

```bash
VERBOSE=1 BOARD="${BOARD}" \
bash scripts/build_zfs.sh ... \
    # build_zfs.sh will detect and switch to safe mode automatically.
    # If it doesn't, check that Module.symvers exists in LINUX_DIR.
```

### `Invalid module format` when loading

The `vermagic` of the compiled `.ko` doesn't match the running kernel.
Make sure you checked out the **exact** HAOS version (`uname -r` output
must match `modinfo mymodule.ko | grep vermagic`).

### Buildroot `make` fails with `No rule to make target`

You may be using a Buildroot defconfig name that changed between HAOS
versions. Check `haos/buildroot-external/configs/` for the actual filename:

```bash
ls haos/buildroot-external/configs/ | grep rpi
```

---

## Quick Reference

| Script | Purpose |
|--------|---------|
| `scripts/check_releases.py` | Detect HAOS versions needing builds |
| `scripts/build_matrix.py`   | Generate CI matrix JSON |
| `scripts/patch_config.sh`   | Enable CONFIG_* symbols in kernel config |
| `scripts/probe_gpl_symbols.sh` | Detect GPL-only NEON symbols |
| `scripts/build_zfs.sh`      | Build OpenZFS out-of-tree modules |
| `scripts/modules_config.py` | Shared library for reading modules.json |
| `scripts/update_readme_modules.py` | Regenerate README module table |
