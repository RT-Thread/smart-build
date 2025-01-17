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
add_rules("mode.debug", "mode.release")

add_requires("apps")

add_requires("xmake::rt-thread", {optional = true})

target("image")
    set_kind("phony")

    if os.isdir("~/.env/tools/scripts") then
        local current_path = os.getenv("PATH")
        current_path = "~/.env/tools/scripts" .. ":" .. current_path
        add_runenvs("PATH", current_path)
    end

    add_packages("apps")
    add_packages("rt-thread")

    on_build(function (target)
        print("Building image target...")
    end)

    after_build(function (target)
        os.exec("xmake smart-rootfs")
        os.exec("xmake smart-image")
        os.exec("xmake sdk")
    end)

target_end()