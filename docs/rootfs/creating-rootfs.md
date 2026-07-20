# Adding a root filesystem type

A rootfs type owns a lowercase, hyphenated directory:

```text
rootfs/<type>/
  Kconfig
  rootfs.yaml
```

## Add the description

```yaml
schema_version: 1
kind: rootfs
name: example
version: 0.1.0
default_profile: base
profiles:
  base:
    packages:
      - hello
filesystem:
  type: ext4
```

The common description loader requires `schema_version`, `kind`, `name`, and
`version`. Rootfs package and profile behavior is interpreted by the rootfs
domain, so use the existing minimal and full descriptions as current examples.

## Add Kconfig

Define a rootfs selection boolean and derived `ROOTFS`, `ROOTFS_BUILD_MODE`,
image format, image size, and size mode values. Source the new file from
`rootfs/Kconfig` and add it to the rootfs choice.

Only expose values that the rootfs and image domains can execute. In
particular, the current image backend supports ext4 only.

## Add execution support

Adding metadata alone does not create a build domain. A new rootfs layout or
image type must be mapped to real tasks in the rootfs, image, task-planning, and
QEMU domains as applicable. Every public build target must resolve to real
tasks for supported configurations.

## Verify the type

Test each supported machine, build mode, profile, and image-size behavior:

```sh
./smart-build menuconfig
./smart-build build rootfs
./smart-build build all
./smart-build qemu-smoke
python -m pytest
```

Also check disabled-rootfs and unsupported combinations to ensure they fail
with a clear configuration error before build tasks execute.
