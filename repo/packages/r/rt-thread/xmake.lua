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
-- 2024-12-9     zchenxiao       initial version
--

package("rt-thread")
do
    set_homepage("https://www.rt-thread.org/")
    set_description("rt-thread kernel")

    on_load(function(package)
        import("rt.private.build.rtflags")
        import("devel.git")
        import("net.http")
        local toolchainsdir = rtflags.get_package_info(package).toolchainsdir

        local config_file = ".config"
        local function read_config_file(config_file)
            local file = io.open(config_file, "r")
            if not file then
                error("cannot open: " .. config_file)
            end
            local content = file:read("*all")
            file:close()
            return content
        end

        -- 获取配置项的值
        local function get_config_values(config_file, vendor_key, model_key, board_key,kernel_key)
            local content = read_config_file(config_file)
            local vendor_pattern = vendor_key .. "([^%s=]*)=y"
            local model_pattern = model_key .. "([^%s=]*)=y"
            local board_pattern = board_key .. "([^%s=]*)=y"
            local kernel_pattern = kernel_key .. "([^%s=]*)=y"

            local vendor = content:match(vendor_pattern)
            local model = content:match(model_pattern)
            local board = content:match(board_pattern)
            local kernel_source = content:match(kernel_pattern)
            if kernel_source == "LOCAL" then
            local kernel_config = 'CONFIG_KERNEL_LOCAL_DIR="(.-)"'
            kernel_source = content:match(kernel_config)
        end
            return vendor, model, board, kernel_source
        end

        local vendor, model, board, kernel_source= get_config_values(config_file, "CONFIG_VENDOR_", "CONFIG_CHIP_MODEL_", "CONFIG_BOARD_", "CONFIG_KERNEL_SOURCE_")

        -- 获取 package 的安装目录
        local rt_install_dir = package:installdir()
        local rt_dir = path.join(rt_install_dir, "rt-thread")
        local env_dir = path.join(rt_install_dir, "env")
        print("Installing RT-Thread env to: " .. rt_install_dir)
        if not os.isdir(env_dir) then
            print("Cloning RT-Thread env repository into package directory...")
            git.clone("https://github.com/RT-Thread/env.git", {outputdir = env_dir})
            http.download("https://raw.githubusercontent.com/RT-Thread/env/master/install_ubuntu.sh", path.join(rt_install_dir, "install_ubuntu.sh"))
            os.exec("chmod +x " .. path.join(rt_install_dir, "install_ubuntu.sh"))
            os.exec(path.join(rt_install_dir, "install_ubuntu.sh"))
        else
            print("RT-Thread env repository already exists in package directory. Skipping clone.")
        end   

        if kernel_source == "GIT" then
            print("Installing RT-Thread to: " .. rt_install_dir)
            os.setenv("RT_THREAD_DIR", rt_dir)
            if not os.isdir(rt_dir) then
            print("Cloning RT-Thread repository into package directory...")
            git.clone("https://gitee.com/rtthread/rt-thread.git", {outputdir = rt_dir})
            else
                print("RT-Thread repository already exists in package directory. Skipping clone.")
            end
        else
            os.setenv("RT_THREAD_DIR", kernel_source)
            print("RT-Thread repository already exists in package directory. Skipping clone.")
    end
        
        if vendor or model or board then
            local parts = {}
            if vendor then table.insert(parts, vendor:lower()) end
            if model then table.insert(parts, model:lower()) end
            if board then table.insert(parts, board:lower()) end
            local bsp_dir = table.concat(parts, "_")
            local bsp_dir = bsp_dir:lower()  -- BSP小写
            bsp_dir = bsp_dir .. ".build"
            local bsp_file = bsp_dir .. ".lua"
            local bsp_packages = path.join(os.scriptdir(), "bsp")
            local bsp_path = path.join(bsp_packages,bsp_file)
            import(bsp_dir, {rootdir = bsp_packages})(toolchainsdir)

            else
                print("no_bsp")
            end
    end)

end
