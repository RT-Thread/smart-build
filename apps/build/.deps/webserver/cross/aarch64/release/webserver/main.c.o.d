{
    files = {
        "webserver/main.c"
    },
    values = {
        "/home/zcx/.xmake/packages/a/aarch64-smart-musleabi/236309-e8ed057a81/92ace334959c4a2c9fc34a7aa7427678/bin/aarch64-linux-musleabi-gcc",
        {
            "-march=armv8-a",
            "-fvisibility=hidden",
            "-O3",
            "-Iwebserver",
            "-Iwebserver/packages/webnet-v2.0.2/inc",
            "-Dclosesocket=close",
            "-DHAVE_PKG_CONFIG_H",
            "-DNDEBUG",
            "-DHAVE_CCONFIG_H",
            "-I/home/zcx/userapps/sdk/rt-thread/include",
            "-I/home/zcx/userapps/sdk/rt-thread/components/dfs",
            "-I/home/zcx/userapps/sdk/rt-thread/components/drivers",
            "-I/home/zcx/userapps/sdk/rt-thread/components/finsh",
            "-I/home/zcx/userapps/sdk/rt-thread/components/net"
        }
    },
    depfiles_gcc = "main.o: webserver/main.c\
"
}