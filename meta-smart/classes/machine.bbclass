def handle_machine(d):
    bsps = {
        'qemuarm64': {
            'ARCH': 'aarch64',
            'BSP': 'bsp/qemu-virt64-aarch64'
        },
        'qemuriscv64': {
            'ARCH': 'riscv64',
            'BSP': 'bsp/qemu-virt64-riscv'
        },
        'qemuarm32': {
            'ARCH': 'arm',
            'BSP': 'bsp/qemu-vexpress-a9'
        },
        'raspi4-64': {
            'ARCH': 'aarch64',
            'BSP': 'bsp/raspberry-pi/raspi4-64'
        },
        'rk3500': {
            'ARCH': 'aarch64',
            'BSP': 'bsp/rockchip/rk3500'
        },
        'k230': {
            'ARCH': 'riscv64',
            'BSP': 'bsp/k230'
        }
    }

    prefix = {
        'aarch64': 'aarch64-linux-musleabi-',
        'riscv64': 'riscv64-linux-musleabi-',
        'arm': 'arm-linux-musleabi-',
    }

    machine = d.getVar('MACHINE')
    if machine in bsps:
        d.setVar('BSP', bsps[machine]['BSP'])
        d.setVarFlag('BSP', 'export', '1')

        d.setVar('RTT_CC_PREFIX', prefix[bsps[machine]['ARCH']])
        d.setVarFlag('RTT_CC_PREFIX', 'export', '1')

        d.setVar('ARCH', bsps[machine]['ARCH'])
        d.setVarFlag('ARCH', 'export', '1')

def toolchain_for_machine(d):
    import os

    toolchains = {
        "aarch64-linux-musleabi-": {
            "URL": "https://download.rt-thread.org/download/rt-smart/toolchains/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
            "LOCAL_TC": "aarch64-linux-musleabi-gcc-latest",
            "TARGET_TC": "aarch64-linux-musleabi_for_x86_64-pc-linux-gnu"
        }, 
        "riscv64-linux-musleabi-": {
            "URL": "https://download.rt-thread.org/download/rt-smart/toolchains/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
            "LOCAL_TC": "riscv64-linux-musleabi-gcc-latest",
            "TARGET_TC": "riscv64-linux-musleabi_for_x86_64-pc-linux-gnu"
        },
        "arm-linux-musleabi-": {
            "URL": "https://download.rt-thread.org/download/rt-smart/toolchains/arm-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
            "LOCAL_TC": "arm-linux-musleabi-gcc-latest",
            "TARGET_TC": "arm-linux-musleabi_for_x86_64-pc-linux-gnu"
        }
    }

    toolchains_ci = {
        "aarch64-linux-musleabi-": {
            "URL": "https://github.com/RT-Thread/toolchains-ci/releases/download/v1.7/aarch64-linux-musleabi_for_x86_64-pc-linux-gnu_stable.tar.bz2",
            "LOCAL_TC": "aarch64-linux-musleabi-gcc-latest",
            "TARGET_TC": "aarch64-linux-musleabi_for_x86_64-pc-linux-gnu"
        }, 
        "riscv64-linux-musleabi-": {
            "URL": "https://github.com/RT-Thread/toolchains-ci/releases/download/v1.7/riscv64-linux-musleabi_for_x86_64-pc-linux-gnu_latest.tar.bz2",
            "LOCAL_TC": "riscv64-linux-musleabi-gcc-latest",
            "TARGET_TC": "riscv64-linux-musleabi_for_x86_64-pc-linux-gnu"
        },
        "arm-linux-musleabi-": {
            "URL": "https://github.com/RT-Thread/toolchains-ci/releases/download/v1.7/arm-linux-musleabi_for_x86_64-pc-linux-gnu_stable.tar.bz2",
            "LOCAL_TC": "arm-linux-musleabi-gcc-latest",
            "TARGET_TC": "arm-linux-musleabi_for_x86_64-pc-linux-gnu"
        }
    }

    # handle machine firstly
    handle_machine(d)

    prefix = d.getVar('RTT_CC_PREFIX')

    # get 'GITHUB_CI' from os.env
    if 'GITHUB_CI' in os.environ:
        d.setVar('URL_TC', toolchains_ci[prefix]["URL"])
        d.setVar('LOCAL_TC', toolchains_ci[prefix]["LOCAL_TC"])
        d.setVar('TARGET_TC', toolchains_ci[prefix]["TARGET_TC"])
    else:
        d.setVar('URL_TC', toolchains[prefix]["URL"])
        d.setVar('LOCAL_TC', toolchains[prefix]["LOCAL_TC"])
        d.setVar('TARGET_TC', toolchains[prefix]["TARGET_TC"])

    return toolchains[prefix]["URL"]
