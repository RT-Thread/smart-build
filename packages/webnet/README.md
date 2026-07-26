# WebNet SCons package example

This package demonstrates the independent RT-Thread SCons package backend with
the official RT-Thread `webnet` online package. The repository contains only
the top-level project; Env downloads the selected WebNet version while building
an isolated copy.

The build performs these steps:

1. Generate `.config`, `rtconfig.h`, and `pkg_config.h`.
2. Run Env `pkgs --update` to download WebNet.
3. Load WebNet's generated `packages/SConscript` and compile it together with
   the local `main.c`.
4. Install `/bin/webnet` into the package staging directory and create
   `webnet.ipk`.

Configure and build the example from the repository root:

```sh
./smart-build configure package:webnet
./smart-build build package:webnet
```

The configure command exposes the WebNet port, connection limit, document
root, optional modules, and online package version. It saves those values
through smart-build without downloading WebNet or modifying
`packages/webnet/source`.

Running `/bin/webnet` initializes the server and keeps the process alive.
`/bin/webnet --help` prints its usage and exits, which is also the package smoke
command. The configured document root must exist in the target rootfs before
serving files.

The build requires the configured machine toolchain, RT-Thread Env package
index, network access, the repository `rt-thread` source, and
`packages/smart-sdk`. Downloaded sources remain below
`build/<machine>/work/packages/webnet/source/packages/`.

`source/building.py` is a package-local compatibility layer for the RT-Thread
SConscript helpers used by WebNet. `source/webnet_compat.h` supplies standard
musl IPv4 socket declarations that WebNet receives implicitly from RT-Thread's
embedded socket headers. Neither file imports smart-build Python APIs.
