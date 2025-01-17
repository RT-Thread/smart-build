-- Licensed under the Apache License, Version 2.0 (the "License");
-- You may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.
--
-- Copyright (C) 2023-2023 RT-Thread Development Team
--
-- @author      zchenxiao
-- @file        xmake.lua
--
-- Change Logs:
-- Date           Author       Notes
-- ------------   ----------   -----------------------------------------------
-- 2024-12-17     zchenxiao       initial version
--
package("uboot")
do
    set_kind("binary") 
    set_homepage("https://git.rt-thread.com/alliance/smart-apps/rkbin-mirror.git")
    set_description("RKBin mirror repository for u-boot branch")
    local build_dir = os.curdir()

    on_load(function (package)
        import("devel.git")
        local install_dir = package:installdir()
        local uboot_dir = path.join(install_dir, "rkbin-mirror")
        local branch = "u-boot"
        local repo_dir = path.join(uboot_dir,"rockchip/rk3568/nanopi")
        if not os.isdir(uboot_dir) then
            print("Cloning RKBin mirror repository...")
            git.clone("https://git.rt-thread.com/alliance/smart-apps/rkbin-mirror.git", {outputdir = repo_dir})
        else
            print("RKBin mirror repository already exists.")
        end

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


