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
