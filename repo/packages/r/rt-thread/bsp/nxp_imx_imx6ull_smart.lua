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
-- nxp_imx_imx6ull_smart.lua
function build(toolchainsdir)
    os.setenv("RTT_CC_PREFIX", "aarch64-linux-musleabi-")
    os.setenv("RTT_EXEC_PATH",     print(toolchainsdir))
    os.setenv("PATH", os.getenv("RTT_EXEC_PATH") .. ":" .. os.getenv("PATH"))

    print("Environment configured:")
    print("RTT_CC_PREFIX=" .. os.getenv("RTT_CC_PREFIX"))
    print("RTT_EXEC_PATH=" .. os.getenv("RTT_EXEC_PATH"))
    print("Starting build process...")
    local rt_dir = os.getenv("RT_THREAD_DIR")
    local build = path.join(rt_dir,"/bsp/nxp/imx/imx6ull-smart")
    local build_dir = os.curdir()
    os.cd(build)
    os.exec("scons --menuconfig")
    os.exec("scons")
    os.execv("cp", {build .. "/rtthread.bin", build_dir})
end

