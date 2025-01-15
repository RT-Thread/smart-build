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
-- @file        tasks.lua
--
-- Change Logs:
-- Date           Author       Notes
-- ------------   ----------   -----------------------------------------------
-- 2023-05-06     xqyjlj       initial version
-- 2024-10-17     zhujiale     add sdk task
-- 2024-12-9     zchenxiao    add menu task

set_xmakever("2.7.2")

task("menu")
do
    on_run(function ()
        os.exec("menuconfig")
    end)
    set_category("plugin")
    set_menu {
        usage = "menuconfig",
        description = "Launch menuconfig to configure the build",
        options = {}
    }
    end
task_end()

task("clean")
do
    on_run(function ()
        local build_dir = path.join(os.curdir(), "build") 

        if os.exists(build_dir) then
            os.rm(build_dir)
            print("Cleaned build directory.")
        else
            print("Build directory does not exist.")
        end
        
        local xmake_dir = path.join(os.curdir(), ".xmake")
        if os.exists(xmake_dir) then
            os.rm(xmake_dir)
            print("Cleaned .xmake directory.")
        else
            print(".xmake directory does not exist.")
        end

        local kernel_dir = path.join(os.curdir(), "rtthread.bin")
        if os.exists(kernel_dir) then
            os.rm(kernel_dir)
            print("Cleaned rt-thread.bin")
        else
            print(" rt-thread.bin does not exist.")
        end
        
        local global_xmake_dir = path.join(os.getenv("HOME"), ".xmake/packages/a/apps")
        if os.exists(global_xmake_dir) then
            os.rm(global_xmake_dir)
            print("Cleaned global xmake a/apps directory.")
        else
            print("$Home/.xmake/packages/a/apps directory does not exist.")
        end
    end)
    set_category("plugin")
    set_menu {
        usage = "menuconfig",
        description = "Launch menuconfig to configure the build",
        options = {}
    }
    end
task_end()

task("smart-image")
do
    on_run("tasks/smart-image/on_run")
    set_category("plugin")
    set_menu {
        usage = "xmake smart-image [options]",
        description = "make image",
        options = {
            {"f",   "format",           "kv",   "ext4",                                     "image format",
                                                                                            "    - ext4",
                                                                                            "    - fat",
                                                                                            "    - cromfs"},
            {"s",   "size",             "kv",   "256M",                                     "image size"},
            {"o",   "output",           "kv",   nil,                                        "output image dir"},
            {"r",   "rootfs",           "kv",   nil,                                        "rootfs dir"},
        }
    }
end
task_end()

task("smart-rootfs")
do
    on_run("tasks/smart-rootfs/on_run")
    set_category("plugin")
    set_menu {
        usage = "xmake smart-rootfs [options]",
        description = "copy dependent files onto roofs",
        options = {
            {nil,   "export",           "kv",   nil,                                        "export package to build dir",
                                                                                            "    - all",
                                                                                            "    - zlib"},
            {"o",   "output",           "kv",   nil,                                        "output dir"},
            {nil,   "no-symlink",        "k",   nil,                                        "without symbolic link."},
        }
    }
end
task_end()

task("sdk")
    set_category("plugin")
    on_run("tasks/sdk-image/on_run")  -- 将具体执行逻辑放到另一个文件中
    set_menu {
        usage = "xmake sdk [options]",
        description = "Create image file with specified components",
        options = {
            {"k", "kernel", "kv", nil, "Path to rtthread.bin file"},
            {"u", "uboot", "kv", nil, "Path to uboot.img file"},
            {"d", "fdt", "kv", nil, "Path to fdt file"},
            {"l", "loader", "kv", nil, "Path to idbloader.img file"},
            {"r", "rootfs", "kv", nil, "Path to rootfs.img file"}
        }
    }
task_end()

