# WebClient SCons package example

This package demonstrates the independent RT-Thread SCons package backend. It
keeps only the top-level project in the repository and selects the official
RT-Thread `webclient` package from the installed Env package index.

The build performs these steps in an isolated machine work directory:

1. Generate `.config`, `rtconfig.h`, and `pkg_config.h`.
2. Run Env `pkgs --update` to download `webclient`.
3. Load the generated `packages/SConscript` and compile its sources together
   with `main.c`.
4. Install `/bin/webclient` into this package's staging directory and create
   `webclient.ipk`.

Build the example from the repository root:

```sh
./smart-build configure package:webclient
./smart-build build package:webclient
```

The configure command opens WebClient's native RT-Thread package options and
saves them through smart-build. It does not download webclient or modify files
below `packages/webclient/source`; downloading starts with the build command.

The build requires the configured machine toolchain, RT-Thread Env package
index, network access, the repository `rt-thread` source, and
`packages/smart-sdk`. Generated Env package sources remain below
`build/<machine>/work/packages/webclient/source/packages/`; they are not copied
back into this directory.

`source/building.py` is a package-local compatibility layer for the small
subset of RT-Thread SConscript helpers used by webclient. It is part of the
independent example and does not import smart-build Python APIs.
