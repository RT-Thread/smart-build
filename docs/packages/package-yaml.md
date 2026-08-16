**English** | [中文](package-yaml_zh.md)

# Package description reference

Package descriptions use YAML schema version 1 and live at
`packages/<name>/package.yaml`, `packages/ros2/<name>/package.yaml`, or
`packages/host/<name>/package.yaml`.

## Common fields

| Field | Required | Description |
| --- | --- | --- |
| `schema_version` | Yes | Must currently be `1` |
| `kind` | Yes | Must be `package` |
| `name` | Yes | Package name matching its directory |
| `version` | Yes | Description version and default package version fallback |
| `versions` | No | Non-empty list of selectable package versions |
| `default_version` | No | Entry from `versions` |
| `type` | Build dependent | `library` or `executable` |
| `description` | No | User-facing package description shown in generated Kconfig, at most 80 characters |
| `category` | No | menuconfig group; defaults to the built-in package category map |
| `depends` | No | Required packages or capabilities; menuconfig selects them automatically |
| `host_depends` | No | Host-only build dependencies; they are selected and built without entering the target IPKG |
| `selects` | No | Extra packages or capabilities selected automatically |
| `conflicts` | No | Packages that cannot be selected together |
| `provides` | No | Capabilities provided by this package |
| `requires_toolchain` | No | Required toolchain capabilities |
| `options` | No | Package option definitions |
| `kconfig` | Native SCons packages | Native Kconfig source and package selection symbol |
| `source` | Yes for source builds | Repository directory or archive source |
| `build` | Yes | Build backend configuration |
| `install` | Backend dependent | Rootfs installation paths |
| `smoke` | No | Command and optional expected stdout for runtime checking |
| `configure` | No | Interactive upstream configuration mapping |

## Relations

`depends`, `host_depends`, `selects`, `conflicts`, `provides`, and
`requires_toolchain` normally use lists. For compatibility, `depends` and
`host_depends` also accept comma-separated strings. Dependencies can refer to a
package name or a name listed by another package's `provides` field. Generated
package Kconfig turns `depends`, `host_depends`, and `selects` into `select`, so
a package stays checkable and pulls in its requirements. Host dependencies are
used by the build graph but are excluded from target IPKG assembly.

The generated `packages/Kconfig` index groups packages into menus such as
Networking, Libraries, and Development and testing. Set `category` to override
the default group; unknown names appear in Other.

## Options

Option types are `bool`, `choice`, and `string`:

```yaml
options:
  shared:
    type: bool
    prompt: Build shared library
    default: true
  compression_level:
    type: choice
    prompt: Default compression level
    choices: [fast, balanced, best]
    default: balanced
  heap_size:
    type: string
    prompt: Heap size
    default: 64k
```

Options generate package Kconfig symbols and are recorded in the manifest.
The current build backends do not consistently forward them to build scripts,
so a package author must verify whether an option affects its output.

## Repository-local source

```yaml
source:
  directory: apps/example
  files:
    - CMakeLists.txt
    - main.c
```

The directory must stay inside the repository. Declared source files must be
regular files below that directory.

## Archive source

```yaml
source:
  type: archive
  url: https://example.org/example-1.0.0.tar.gz
  archive: example-1.0.0.tar.gz
  sha256: <sha256>
  strip_root: true
  local_files:
    - sbuild.py
    - patches/example.patch
  patches:
    - example.patch
  files:
    - configure
```

For best-effort imported packages whose upstream does not publish a hash,
`source.allow_unverified: true` may be used explicitly. Normal package
definitions should keep an immutable archive URL and SHA-256 checksum.

Archive extraction rejects path traversal and unsafe link targets. `local_files`
are copied from the package directory into the prepared source tree. Every
entry in `patches` must also be listed in `local_files`; patches are applied to
the prepared tree in declaration order with `git apply`, before configuration
is restored. A patch failure stops source preparation.

## Python backend

```yaml
build:
  python:
    script: sbuild.py
    outputs:
      - /usr/bin/example
      - /usr/lib/libexample.a
    upstream_markers:
      - configure
install:
  path: /usr/bin/example
```

Every declared output must be created below the package staging directory.
Output paths are absolute rootfs paths in metadata but cannot escape staging.

## ament CMake backend

```yaml
type: library
category: ROS 2
build:
  ament_cmake:
    testing: false
    linkage: shared
    host_python: sdk
    cmake_args:
      - -DCMAKE_BUILD_TYPE=Release
    outputs:
      - /usr/lib
      - /usr/include
      - /usr/share
```

