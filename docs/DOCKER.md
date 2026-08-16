# Docker 指南

MiAirX 的 Docker 镜像适合 Linux 主机、Linux NAS 和能够真正使用宿主机网络的环境。Docker Desktop for Windows/macOS 通常无法把 SSDP/mDNS 组播透明带进物理局域网，不是推荐部署方式。

## 为什么必须使用 host 网络

MiAirX 不是普通的纯 HTTP 服务：

- DLNA 使用 UDP 1900 SSDP 组播发现设备。
- AirPlay 使用 UDP 5353 mDNS 广播服务。
- AirPlay 为每台音箱分配两个固定、连续的 TCP 端口，默认从 7000 开始。
- 音箱还需要反向访问 MiAirX 提供的媒体 URL。

Docker 网桥和端口映射不能完整替代这些行为，因此必须使用：

```yaml
network_mode: host
```

或者：

```bash
docker run --network host ...
```

## 使用 Docker Compose

仓库提供了 [docker-compose.yml](../docker-compose.yml)。建议把凭据放在本地 `.env` 中：

```dotenv
MI_USER=your-xiaomi-account
MI_PASS=your-password
MI_DID=
MIAIR_HOSTNAME=192.168.1.10
MIAIR_AIRPLAY_PORT_START=7000
```

确认 `MIAIR_HOSTNAME` 是 Linux 宿主机真实的局域网 IPv4，然后启动：

```bash
mkdir -p conf
docker compose up -d
docker compose logs -f miairx
```

如果不提供 `MI_DID`，可以在管理台中选择设备：

```text
http://Linux宿主机IP:8300
```

保存设备后执行：

```bash
docker compose restart miairx
```

## 使用 docker pull 和 docker run

`docker pull` 只下载镜像，不会启动容器或修改宿主机防火墙：

```bash
docker pull jxydk/miairx:master
```

然后创建配置目录并启动：

```bash
mkdir -p conf

docker run -d \
  --name miairx \
  --network host \
  --restart unless-stopped \
  -e MI_USER='your-account' \
  -e MI_PASS='your-password' \
  -e MIAIR_HOSTNAME='192.168.1.10' \
  -e MIAIR_AIRPLAY_PORT_START='7000' \
  -v "$(pwd)/conf:/app/conf" \
  jxydk/miairx:master
```

## 镜像中的前端

Dockerfile 使用多阶段构建：

1. `node:24-alpine` 安装锁定的 pnpm 依赖。
2. Vite 构建 React 管理台。
3. 编译结果复制到 Python 镜像的 `miairx/web/static/app/`。
4. 最终 `python:3.12-slim` 镜像安装 MiAirX 和 FFmpeg。

最终运行镜像不包含 Node.js、pnpm、前端源码或测试依赖。容器中的根路径 `/` 是新版 React 管理台，`/legacy` 是旧管理页。

## AirPlay 固定端口段

默认从 TCP 7000 开始，每台启用音箱按 DID 配置顺序占用两个端口：

| 音箱序号 | RTSP | 音频 HTTP |
|---:|---:|---:|
| 1 | 7000 | 7001 |
| 2 | 7002 | 7003 |
| 3 | 7004 | 7005 |

镜像声明了 TCP 7000–7099，可覆盖 50 台音箱。使用 `network_mode: host` 时 `EXPOSE` 只是镜像元数据，真正是否可访问由宿主机防火墙决定。

如果默认端口被占用，可在 `.env` 中整体平移：

```dotenv
MIAIR_AIRPLAY_PORT_START=17000
```

此时第一台音箱使用 17000/17001，防火墙也应改为相应端口段。

## 宿主机防火墙

使用 host 网络时，MiAirX 直接占用宿主机端口。`docker pull`、Dockerfile 的 `EXPOSE` 和 `docker run` 都不会自动创建宿主机防火墙规则。

最小规则如下：

| 功能 | 端口 |
|---|---|
| SSDP/DLNA 发现 | UDP 1900 |
| DLNA 与媒体代理 | TCP 8200 |
| Web 管理台 | TCP 8300 |
| AirPlay mDNS | UDP 5353 |
| AirPlay 固定端口段 | TCP 7000–7099 |

SSDP 还涉及 `239.255.255.250:1900` 组播查询、单播响应和 NOTIFY 广播；普通 `-p 1900:1900/udp` 无法替代 host 网络。可直接复制的 UFW、firewalld、Windows、NAS 规则和 `tcpdump` 诊断命令见 [防火墙与局域网发现](FIREWALL.md)。

## 本地构建

```bash
docker build -t miairx:dev .

docker run --rm \
  --network host \
  -v "$(pwd)/conf:/app/conf" \
  miairx:dev
```

构建会从 `frontend/pnpm-lock.yaml` 安装依赖，并重新生成静态资源；不会依赖工作区中已经构建好的前端文件。

## 更新

```bash
docker compose pull
docker compose up -d
docker image prune
```

`master` 标签跟随主分支。正式版本也会生成语义化版本标签，例如 `1.0.4` 和 `1.0`。对稳定部署，建议固定完整版本标签。

## 健康检查

镜像会访问：

```text
http://127.0.0.1:8300/api/status
```

查看状态：

```bash
docker inspect --format '{{json .State.Health}}' miairx
```

健康检查成功只表示 Web 服务可响应，不代表手机一定能通过组播发现音箱。

## 排障

### 管理台能打开，但投屏列表没有设备

依次确认：

1. 容器使用 `host` 网络。
2. `MIAIR_HOSTNAME` 是宿主机 LAN IPv4，而不是容器地址或 `127.0.0.1`。
3. 宿主机和手机在同一子网，没有 AP 隔离。
4. 防火墙允许 UDP 1900、UDP 5353、TCP 8200/8300 和配置的 AirPlay TCP 端口段。
5. 路由器没有禁用组播或 IGMP。

### 日志出现 IPv6 `Network is unreachable`

当前实现将 Zeroconf 广播限制为 IPv4。若新镜像仍持续打印向 `::1:5353` 发送失败，先确认容器不是旧版本：

```bash
docker inspect miairx --format '{{.Image}}'
docker compose pull
docker compose up -d --force-recreate
```

### 账号配置每次重启丢失

确认配置卷实际挂载：

```bash
docker inspect miairx --format '{{json .Mounts}}'
ls -la ./conf
```

配置文件应该位于宿主机 `./conf/config.json`。

### 端口占用

`host` 网络会直接占用宿主机 8200/8300 和 AirPlay 端口段。停止旧实例或修改端口：

```dotenv
MIAIR_DLNA_PORT=18200
MIAIR_WEB_PORT=18300
MIAIR_AIRPLAY_PORT_START=17000
```

修改 DLNA 端口后，仍需保证音箱可以访问 `MIAIR_HOSTNAME:新端口`。

### 大文件无声

大文件会绕过内存缓冲，直接从上游流式转发给音箱。检查：

- 上游 URL 能否从容器访问。
- 上游是否返回正常的状态码和 `Content-Type`。
- 音箱能否访问宿主机 `hostname:dlna_port`。
- 源站是否要求容器没有的 Cookie、Referer 或鉴权头。

容器内可进行最小连通性检查：

```bash
docker exec miairx python -c "import urllib.request; print(urllib.request.urlopen('https://example.com/audio.mp3').status)"
```

不要在公开日志中粘贴带签名或账号信息的真实媒体 URL。
