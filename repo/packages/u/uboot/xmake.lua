package("uboot")
do
    set_kind("binary") -- 指定包的类型
    set_homepage("https://git.rt-thread.com/alliance/smart-apps/rkbin-mirror.git")
    set_description("RKBin mirror repository for u-boot branch")
    local build_dir = os.curdir()

    on_load(function (package)
        import("devel.git")
        local install_dir = package:installdir()
        local uboot_dir = path.join(install_dir, "rkbin-mirror")
        local branch = "u-boot"
        local repo_dir = path.join(uboot_dir,"rockchip/rk3568/nanopi")
        -- 如果目录不存在，则克隆整个仓库
        if not os.isdir(uboot_dir) then
            print("Cloning RKBin mirror repository...")
            git.clone("https://git.rt-thread.com/alliance/smart-apps/rkbin-mirror.git", {outputdir = repo_dir})
        else
            print("RKBin mirror repository already exists.")
        end
        print("============s",uboot_dir,"============s")
        print("============s",repo_dir,"============s")
        print("============s",build_dir,"============s")
        os.execv("git", {"-C", uboot_dir, "checkout", branch})
        os.execv("cp", {
            path.join(repo_dir, "dtb"),
            path.join(repo_dir, "fdt"),
            path.join(repo_dir, "idbloader.img"),
            path.join(repo_dir, "u-boot.itb"),
            build_dir
        })

        print("RKBin mirror repository is ready at:", build_dir)
    end)
end