The backend writes a Generic/UNIX CMake toolchain file, turns off tests unless
`testing` is true, applies the selected `linkage`, and installs with `DESTDIR`
set to the package staging directory. `CMAKE_PREFIX_PATH` and
`AMENT_PREFIX_PATH` include the complete dependency closure and
`build/<machine>/host/ros2-sdk`. With `host_python: sdk`, CMake and ament
generators use the Host SDK virtual environment. Toolchain, prefix, install,
and Python arguments are protected from override by `cmake_args`. Declared
outputs must exist after install.

## CMake executable backend

```yaml
type: executable
source:
  directory: apps/example
  files: [CMakeLists.txt, main.c]
build:
  cmake:
    outputs:
      static: [/bin/example-static]
      dynamic: [/bin/example-dynamic]
      mixed: [/bin/example-static, /bin/example-dynamic]
    options:
      - -DCMAKE_BUILD_TYPE=Release
```

The selected rootfs build mode chooses the output set. CMake options cannot
override smart-build-owned toolchain, install prefix, or linkage definitions.

## Independent RT-Thread SCons backend

This backend is limited to adjusted, repository-local RT-Thread packages with
the following fixed layout:

```text
packages/example/
  package.yaml
  source/
    Kconfig
    SConstruct
    SConscript
    main.c
```

The package uses its native `source/Kconfig` in both RT-Thread and smart-build.
It must not declare generated `options` or multiple versions in `package.yaml`.
The selection symbol must be defined by the Kconfig closure rooted at that
file. A package-local boolean can select the RT-Thread Env online package while
keeping the smart-build package selection explicit.

```yaml
type: executable
source:
  directory: packages/webclient/source
kconfig:
  mode: native
  source: source/Kconfig
  symbol: PACKAGE_WEBCLIENT
build:
  rtthread_scons:
    supported_linkage: [static]
    install_target: install
    outputs:
      - /bin/webclient
```

To use RT-Thread online packages, the native Kconfig can source the installed
Env index in the same way as an independent RT-Thread project:

```kconfig
config PKGS_DIR
    string
    option env="PKGS_ROOT"
    default "packages"

menu "webclient"

config PACKAGE_WEBCLIENT
    bool "Enable webclient"
    select PKG_USING_WEBCLIENT

source "$PKGS_DIR/Kconfig"

endmenu
```

`./smart-build configure package:<name>` opens this native Kconfig and saves
the configuration subtree rooted at `kconfig.symbol`. Configuration does not
run SCons or Env `pkgs --update`; the build uses the saved values later.

`source.directory`, `kconfig.source`, `SConstruct`, `SConscript`, and the
`install` target are fixed by this contract. Every output is an absolute rootfs
path. The install target must create exactly those regular files below
`DESTDIR`; undeclared files, missing files, links, and escaping paths are
rejected.

For a `static` or `dynamic` rootfs build mode, that mode is passed as `LINKAGE`
and must be listed in `supported_linkage`. A `mixed` rootfs accepts any package
linkage: smart-build selects the first entry in `supported_linkage`, so the list
also defines the package preference order. smart-build supplies the following
build environment. `BUILD_DIR` through `LINKAGE` are also passed as command-line
SCons variables:

| Variable | Meaning |
| --- | --- |
| `BUILD_DIR` | Package build directory outside the copied source tree |
| `DESTDIR` | Package-specific staging directory |
| `KCONFIG_CONFIG` | Generated package configuration snapshot |
| `SMART_SDK_DIR` | Repository RT-Thread Smart SDK package |
| `RTT_ROOT` | Repository RT-Thread source root |
| `RTTHREAD_TOOLS_DIR` | RT-Thread Python build tools directory |
| `CROSS_COMPILE` | Selected machine toolchain prefix |
| `MACHINE` | Selected target machine |
| `LINKAGE` | Linkage selected for this package |
| `ENV_ROOT` | Installed RT-Thread Env root |
| `PKGS_ROOT` | Env package metadata root used by Kconfig |
| `PKGS_DIR` | Env package metadata root used by Kconfig |
| `PYTHONPATH` | Includes `RTTHREAD_TOOLS_DIR` |

smart-build copies `source/` into the machine work directory, excluding local
generated state. It writes `.config`, runs `scons --pyconfig-silent`, then runs
the installed Env `pkgs --update`. The generated `packages/SConscript`, package
state, and downloaded sources are validated before `scons install` runs from
the same isolated copy. The source package is not modified.

Online dependencies remain managed by RT-Thread Env and participate through
`packages/SConscript`. They do not become separate smart-build packages or
IPKG files; only the declared outputs of the independent top-level project are
packaged. This backend does not support a complete userapps tree, application
discovery, alternate SConstruct entry names, arbitrary remote source
preparation, or interpretation of SCons scripts.
