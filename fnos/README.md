# MiAirX for fnOS

该目录包含 MiAirX 的飞牛 fnOS Docker 应用包装。它不会在 `.fpk` 中重复打包
Python 运行时，而是由飞牛的 Docker 项目资源拉取官方多架构镜像。

## 构建

安装官方 `fnpack` 1.2.3 或更高版本，然后在项目根目录执行：

```bash
fnpack build --directory fnos/miairx
```

构建产物位于 `fnos/miairx` 目录。将 `.fpk` 上传到飞牛应用中心进行安装。

## 网络要求

MiAirX 使用 `network_mode: host`，使 SSDP、mDNS、DLNA 和 AirPlay 可以直接访问
物理局域网。首次启动会根据 NAS 默认路由自动选择局域网 IPv4，不要求安装时手工
填写；多网卡设备可以随后在管理后台修改。如果启用了飞牛防火墙，需要放行：

- UDP 1900：SSDP 发现
- UDP 5353：mDNS / AirPlay 发现
- TCP 8200：DLNA 媒体服务
- TCP 8300：管理后台
- TCP 7000–7099：AirPlay RTSP 与音频流

配置保存在飞牛提供的 `${TRIM_PKGVAR}/conf` 持久化目录中，应用升级不会覆盖。

## 发布前检查

- 将 `manifest` 和 Compose 镜像标签更新为同一个 MiAirX 版本。
- 确认 GHCR 标签同时提供 `linux/amd64` 与 `linux/arm64` 镜像。
- 在 GitHub 仓库中设置 `DOCKERHUB_IMAGE` 变量以及 `DOCKERHUB_USERNAME`、
  `DOCKERHUB_TOKEN` Secrets，即可将相同标签同步发布到 Docker Hub。
- Docker Hub 镜像首次发布成功后，再将飞牛 Compose 的 `image` 切换到该仓库。
- 在真实 fnOS 设备上验证 `network_mode: host`、组播发现和应用中心启停流程。
