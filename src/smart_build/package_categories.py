"""Menuconfig grouping for smart-build packages."""

OTHER_CATEGORY = "Other"

PACKAGE_CATEGORIES = (
    "Networking",
    "Shell and editors",
    "Compressors",
    "Security and cryptography",
    "Interpreters and languages",
    "Libraries",
    "Graphics and multimedia",
    "Math and machine learning",
    "Development and testing",
    "System utilities",
    "ROS 2",
    "Host tools",
    OTHER_CATEGORY,
)

_PACKAGE_CATEGORY_BY_NAME = {
    "curl": "Networking",
    "dropbear": "Networking",
    "haproxy": "Networking",
    "iperf3": "Networking",
    "libcurl": "Networking",
    "tinyssh": "Networking",
    "uhttpd": "Networking",
    "webclient": "Networking",
    "webnet": "Networking",
    "wget": "Networking",
    "dialog": "Shell and editors",
    "mc": "Shell and editors",
    "nano": "Shell and editors",
    "ncurses": "Shell and editors",
    "readline": "Shell and editors",
    "tmux": "Shell and editors",
    "vim": "Shell and editors",
    "bzip2": "Compressors",
    "libzlib": "Compressors",
    "lzo": "Compressors",
    "xz": "Compressors",
    "zlib": "Compressors",
    "zlib-ng": "Compressors",
    "botan": "Security and cryptography",
    "gnupg2": "Security and cryptography",
    "libgpg-error": "Security and cryptography",
    "libopenssl": "Security and cryptography",
    "libressl": "Security and cryptography",
    "libxcrypt": "Security and cryptography",
    "openssl": "Security and cryptography",
    "sedutil": "Security and cryptography",
    "lua": "Interpreters and languages",
    "luajit": "Interpreters and languages",
    "micropython": "Interpreters and languages",
    "quickjs": "Interpreters and languages",
    "jemalloc": "Libraries",
    "json-c": "Libraries",
    "libabseil-cpp": "Libraries",
    "libatomic_ops": "Libraries",
    "libbsd": "Libraries",
    "libeastl": "Libraries",
    "libevent": "Libraries",
    "libexpat": "Libraries",
    "libffi": "Libraries",
    "libglib2": "Libraries",
    "libiconv": "Libraries",
    "libnspr": "Libraries",
    "libubox": "Libraries",
    "libunwind": "Libraries",
    "liburcu": "Libraries",
    "libuv": "Libraries",
    "libxml2": "Libraries",
    "pcre": "Libraries",
    "pcre2": "Libraries",
    "poco": "Libraries",
    "protobuf": "Libraries",
    "fdk-aac": "Graphics and multimedia",
    "ffmpeg": "Graphics and multimedia",
    "freetype": "Graphics and multimedia",
    "libjpeg": "Graphics and multimedia",
    "libjpeg-turbo": "Graphics and multimedia",
    "libopenh264": "Graphics and multimedia",
    "libpng": "Graphics and multimedia",
    "lvgl": "Graphics and multimedia",
    "opencv": "Graphics and multimedia",
    "sdl2": "Graphics and multimedia",
    "sdl2-image": "Graphics and multimedia",
    "cpuinfo": "Math and machine learning",
    "fp16": "Math and machine learning",
    "fxdiv": "Math and machine learning",
    "lapack": "Math and machine learning",
    "llama-cpp": "Math and machine learning",
    "psimd": "Math and machine learning",
    "pthreadpool": "Math and machine learning",
    "tensorflow-lite": "Math and machine learning",
    "xnnpack": "Math and machine learning",
    "z3": "Math and machine learning",
    "hello": "Development and testing",
    "ltp-testsuite": "Development and testing",
    "oprofile": "Development and testing",
    "utest-h": "Development and testing",
}


def package_category(metadata):
    declared = getattr(metadata, "category", "") or ""
    if declared:
        return declared
    path = getattr(metadata, "path", None)
    if path is not None:
        from .package_metadata import is_host_package_path, is_ros2_package_path

        if is_host_package_path(path):
            return "Host tools"
        if is_ros2_package_path(path):
            return "ROS 2"
    return _PACKAGE_CATEGORY_BY_NAME.get(metadata.name, OTHER_CATEGORY)


def grouped_packages(packages):
    groups = {}
    extras = set()
    for metadata in packages:
        category = package_category(metadata)
        groups.setdefault(category, []).append(metadata)
        if category not in PACKAGE_CATEGORIES:
            extras.add(category)
    order = [title for title in PACKAGE_CATEGORIES if title != OTHER_CATEGORY]
    order.extend(sorted(extras))
    order.append(OTHER_CATEGORY)
    result = []
    for title in order:
        items = sorted(groups.get(title, ()), key=lambda item: item.name)
        if items:
            result.append((title, items))
    return tuple(result)
