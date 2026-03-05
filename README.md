# hasos_more_modules

> **Note:** this project is community-maintained and is not affiliated with Nabu Casa / official Home Assistant.

Extra kernel modules for **Home Assistant OS (HAOS)** – automatically compiled for every new release.

Available modules:

| Module | Description |
| :------- | :------------ |
| `xfs.ko` | XFS filesystem support |
| `nfs.ko` | NFS client (Network File System) |
| `nfsd.ko` | NFS server daemon |

Supported architectures: **x86_64** (OVA / generic x86-64) and **aarch64** (Raspberry Pi 4 / ARM 64-bit).

---

## Table of Contents

1. [How the project works](#how-the-project-works)
2. [Installing modules on HAOS](#installing-modules-on-haos)
3. [Making modules persistent](#making-modules-persistent)
4. [Warning about Kernel Version Magic](#warning-about-kernel-version-magic)
5. [Local development](#local-development)
6. [Repository structure](#repository-structure)

---

## How the project works

```text
┌─────────────────────────────────────┐
│  GitHub Actions (main_build.yml)    │
│                                     │
│  1. check_releases.py               │
│     └─ compares HAOS releases       │
│        with already-built assets    │
│                                     │
│  2. patch_config.sh                 │
│     └─ modifies kernel.config       │
│        to enable modules as =m      │
│                                     │
│  3. make linux-modules              │
│     └─ compiles only .ko modules    │
│                                     │
│  4. GitHub Release                  │
│     └─ uploads .ko assets named     │
│        {mod}_{ver}_{arch}.ko        │
└─────────────────────────────────────┘
```

The workflow runs:

- **Automatically** every day at 06:00 UTC (cron).
- **Manually** from the *Actions* tab of the repository.
- **Via API** with a `repository_dispatch` event of type `build-modules`.

---

## Installing modules on HAOS

### Prerequisites

- SSH access enabled on HAOS (see *Settings → System → SSH Access*).
- HAOS version matching the module to install.

### Step 1 – Download the module

Download the `.ko` file matching your version and architecture from the
[Releases](../../releases) page of this repository.  
Example: `xfs_13.2_x86_64.ko`.

### Step 2 – Upload the module to the system

```bash
# Copy the file to the system (from an SSH terminal)
scp xfs_13.2_x86_64.ko root@homeassistant.local:/tmp/
```

### Step 3 – Remount `/` as read-write

HAOS mounts the system partition (`/`) as **read-only** to ensure its
integrity. Before copying the module to its final location you need to
remount it as read-write:

```bash
# Remount / as read-write
mount -o remount,rw /

# Create the modules directory if it doesn't exist
mkdir -p /lib/modules/$(uname -r)/extra

# Copy the module
cp /tmp/xfs_13.2_x86_64.ko /lib/modules/$(uname -r)/extra/xfs.ko

# Update the module database
depmod -a
```

### Step 4 – Load the module

```bash
modprobe xfs        # load the module (and its dependencies)
# or
insmod /lib/modules/$(uname -r)/extra/xfs.ko
```

To verify that the module was loaded correctly:

```bash
lsmod | grep xfs
dmesg | tail -20
```

> **Warning:** on the next update/reboot, HAOS remounts `/` as read-only
> and files copied to `/lib/modules` are removed. See the next section
> to make the module persistent.

---

## Making modules persistent

The recommended method is to use the `/mnt/data` partition, which **survives
HAOS updates**.

### Directory structure

```text
/mnt/data/
└── modules/
    └── <kernel-version>/
        └── extra/
            ├── xfs.ko
            ├── nfs.ko
            └── nfsd.ko
```

### Startup script

Create the file `/mnt/data/modules/load_modules.sh`:

```bash
#!/bin/sh
# Load extra modules at HAOS boot.

KERNEL_VER=$(uname -r)
MODULE_DIR="/mnt/data/modules/${KERNEL_VER}/extra"

if [ ! -d "${MODULE_DIR}" ]; then
    echo "[haos_more_modules] Module directory not found: ${MODULE_DIR}"
    exit 0
fi

# Copy modules to the system location
mount -o remount,rw /
mkdir -p "/lib/modules/${KERNEL_VER}/extra"
cp "${MODULE_DIR}"/*.ko "/lib/modules/${KERNEL_VER}/extra/" 2>/dev/null || true
depmod -a
mount -o remount,ro /

# Load modules
for mod in xfs nfs nfsd; do
    modprobe "${mod}" 2>/dev/null && \
        echo "[haos_more_modules] Module ${mod} loaded." || \
        echo "[haos_more_modules] Module ${mod} not found or already built-in."
done
```

### Integration with containers (Advanced SSH & Web Terminal Add-on)

If you use the *Advanced SSH & Web Terminal* add-on, you can add the command to
the `~/.profile` file or to a custom `s6-rc` service.

For a permanent integration you can use the
[AppDaemon](https://github.com/hassio-addons/addon-appdaemon) add-on or create
an S6 script in `/mnt/data/supervisor/addons/local/`.

---

## Warning about Kernel Version Magic

Linux kernel modules embed a string called **"version magic"** that must match
**exactly** the string of the running kernel.

```bash
# Show the version magic of the running kernel
uname -r

# Show the version magic of the module
modinfo xfs.ko | grep vermagic
```

If the two strings **do not match**, loading the module will fail with:

```text
ERROR: could not insert module xfs.ko: Invalid module format
```

**Practical implications:**

| Situation | Result |
| :---------- | :------- |
| Module compiled for HAOS 13.2, running on HAOS 13.2 | ✅ Works |
| Module compiled for HAOS 13.2, running on HAOS 13.1 | ❌ Fails |
| Module compiled for HAOS 13.2, running after an upgrade to 13.3 | ❌ Fails |

**Solution:** always download the module that matches **exactly** the installed
HAOS version. After every HAOS update you must replace the modules with the
version compiled for the new kernel.

---

## Local development

### Requirements

- Python ≥ 3.10
- `pip install -r requirements.txt`

### Check for missing releases

```bash
export GITHUB_TOKEN=ghp_...  # optional, increases API rate-limit

python3 scripts/check_releases.py \
    --haos-repo home-assistant/operating-system \
    --this-repo dianlight/hasos_more_modules
```

### Test the configuration patch

```bash
# Copy a sample kernel.config
cp /boot/config-$(uname -r) /tmp/test.config

bash scripts/patch_config.sh /tmp/test.config x86_64

# Verify the patched values
grep -E "CONFIG_MODULES|CONFIG_LOCALVERSION|CONFIG_XFS|CONFIG_NFS|CONFIG_EXPORTFS" \
    /tmp/test.config
```

---

## Repository structure

```text
hasos_more_modules/
├── .github/
│   └── workflows/
│       └── main_build.yml      # Main CI/CD workflow
├── scripts/
│   ├── check_releases.py       # HAOS missing-release detection
│   └── patch_config.sh         # kernel.config patch
├── .gitignore
├── LICENSE
├── README.md                   # This file
└── requirements.txt            # Python dependencies
```

---

## License

This project is distributed under the **MIT** license.  
See the [LICENSE](LICENSE) file for full details.
