# MiAirX 项目状态

本文是当前能力快照，不再使用“全部完成”表示没有后续工作。MiAirX 的核心链路可用，但协议兼容、网络环境和不同音箱型号仍需持续回归。

## 已完成

- DLNA/UPnP 设备发布、SOAP 控制和 GENA 事件
- 多音箱独立渲染器和稳定 UDN
- 播放、暂停、停止、音量、位置和 Seek
- 本地影子状态、宽限期与过期自动切歌保护
- 小文件内存缓冲和大文件流式代理
- Range、媒体 token、buffer 回收和 FFmpeg Seek
- AirPlay 1 / RAOP 接收与 IPv4 mDNS 广播
- 账号密码和 Cookie 登录
- React/TypeScript 响应式管理台
- 设备选择和完整配置持久化
- wheel/sdist 静态资源打包
- Linux host-network Docker 多阶段镜像
- Python、Vitest 和 Playwright 自动化测试

## 当前限制

- 管理台没有访问认证
- Docker Desktop 不适合作为组播部署环境
- AirPlay 兼容性弱于 DLNA
- DRM 或强鉴权媒体无法代理
- 配置变更需要手动重启
- 少量历史配置字段当前为保留项

## 当前验证基线

最近一次前端重写验证包括：

- Python：103 项测试通过
- Vitest：3 项测试通过
- Playwright：桌面端和移动端 2 项冒烟测试通过
- TypeScript 严格类型检查通过
- Vite 生产构建通过
- wheel 包含新版管理台静态资源

测试数量会随项目变化，最终以 CI 结果为准。

## 相关文档

- [快速开始](../README.md)
- [配置参考](CONFIGURATION.md)
- [Docker 指南](DOCKER.md)
- [架构说明](ARCHITECTURE.md)
- [开发指南](DEVELOPMENT.md)
- [项目交接](PROJECT_HANDOVER.md)
