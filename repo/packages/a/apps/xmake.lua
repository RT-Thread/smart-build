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
package("apps")
do
    set_homepage("https://www.rt-thread.org/")
    set_description("rt-thread apps")

    on_load(function (package)
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

        -- 获取选中的应用列表
        local function get_selected_apps(config_file)
            local content = read_config_file(config_file)
            local app_pattern = "CONFIG_APP_([%w_]+)=y" 
            local apps = {}
            for app in content:gmatch(app_pattern) do
                table.insert(apps, app:lower())  -- 应用名称转为小写
            end
            return apps
        end

        local apps = get_selected_apps(config_file)

        -- 为每个选中的应用添加构建规则
        if #apps > 0 then
            for _, app in ipairs(apps) do
                print("Building app: " .. app)
                    if app == "busybox" then
                        package:add("deps","busybox")
                    elseif app == "cpp" then
                        package:add("deps","cpp")
                    elseif app == "ffmpeg" then
                        package:add("deps","ffmpeg")
                    elseif app == "hello" then
                        package:add("deps","hello")
                    elseif app == "micropython" then
                        package:add("deps","micropython")
                    elseif app == "player" then
                        package:add("deps","player")
                    elseif app == "shm_ping" then
                        package:add("deps","shm_ping")
                    elseif app == "shm_pong" then
                        package:add("deps","shm_pong")
                    elseif app == "smart-fetch" then
                        package:add("deps","smart-fetch")
                    elseif app == "umailbox" then
                        package:add("deps","umailbox")
                    elseif app == "webclient" then
                        package:add("deps","webclient")
                    elseif app == "webserver" then
                        package:add("deps","webserver")
                    elseif app == "zlib" then
                        package:add("deps","zlib_app")
                    end
                end
        else
            print("No apps selected.")
        end

    end)
    on_install("cross@linux", function(package)

    end)
end
