**English** | [中文](package-yaml_zh.md)

# Package description reference

Package descriptions use YAML schema version 1 and live at
`packages/<name>/package.yaml`.

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
| `description` | No | User-facing package description |
| `depends` | No | Dependency names or provided capabilities |
| `selects` | No | Packages or capabilities selected automatically |
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

`depends`, `selects`, `conflicts`, `provides`, and `requires_toolchain` normally
use lists. For compatibility, `depends` also accepts a comma-separated string.
Dependencies can refer to a package name or a name listed by another package's
`provides` field.

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
  files:
    - configure
```

Archive extraction rejects path traversal and unsafe link targets. `local_files`
are copied from the package directory into the prepared source tree.

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
