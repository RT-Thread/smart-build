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
package("shm_ping")
do
    set_homepage("https://github.com/RT-Thread/userapps")
    set_description("userapps")

    add_urls("https://github.com/RT-Thread/userapps.git")

    on_install("cross@linux,windows", function(package)
        local sourcedir_files = path.join(os.curdir(),"apps", "shm_ping", "*")
        local bakdir = path.join(os.curdir())
        print("sourcedir_files: " .. sourcedir_files)
        print("bakdir: " .. bakdir)
        
        os.cp(sourcedir_files, bakdir)

        import("package.tools.xmake").install(package)
    end)

end
