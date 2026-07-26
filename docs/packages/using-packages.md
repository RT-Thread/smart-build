**English** | [中文](using-packages_zh.md)

# Using packages

Packages are selected through the configured rootfs or built directly by name.

## Build one package

```sh
./smart-build build package:hello
./smart-build build package:curl
```

The resolver loads every `packages/<name>/package.yaml`, resolves providers and
dependencies, rejects declared conflicts, and creates source and build tasks.
For example, selecting curl also selects OpenSSL and zlib.

Downloaded archives are stored below `downloads/`. Prepared sources, work
directories, logs, and staged files are stored below `build/<machine>/`.

## Select packages for a rootfs

Run:

```sh
./smart-build menuconfig
```

Choose the full rootfs to select packages manually or use one of its profiles.
Package Kconfig entries are generated from package metadata, including version,
dependency, conflict, and option selections.

## Configure a package

A package with a `configure` mapping, or an independent RT-Thread SCons package
with native Kconfig, can be configured using:

```sh
./smart-build configure package:<name>
```

Native Kconfig configuration is saved by smart-build without modifying the
package source directory or downloading online packages. Other packages
without a `configure` mapping do not provide an interactive configuration step.

## Package outputs

Library packages stage headers and libraries. Executable packages stage files
at the rootfs paths declared by their build and install metadata. The rootfs
assembly step rejects conflicting files from different packages.

Some metadata options are currently recorded but not consumed by every package
backend. Confirm the generated files when changing package-specific options.
