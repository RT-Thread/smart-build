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
-- Date           Author         Notes
-- ------------  ----------     -----------------------------------------------
-- 2025-2-12     zhangxianshun   initial version
--

import("core.base.option")

local function writetofile(file, line)
    local file = io.open(file, "a")
    if file then
        file:print("    " .. line)
        file:close()
    end
end

local function generatefile(file)
    local file_read = io.open(file, "r")
    if file_read then
        local data = file_read:read("*all")
        file_read:close()
        local file_write = io.open(file, "w")
        if file_write then
            file_write:write("{\n")
            file_write:write(data)
            file_write:write("}\n")
            file_write:close()
        end
    end
end

local function parsing_config(line)
    local key, value =  line:match('CONFIG_([^=]+)%s*=%s*(.-)%s*$')
    if key and value then
        key = key:lower()
        return key .. " = " .. value .. ","
    end
end

local function get_xmake_config(path_config)
    local xmake_config = path.join(os.tmpdir(), "xmake_config")
    if os.isfile(xmake_config) then
        os.rm(xmake_config)
    end
    local lines = io.lines(path_config)
    local begin_record = false
    for line in lines do
        if line:startswith("# k230") and line:endswith("config") then
            begin_record = true
        end

        if begin_record and not line:startswith("#") then
            writetofile(xmake_config,parsing_config(line))
        end

        if line:startswith("# end of") and line:endswith("config") then
            begin_record = false
        end
    end

    generatefile(xmake_config)
    return xmake_config
end

function main()
    local import_path = option.get("import")
    if import_path then
        if not path.is_absolute(import_path) then
            import_path = path.absolute(import_path, os.curdir())
        end
    else
        cprint("${red}error:${clear} Input path error!")
    end
    if not os.isfile(import_path) then
        cprint("${red}error:${clear} Invalid file input!")
    end

    local tmp_xamke_config = get_xmake_config(import_path)
    if not os.isfile(tmp_xamke_config) then
        cprint("${red}error:${clear} Invalid file output!")
    end
    os.execv("xmake", {"f","--import=" .. tmp_xamke_config})

end
