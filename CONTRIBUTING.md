# Contributing to smart-build

Contributions should describe and preserve the current behavior of smart-build
as a standalone RT-Thread Smart build system.

## Before changing code

- Run `./smart-build doctor` for the target machine.
- Keep generated outputs, downloads, external RT-Thread sources, toolchains,
  `.config`, and local automation configuration out of commits.
- Follow neighboring Python, Kconfig, YAML, and build-script style.
- Use `SmartBuildError` with a stable user-facing code for expected failures.
- Validate external paths and metadata before creating executable build tasks.

## Repository conventions

- Machine, rootfs, and package names use lowercase English and hyphens.
- A board directory name must equal its `MACHINE` value and board description
  name.
- Package metadata is stored in `packages/<name>/package.yaml`.
- Generated package Kconfig files must match package metadata and must not be
  edited by hand.
- Build tasks write only through paths owned by `BuildPaths`.
- Public documentation describes implemented behavior, including current
  limitations; it does not contain requirements, internal design documents,
  implementation plans, roadmaps, internal review records, or automation
  instructions.

## Tests

Run the smallest relevant pytest test first. Run the full test suite for shared
task, scheduler, cache, manifest, configuration, machine metadata, or
cross-domain changes:

```sh
python -m pytest
```

For real build changes, run the affected target:

```sh
./smart-build build <target>
```

For a QEMU-capable machine, also run:

```sh
./smart-build qemu-smoke
```

Confirm that RT-Thread Smart reaches its shell and inspect the complete log for
errors rather than relying only on the command exit status.

## Documentation changes

When a command, configuration field, package contract, board contract, rootfs
contract, or user-visible limitation changes, update `README.md`,
`docs/README.md`, and the relevant user guide in the same contribution.

## Commits and pull requests

Use a concise imperative title with an optional scope prefix, for example:

```text
docs: add board support guide
fix: validate qemu rootfs selection
```

Keep each commit focused on one topic. A pull request should identify the
affected machine, package, or build domain; list the commands actually run; and
describe compatibility or manifest changes. Include relevant QEMU boot output
when QEMU behavior changes.
