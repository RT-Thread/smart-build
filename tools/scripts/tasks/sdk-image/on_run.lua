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
-- @author      xqyjlj
-- @file        on_run.lua
--
-- Change Logs:
-- Date           Author       Notes
-- ------------   ----------   -----------------------------------------------
-- 2024-11-20     zhujiale       initial version
-- 2024-12-9     zchenxiao      add version get
--
import("core.base.option")
import("core.project.task")
import("privilege.sudo")

-- 检查是否存在必需的参数
local function check_required_param(param, name)
    if not param then
        print("错误：缺少必要参数 '" .. name .. "'")
        os.exit(1)
    end
end

-- 创建分区
local function create_partition(imgname, start, end_, name)
    if os.execv("parted", {"-s", imgname, "mkpart", name, start, end_}) ~= 0 then
        print("创建分区失败：" .. name)
        os.exit(1)
    end
    print(string.format("成功创建分区: %s (起始: %s, 结束: %s)", name, start, end_))
end

-- 生成并写入 boot.img 镜像
local function boot_img(rtthread_bin, fdt)
    os.execv("sync")

    os.iorun("rm boot -rf")
    os.iorun("mkdir boot")

    os.execv("dd", {"if=/dev/zero", "of=./boot.img", "bs=1M", "count=32"})
    os.execv("mkfs.fat", {"./boot.img"})
    if sudo.has() then
        os.execv("sudo mount", {"./boot.img", "boot/"})
        os.execv("sudo cp", {rtthread_bin, "./boot"})
        os.execv("sudo cp", {fdt, "./boot/fdt"})
        os.iorun("sudo umount boot/")
    else
        os.execv("mount", {"./boot.img", "boot/"})
        os.execv("cp", {rtthread_bin, "./boot"})
        os.execv("cp", {fdt, "./boot/fdt"})
        os.iorun("umount boot/")
    end

    os.exec("sync")
    os.iorun("rm boot -rf")
end

-- 获取当前目录下的文件路径
local function get_kernel_from_curdir()
    local kernel_path = os.curdir() .. "/rtthread.bin"
    if not os.isfile(kernel_path) then
        print("错误：未找到内核文件 'rtthread.bin' 在当前目录中")
        os.exit(1)
    end
    return kernel_path
end

local function get_rootfs_from_curdir()
    local rootfs_path = os.curdir() .. "/build/ext4.img"
    if not os.isfile(rootfs_path) then
        print("错误：未找到根文件系统文件 'ext4.img' 在当前目录中")
        os.exit(1)
    end
    return rootfs_path
end

local function get_other_files_from_curdir()
    local files = {
        uboot = os.curdir() .. "/u-boot.itb",
        fdt = os.curdir() .. "/fdt",
        idbloader = os.curdir() .. "/idbloader.img",
    }

    for name, path in pairs(files) do
        if not os.isfile(path) then
            print("错误：未找到文件 '" .. name .. "' 在当前目录中")
            os.exit(1)
        end
    end

    return files
end

function main()
    -- print("=======================", os.curdir(), "=======================")
    -- print("=======================", os.scriptdir(), "=======================")

    -- 获取文件路径
    local rtthread_bin = get_kernel_from_curdir()        -- 获取内核文件
    local rootfs_img = get_rootfs_from_curdir()          -- 获取根文件系统
    local other_files = get_other_files_from_curdir()    -- 获取其他文件

    -- 提取其它文件路径
    local uboot_img = other_files.uboot
    local fdt = other_files.fdt
    local idbloader_img = other_files.idbloader

    -- 删除现有镜像文件
    os.iorun("rm rk35xx.img -f")

    -- 确保文件存在
    check_required_param(rtthread_bin, "kernel")
    check_required_param(uboot_img, "uboot")
    check_required_param(fdt, "fdt")
    check_required_param(idbloader_img, "loader")
    check_required_param(rootfs_img, "rootfs")

    -- 镜像文件名
    local imgname = "rk35xx.img"
    local pwd = os.getenv("PWD")
    
    -- 创建空白的 rk35xx.img 文件并初始化
    os.execv("dd", {"if=/dev/zero", "of="..pwd .. "/" .. imgname, "bs=1M", "count=1000"})
    os.execv("ls -al")
    os.execv("parted", {"-s", pwd .. "/" .. imgname, "mklabel", "gpt"})

    -- 创建分区
    create_partition(imgname, "64s", "7104s", "loader1")
    create_partition(imgname, "16384s", "24575s", "loader2")
    create_partition(imgname, "32768s", "262143s", "boot")
    create_partition(imgname, "262144s", "100%", "rootfs")
    os.execv("parted", {"-s", imgname, "unit", "s", "print"})

    -- 生成 boot.img 并将内核及设备树文件复制进去
    boot_img(rtthread_bin, fdt)

    -- 将各个文件写入分区
    os.execv("dd", {"if=" .. idbloader_img, "of=" .. imgname, "bs=512", "seek=64"})
    os.execv("dd", {"if=" .. uboot_img, "of=" .. imgname, "bs=512", "seek=16384"})
    os.execv("dd", {"if=./boot.img", "of=" .. imgname, "bs=512", "seek=32768"})
    os.execv("dd", {"if=" .. rootfs_img, "of=" .. imgname, "bs=512", "seek=262144"})

    -- 调整镜像大小
    os.exec("truncate -s 1000M " .. imgname)
    print("the image " .. imgname .. " part is :")
    os.execv("parted", {"-s", imgname, "unit", "s", "print"})

    -- 清理临时的 boot.img 文件
    os.iorun("rm boot.img")
end
