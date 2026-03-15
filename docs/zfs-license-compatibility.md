# ZFS License Compatibility on HAOS / aarch64

> **TL;DR** — ZFS (CDDL) cannot use `EXPORT_SYMBOL_GPL` symbols. On Linux ≥ 6.2
> aarch64, the Raspberry Pi Foundation kernel marks `kernel_neon_begin/end` as
> GPL-only. This project auto-detects the conflict at build time and builds ZFS
> without NEON if needed. All ZFS functionality is preserved; only hardware-
> accelerated AES-NI / SHA is disabled.

---

## Background: CDDL vs. GPL symbol visibility

The Linux kernel's `EXPORT_SYMBOL_GPL()` macro restricts a symbol to modules
that declare a GPL-compatible license. OpenZFS is licensed under the **Common
Development and Distribution License 1.0 (CDDL)**, which is incompatible with
GPL. When the kernel `modpost` tool links a CDDL module against a
GPL-only symbol it produces a hard build error:

```
ERROR: modpost: GPL-incompatible module zfs.ko uses GPL-only symbol 'kernel_neon_begin'
```

---

## Timeline of the aarch64 NEON problem

| Kernel version | `kernel_neon_begin` export | Effect on ZFS |
|---|---|---|
| ≤ 6.1 | `EXPORT_SYMBOL` | ✅ ZFS builds normally with NEON |
| ≥ 6.2 | `EXPORT_SYMBOL_GPL` | ❌ Build fails unless NEON disabled |

The change was introduced in `arch/arm64/kernel/fpsimd.c` in mainline Linux 6.2.
The Raspberry Pi Foundation downstream kernel (`rpi-6.6.y`, used by HAOS on all
RPi boards and the Home Assistant Yellow CM4) follows the mainline change.

Upstream tracking: **openzfs/zfs#15401** (closed), fix landed in **openzfs/zfs PR #15711**
(merged into `zfs-2.2-release` branch in 2023-Q4).

---

## What happens at build time in this project

```
build_zfs.sh
    │
    ├─ Step 1: Clone OpenZFS at configured ref (zfs-2.2-release)
    │
    ├─ Step 2: probe_gpl_symbols.sh  ◄── key step
    │       │
    │       ├─ Method 1: parse Module.symvers   (most accurate)
    │       ├─ Method 2: grep fpsimd.c source   (fallback)
    │       └─ Method 3: kernel version ≥ 6.2?  (last resort)
    │           │
    │           ├─ Exit 0: symbols are NOT GPL-only → USE_SAFE_MODE=0
    │           ├─ Exit 1: GPL conflict detected  → USE_SAFE_MODE=1
    │           └─ Exit 2: inconclusive           → USE_SAFE_MODE=1 (fail-safe)
    │
    ├─ Step 3: ./configure
    │       ├─ Normal:    ./configure --with-config=kernel
    │       └─ Safe mode: ./configure --with-config=kernel --without-neon
    │                      + patch zfs_config.h: #undef HAVE_KERNEL_NEON
    │                      + EXTRA_CFLAGS: -DZFS_NO_TRACEPOINTS
    │
    └─ Step 4: make modules → collect *.ko
```

---

## The two root-cause symbols

### 1. `kernel_neon_begin` / `kernel_neon_end`

Used by ZFS's `icp` (Illumos Crypto Provider) module for AES acceleration
using ARM NEON instructions.  With `--without-neon` (or `#undef HAVE_KERNEL_NEON`),
ZFS's configure system falls back to a portable C implementation of AES-256-GCM,
AES-256-CCM, SHA-256, and SHA-512.

**Performance impact:** ~20–30% slower encryption/decryption for
`aes-256-gcm` / `aes-256-ccm` encryption-at-rest. Other ZFS operations
(COW, checksumming with SHA-256, compression) are not significantly affected
because SHA uses different code paths.

### 2. `bpf_trace_run*` / `trace_event_*`

ZFS includes DTrace-style tracepoints (`zfs_dbgmsg`, `zpl_*` trace macros).
When the kernel has `CONFIG_BPF_SYSCALL=y` (RPi kernels do), these tracepoints
generate references to BPF tracing symbols that are also `EXPORT_SYMBOL_GPL`.

Fix: compile with `-DZFS_NO_TRACEPOINTS` — the tracepoint stubs become no-ops.
This only affects kernel-level ZFS debug/tracing; it has no effect on user-space
`zpool`, `zfs`, or `libzpool`.

---

## Why not just change the ZFS license to GPL?

The CDDL was chosen by Sun/Oracle for ZFS and is the official OpenZFS license.
Changing it would require approval from all copyright holders across 20+ years
of development — not practical. The OpenZFS project's position (and the legal
consensus) is that CDDL and GPL are **license-incompatible** but **not
inherently incompatible in a binary distribution context** — they can coexist
in a system image as separate modules, as long as no CDDL module directly links
against GPL-only symbols at the kernel level.

---

## Future: when will NEON be re-enabled on RPi?

There are two paths forward:

1. **Raspberry Pi Foundation reverts the export change** — unlikely, as it
   follows mainline behavior.

2. **OpenZFS adds a pure-C NEON abstraction layer** that avoids calling the
   GPL-only entrypoints — tracked in the ZFS project; not yet merged.

When either happens, `probe_gpl_symbols.sh` will automatically detect the
improvement and the next HAOS build for RPi boards will switch back to full
NEON mode with no code changes required in this project.

---

## Verification

To confirm which mode was used for a particular build, inspect the
`build_info_{version}_{board}.json` asset in the GitHub Release:

```json
{
  "haos_version": "17.1",
  "board":        "rpi4_64",
  "arch":         "aarch64",
  "kernel_version": "6.6.31-v8-haos",
  "zfs_ref":      "zfs-2.2-release",
  "zfs_safe_mode": "false",   ← "false" = full NEON; "true" = safe mode
  "built_at":     "2026-03-15T06:42:17Z"
}
```

To verify manually on a loaded module:

```bash
# Check whether the NEON module was linked (should NOT appear in safe mode):
modinfo /lib/modules/$(uname -r)/extra/icp.ko | grep depends
# In normal mode: depends: spl,zcommon,kernel_neon (or similar)
# In safe mode:   depends: spl,zcommon  (no neon dependency)

# Check vermagic
modinfo /lib/modules/$(uname -r)/extra/zfs.ko | grep vermagic
```
