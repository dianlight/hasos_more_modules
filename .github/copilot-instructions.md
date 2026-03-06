# Copilot Rules For Workflow Variant Testing

## Scope
These instructions apply when working on `.github/workflows/main_build.yml` and when testing GitHub Actions locally with `act`.

## Rules
1. For local workflow validation on Apple Silicon, use:
   - `--container-architecture linux/amd64`
   - `-P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04`
2. If `act` fails to parse dynamic matrix expressions like `fromJson(needs.<job>.outputs.<name>)`, do not modify tracked workflow files to work around it.
3. To simulate a specific matrix variant, create a temporary workflow copy under `/tmp` and replace dynamic matrix values with static arrays for the target variant.
4. Keep production workflow behavior unchanged. Temporary simulation files must stay outside the repository.
5. In reports, always include:
   - The exact command(s) used.
   - Which variant was simulated (`version` and `board`).
   - Whether failures are from workflow logic or `act` parser limitations.

## Preferred Commands
- List jobs:
  - `act -l`
- Full dry-run:
  - `act workflow_dispatch -W .github/workflows/main_build.yml --container-architecture linux/amd64 -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 --dryrun`
- Single variant dry-run with static matrix in `/tmp` copy:
  - `act workflow_dispatch -W /tmp/main_build_variant.yml --container-architecture linux/amd64 -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 --dryrun`

## Detailed Variant Procedure
1. Generate a temporary static-matrix workflow file:
   - `bash scripts/create_static_matrix_variant.sh --version 17.1 --board generic_aarch64`
2. Confirm the generated matrix values:
   - `grep -nE "matrix:|version: \[|board: \[" /tmp/main_build_variant_17.1_generic_aarch64.yml`
3. Dry-run the generated file:
   - `act workflow_dispatch -W /tmp/main_build_variant_17.1_generic_aarch64.yml --container-architecture linux/amd64 -P ubuntu-24.04=ghcr.io/catthehacker/ubuntu:act-24.04 --dryrun`

## Reporting Template
- Variant:
  - `version=<value>`
  - `board=<value>`
- Command:
  - `<exact act command>`
- Outcome:
  - `success` or `failure`
- Root cause class:
  - `workflow logic`
  - `act parser limitation`
