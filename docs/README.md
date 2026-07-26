**English** | [中文](README_zh.md)

# smart-build documentation

This directory contains public documentation for users and extension authors.
It describes the behavior available in the current source tree.

English files without a language suffix are the default. Chinese translations
use the `_zh.md` suffix, and each page links to its counterpart.

## Use smart-build

- [Getting started](getting-started.md)
- [Configuration](configuration.md)
- [Command reference](commands.md)
- [Troubleshooting](troubleshooting.md)
- [Compatibility and current limitations](compatibility.md)

The configuration guide covers both the workspace menu and target-specific
configuration, including native Kconfig for independent RT-Thread SCons packages.

## Extend smart-build

- [Using packages](packages/using-packages.md)
- [Adding a package](packages/creating-package.md)
- [Package description reference](packages/package-yaml.md)
- [Supported boards](boards/supported-boards.md)
- [Adding board support](boards/creating-board.md)
- [Root filesystem support](rootfs/rootfs-options.md)
- [Adding a root filesystem type](rootfs/creating-rootfs.md)

Requirements, internal architecture, implementation plans, review records, and
internal automation instructions are not part of this public documentation.
