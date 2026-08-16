# MiAirX 文档

这里是 MiAirX 的用户、部署和开发文档入口。根目录 [README](../README.md) 负责快速上手，下面的文档提供细节。

## 使用与部署

| 文档 | 适合谁 | 内容 |
|---|---|---|
| [配置参考](CONFIGURATION.md) | 所有用户 | 配置文件、环境变量、端口和敏感信息 |
| [Docker 指南](DOCKER.md) | Linux / NAS 用户 | host 网络、Compose、镜像构建和排障 |
| [防火墙与局域网发现](FIREWALL.md) | Docker、NAS 与本机部署用户 | SSDP/mDNS 原理、UFW、firewalld、Windows 和诊断命令 |
| [通俗原理](SIMPLE.md) | 初次接触 DLNA 的用户 | 用非技术语言解释 MiAirX |

## 开发与维护

| 文档 | 内容 |
|---|---|
| [架构说明](ARCHITECTURE.md) | 组件边界、协议流、媒体策略和前端集成 |
| [开发指南](DEVELOPMENT.md) | 本地环境、测试、构建、CI 和发版检查 |
| [项目交接](PROJECT_HANDOVER.md) | 当前状态、关键约束和维护清单 |
| [项目状态](COMPLETE.md) | 当前已完成能力、限制和验证基线 |

## 历史资料

以下文档保留用于追溯设计过程，不再作为当前行为的唯一依据：

- [历史修复日志](REWRITE_LOG.md)
- [历史性能优化提案](OPTIMIZATION.md)

遇到历史文档与代码、测试或当前文档冲突时，以当前代码、测试和本目录中的配置/架构/开发文档为准。

## 文档维护约定

- 用户可见行为变化时同步更新根 README。
- 配置字段变化时同步更新 `config-example.json` 和 `CONFIGURATION.md`。
- Docker 构建或网络策略变化时同步更新 `Dockerfile`、`docker-compose.yml`、`DOCKER.md` 和 `FIREWALL.md`。
- 前端依赖或构建流程变化时同步更新 `frontend/package.json` 与 `DEVELOPMENT.md`。
- 不在文档、截图、示例或测试夹具中放入真实账号、Cookie、DID 和局域网信息。
