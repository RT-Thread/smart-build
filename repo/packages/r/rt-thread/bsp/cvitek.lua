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
local TOOLCHAIN_URL = "https://occ-oss-prod.oss-cn-hangzhou.aliyuncs.com/resource//1705395512373/Xuantie-900-gcc-elf-newlib-x86_64-V2.8.1-20240115.tar.gz"
local TOOLCHAIN_ARCHIVE = "Xuantie-900-gcc-elf-newlib-x86_64-V2.8.1-20240115.tar.gz"
local TOOLCHAIN_PATH = "/opt/Xuantie-900-gcc-elf-newlib-x86_64-V2.8.1"

-- 工具链
function download_and_extract_toolchain()
    -- 如果工具链已经存在则跳过下载和解压
    if os.isdir(TOOLCHAIN_PATH) then
        print("Toolchain already exists at: " .. TOOLCHAIN_PATH)
        return
    end
    print("Downloading toolchain...")
    http.download(TOOLCHAIN_URL, TOOLCHAIN_ARCHIVE)
    print("Extracting toolchain...")
    archive.extract(TOOLCHAIN_ARCHIVE, "/opt")
    os.rm(TOOLCHAIN_ARCHIVE)
    print("Toolchain is ready at: " .. TOOLCHAIN_PATH)
end

-- 配置环境变量
function configure_environment()
    os.setenv("RTT_CC_PREFIX", "riscv64-unknown-elf-")
    os.setenv("RTT_EXEC_PATH", path.join(TOOLCHAIN_PATH, "bin"))
    print("Environment configured:")
    print("RTT_CC_PREFIX=" .. os.getenv("RTT_CC_PREFIX"))
    print("RTT_EXEC_PATH=" .. os.getenv("RTT_EXEC_PATH"))
end

function toolchain_module(target)
    download_and_extract_toolchain()
    configure_environment()
end

-- 编译
function build()
    os.cd("/home/rtt/.xmake/packages/r/rt-thread/latest/730a21d91cc8433ebae80c7f6d80c197/rt-thread/bsp/cvitek")
    -- 进入大核目录并编译
    print("Building for big core (cv18xx_risc-v)...")
    os.cd("cv18xx_risc-v")
    os.execv("scons")
    os.cd("..")
    
    -- 进入小核目录并编译
    print("Building for little core (c906_little)...")
    os.cd("c906_little")
    os.exec("scons")
    os.cd("..")
    
    print("Build completed. Output files located in bsp/cvitek/output.")
end

-- -- 依赖安装提示
-- toolchain_module.print_dependencies = function()
--     print("Please ensure you have installed the dependencies:")
--     print("sudo apt install -y scons libncurses5-dev device-tree-compiler")
-- end

