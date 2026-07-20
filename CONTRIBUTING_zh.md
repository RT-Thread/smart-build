[English](CONTRIBUTING.md) | **中文**

# 为 smart-build 做贡献

贡献内容应将 smart-build 作为独立的 RT-Thread Smart 构建系统进行描述，
并保持其当前行为。

## 修改代码前

- 针对目标机器运行 `./smart-build doctor`。
- 不要提交生成产物、下载内容、外部 RT-Thread 源码、工具链、`.config`
  和本地自动化配置。
- 遵循相邻 Python、Kconfig、YAML 和构建脚本的风格。
- 对预期内的失败使用 `SmartBuildError`，并提供稳定的用户可见错误码。
- 创建可执行的构建任务前，校验外部路径和元数据。

## 仓库约定

- machine、rootfs 和 package 名称使用小写英文和连字符。
- 板卡目录名必须与其 `MACHINE` 值和板卡描述名称一致。
- 软件包元数据保存在 `packages/<name>/package.yaml`。
- 生成的软件包 Kconfig 文件必须与软件包元数据一致，不得手动编辑。
- RT-Thread 内核软件包及其版本属于板卡内核 defconfig 和 Env 软件包索引。
  不要在 smart-build 内核任务中添加软件包下载或源码复制逻辑。
- 板卡内核 overlay 不得修改 BSP 的 `packages/` 目录。
- 构建任务只能通过 `BuildPaths` 所管理的路径写入文件。
- 公开文档描述已实现的行为及当前限制；不得包含需求、内部设计文档、
  实施计划、路线图、内部评审记录或自动化指令。

## 测试

先运行范围最小的相关 pytest 测试。修改共享任务、调度器、缓存、manifest、
配置、机器元数据或跨构建域契约时，应运行完整测试套件：

```sh
python -m pytest
```

修改真实构建流程时，运行受影响的目标：

```sh
./smart-build build <target>
```

对于支持 QEMU 的机器，还应运行：

```sh
./smart-build qemu-smoke
```

确认 RT-Thread Smart 已进入 shell，并检查完整日志中的错误，不能只依赖命令
退出状态。

## 文档变更

修改命令、配置字段、软件包契约、板卡契约、rootfs 契约或用户可见限制时，
应在同一个贡献中更新 `README.md`、`README_zh.md`、`docs/README.md`、
`docs/README_zh.md` 以及相关用户指南的中英文版本。

## 提交和 Pull Request

提交标题使用简洁的祈使句，可按需添加范围前缀，例如：

```text
docs: add board support guide
fix: validate qemu rootfs selection
```

每个提交只聚焦一个主题。Pull Request 应说明受影响的 machine、package 或
构建域，列出实际运行的命令，并说明兼容性或 manifest 变更。QEMU 行为发生
变化时，应附上相关的 QEMU 启动输出。
