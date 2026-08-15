[English](README.md) | **中文**

# smart-build 文档

本目录包含面向用户和扩展开发者的公开文档，描述当前源码树中已经提供的行为。

无语言后缀的英文文件为默认版本，中文翻译使用 `_zh.md` 后缀。每个页面均提供
对应语言版本的链接。

## 使用 smart-build

- [入门指南](getting-started_zh.md)
- [配置说明](configuration_zh.md)
- [命令参考](commands_zh.md)
- [故障排查](troubleshooting_zh.md)
- [兼容性与当前限制](compatibility_zh.md)

配置说明同时介绍工具链版本选择与下载、工作区菜单和按目标配置，包括独立 RT-Thread SCons 包的
native Kconfig 配置入口。
命令参考介绍任务开始前的规划进度、详细任务输出和 RT-Thread 内核详细构建。

命令参考同时说明可选的 Buildroot 软件包导入流程。Buildroot 只用于选择软件包，
导入后的软件包使用 smart-build 元数据，并在普通构建时下载上游源码。永不导入名单会
阻止 C 库、Linux 内核相关包、依赖 RT-Thread Smart 不具备的内核特性的软件包，
以及已经手工删除的导入包再次进入仓库。

## 扩展 smart-build

- [使用软件包](packages/using-packages_zh.md)
- [添加软件包](packages/creating-package_zh.md)
- [软件包描述文件参考](packages/package-yaml_zh.md)
- [支持的板卡](boards/supported-boards_zh.md)
- [添加板卡支持](boards/creating-board_zh.md)
- [根文件系统支持](rootfs/rootfs-options_zh.md)
- [添加根文件系统类型](rootfs/creating-rootfs_zh.md)
- [产品 Profile 提案](profiles/profile-proposals_zh.md)
- [常用嵌入式开源软件包待更新清单](profiles/embedded-open-source-packages_zh.md)

需求、内部架构、实施计划、评审记录和内部自动化指令不属于本公开文档的内容。
