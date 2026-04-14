# Smart Build 文档中心

欢迎使用 **Smart Build** —— 基于 BitBake/OpenEmbedded 构建系统的 RT-Thread Smart 一站式编译方案。

本文档旨在帮助嵌入式开发工程师快速上手 smart-build，并深入理解其架构设计与扩展方式。

## 文档目录

| 章节 | 文件 | 说明 |
| --- | --- | --- |
| 第一章 | [上手指南](01-getting-started.md) | 从零开始搭建环境、编译并运行一个完整的 RT-Smart 系统 |
| 第二章 | [核心概念](02-core-concepts.md) | BitBake 构建系统核心概念与 RT-Thread Smart 相关术语 |
| 第三章 | [构建流程](03-build-flow.md) | 整体构建流程的宏观说明，帮助建立全局视角 |
| 第四章 | [示例：增加板卡支持](04-example-add-board.md) | 手把手教你为新硬件平台添加 BSP 支持 |
| 第五章 | [示例：增加全新程序](05-example-add-program.md) | 从零编写一个用户态应用程序并集成到构建系统 |
| 第六章 | [示例：增加软件包](06-example-add-package.md) | 将开源软件包或第三方应用集成到 smart-build |
| 附录 | [文档维护规范](CONTRIBUTING.md) | 文档编写要求、风格指南与维护流程 |

## 快速链接

- **项目仓库**: [https://github.com/RT-Thread/smart-build](https://github.com/RT-Thread/smart-build)
- **RT-Thread 官网**: [https://www.rt-thread.org](https://www.rt-thread.org)
- **BitBake 手册**: [https://docs.yoctoproject.org/bitbake/](https://docs.yoctoproject.org/bitbake/)

## 适用对象

- 希望基于 RT-Thread Smart 进行产品开发的嵌入式工程师
- 需要为新硬件平台适配 RT-Smart 的 BSP 开发者
- 希望了解 BitBake 构建体系并应用于 RTOS 场景的开发者
