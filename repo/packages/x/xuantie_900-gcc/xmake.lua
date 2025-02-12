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
-- Copyright (C) 2023-2025 RT-Thread Development Team
--
-- @author      zhangxianshun
-- @file        xmake.lua
--
-- Change Logs:
-- Date           Author          Notes
-- ------------   -------------   -----------------------------------------------
-- 2025-02-17     zhangxianshun   initial version
--
package("xuantie_900-gcc")
do
    set_kind("toolchain")
    set_homepage("https://www.xrvm.cn/")
    set_description("xuantie_900-gcc cross compiler for linux.")

    add_urls("https://kendryte-download.canaan-creative.com/k230/toolchain/Xuantie-900-gcc-linux-5.10.4-glibc-x86_64-V$(version).tar.bz2")
    add_versions("2.6.0", "17decb02130b8d79a1eb8c2126e17749fbea603dae7d95f20cd4ab411f3f1a41")
    add_versions("2.10.1", "15d91b6613bb92b4685c474972785a49b6f6ee9fbeefa1faef180e86a2f7e2f3")

    on_load(function(package)
        assert(is_host("linux"), 'The current cross-compilation toolchain only supports linux environments.')
    end)   

    on_install("@linux|x86_64", function(package)
        os.vcp("*", package:installdir(), {rootdir = ".", symlink = true})
        package:addenv("PATH", "bin")
    end)

    on_test(function(package)
        local gcc = "riscv64-unknown-linux-gnu-gcc"
        local file = os.tmpfile() .. ".c"
        io.writefile(file, "int main(int argc, char** argv) {return 0;}")
        os.vrunv(gcc, {"-c", file})
    end)
end
