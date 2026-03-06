# Testing A Specific Workflow Variant Locally

This guide explains how to simulate one workflow matrix variant (for example `version=17.1` and `board=generic_aarch64`) using `act`.

## Why This Is Needed
`main_build.yml` builds its matrix dynamically from job outputs:
- `fromJson(needs.detect-versions.outputs.versions)`
- `fromJson(needs.detect-boards.outputs.boards)`

Current `act` versions may fail to parse this pattern during dry-run. The workaround is to use a temporary workflow copy with static matrix values.

## Prerequisites
- Docker running locally.
- `act` installed.
- Run commands from repository root.

## 1. Baseline Job Discovery
```bash
act -l
```

## 2. Attempt Full Dry-Run (Optional)
```bash
act workflow_dispatch \
  -W .github/workflows/main_build.yml \
  --container-architecture linux/amd64 \
  -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 \
  --dryrun
```

If this fails with matrix parsing errors, continue.

## 3. Create A Temporary Variant Workflow
This example simulates:
- `version=17.1`
- `board=generic_aarch64`

### Recommended: use helper script

```bash
bash scripts/create_static_matrix_variant.sh \
  --version 17.1 \
  --board generic_aarch64
```

The script prints the generated workflow path under `/tmp`.

### Manual fallback (without helper script)

```bash
cp .github/workflows/main_build.yml /tmp/main_build_variant_17_1_generic_aarch64.yml

perl -0777 -i -pe 's/matrix:\n\s*version:\s*\$\{\{\s*fromJson\(needs\.detect-versions\.outputs\.versions\)\s*\}\}\n\s*board:\s*\$\{\{\s*fromJson\(needs\.detect-boards\.outputs\.boards\)\s*\}\}/matrix:\n        version: ["17.1"]\n        board: ["generic_aarch64"]/s' \
  /tmp/main_build_variant_17_1_generic_aarch64.yml

perl -0777 -i -pe 's/matrix:\n\s*version:\s*\$\{\{\s*fromJson\(needs\.detect-versions\.outputs\.versions\)\s*\}\}/matrix:\n        version: ["17.1"]/s' \
  /tmp/main_build_variant_17_1_generic_aarch64.yml
```

Quick check:
```bash
grep -nE "matrix:|version: \[|board: \[" /tmp/main_build_variant_17_1_generic_aarch64.yml
```

Script-based quick check example:
```bash
grep -nE "matrix:|version: \[|board: \[" /tmp/main_build_variant_17.1_generic_aarch64.yml
```

## 4. Dry-Run The Variant Workflow
```bash
act workflow_dispatch \
  -W /tmp/main_build_variant_17_1_generic_aarch64.yml \
  --container-architecture linux/amd64 \
  -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 \
  --dryrun
```

Script-based dry-run example:
```bash
act workflow_dispatch \
  -W /tmp/main_build_variant_17.1_generic_aarch64.yml \
  --container-architecture linux/amd64 \
  -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 \
  --dryrun
```

Expected outcome:
- `detect-boards`: planned successfully.
- `detect-versions`: planned successfully.
- `build 17.1 / generic_aarch64`: planned successfully.
- `release 17.1`: planned successfully.

## Notes
- Keep all simulation edits in `/tmp` only.
- Do not commit temporary variant workflows.
- A dry-run validates workflow planning, not full compile correctness.
