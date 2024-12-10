{
    files = {
        "zlib/main.c"
    },
    values = {
        "/home/zcx/.xmake/packages/a/aarch64-smart-musleabi/236309-e8ed057a81/92ace334959c4a2c9fc34a7aa7427678/bin/aarch64-linux-musleabi-gcc",
        {
            "-march=armv8-a",
            "-fvisibility=hidden",
            "-O3",
            "-isystem",
            "/home/zcx/.xmake/packages/z/zlib/v1.2.13/76e54536b82e402d9bc1ec2ea08c623f/include",
            "-DNDEBUG"
        }
    },
    depfiles_gcc = "main.o: zlib/main.c\
"
}