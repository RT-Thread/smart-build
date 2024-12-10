{
    values = {
        "/home/zcx/.xmake/packages/a/aarch64-smart-musleabi/236309-e8ed057a81/92ace334959c4a2c9fc34a7aa7427678/bin/aarch64-linux-musleabi-g++",
        {
            "--static",
            "-s",
            "-L/home/zcx/userapps/sdk/lib",
            "-L/home/zcx/userapps/sdk/lib/aarch64/cortex-a",
            "-L/home/zcx/userapps/sdk/rt-thread/lib/aarch64/cortex-a",
            "-Wl,--start-group",
            "-Wl,-whole-archive",
            "-lrtthread",
            "-Wl,-no-whole-archive",
            "-Wl,--end-group"
        }
    },
    files = {
        "build/.objs/shm_ping/cross/aarch64/release/shm_ping/main.c.o"
    }
}