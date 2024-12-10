{
    files = {
        "smart-fetch/smart_fetch.c"
    },
    values = {
        "/home/zcx/.xmake/packages/a/aarch64-smart-musleabi/236309-e8ed057a81/92ace334959c4a2c9fc34a7aa7427678/bin/aarch64-linux-musleabi-gcc",
        {
            "-march=armv8-a",
            "-fvisibility=hidden",
            "-O3",
            "-Ismart-fetch",
            "-DNDEBUG"
        }
    },
    depfiles_gcc = "smart_fetch.o: smart-fetch/smart_fetch.c smart-fetch/smart_fetch.h\
"
}