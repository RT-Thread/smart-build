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
-- Copyright (C) 2022-2023 RT-Thread Development Team
--
-- @author      zhangxianshun
-- @file        config.lua
--
-- Change Logs:
-- Date           Author       Notes
-- ------------   ----------   -----------------------------------------------
-- 2025-02-11     zhangxianshun       initial version
--

-- option("defconfig")
--     set_default("k230_defconfig")
--     set_showmenu(true)
--     set_description("Set defconfig",
--                 "    - k230_defconfig")
-- option_end()

-- option("crux")
--     set_default("k230")
--     set_showmenu(true)
--     set_description("Set SOC name",
--                         "    - k230")
-- option_end()

option("xuantie_ver")
    set_default("2.6.0")
    set_showmenu(true)
    set_description("toolchain version",
                        "    - 2.6.0",
                        "    - 2.10.1")
option_end()