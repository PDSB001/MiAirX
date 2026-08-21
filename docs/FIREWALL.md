# 防火墙与局域网发现

本文适用于以下部署方式：

- Linux 主机直接运行 MiAirX
- Linux、NAS 或软路由通过 `docker pull` 获取镜像后手动运行
- Docker Compose 使用 `network_mode: host`

Docker Desktop for Windows/macOS 通常无法把 SSDP 和 mDNS 组播透明接入物理局域网，不建议用于正式部署。

## 先看结论

MiAirX 只应对可信局域网开放，不要在路由器上配置公网端口转发。

| 功能 | 方向 | 协议/端口 | 是否必须 |
|---|---|---|---|
| SSDP/DLNA 发现 | 局域网进入宿主机 | UDP 1900 | 使用 DLNA 时必须 |
| DLNA 描述、SOAP 控制和媒体代理 | 局域网进入宿主机 | TCP 8200 | 使用 DLNA 时必须 |
| Web 管理台和 JSON API | 局域网进入宿主机 | TCP 8300 | 使用管理台时必须 |
| AirPlay mDNS 发现 | 局域网双向组播 | UDP 5353 | 使用 AirPlay 时必须 |
| AirPlay RTSP 与音频 HTTP | 局域网进入宿主机 | TCP 7000 起 | 使用 AirPlay 时必须 |

默认 AirPlay 端口按启用音箱的顺序固定分配：

```text
第 1 台：7000 / 7001
第 2 台：7002 / 7003
第 3 台：7004 / 7005
```

端口段终点的计算方式：

```text
airplay_port_start + 启用音箱数量 × 2 - 1
```

例如 3 台音箱从 7000 开始，只需 TCP 7000–7005。为了以后增加音箱，也可以一次放行 TCP 7000–7099，这能覆盖 50 台音箱。

## 为什么 SSDP 不只是“开放 1900”

SSDP 使用 IPv4 组播地址 `239.255.255.250`：

```text
手机/播放器的随机 UDP 端口
        │ M-SEARCH 查询
        ▼
239.255.255.250:1900
        │
        ▼
MiAirX 监听 0.0.0.0:1900
        │ 单播响应
        ▼
手机/播放器的随机 UDP 端口
```

MiAirX 还会向 `239.255.255.250:1900` 定期发送 `NOTIFY` 广播。因此：

- 入站必须允许局域网访问 UDP 1900。
- 系统默认允许出站时，不需要额外规则。
- 如果宿主机采用严格的出站拒绝策略，还要允许发往组播地址 UDP 1900，以及从 MiAirX 返回局域网客户端随机 UDP 端口的响应。
- 普通 Docker bridge 的 `-p 1900:1900/udp` 不能替代组播接入，必须使用 host 网络。

## `docker pull` 手动部署

`docker pull` 只下载镜像，不会启动容器，也不会修改防火墙。Dockerfile 中的 `EXPOSE` 也只是镜像元数据。

准备 `.env`：

```dotenv
MI_USER=your-xiaomi-account
MI_PASS=your-password
MI_DID=
MIAIR_HOSTNAME=192.168.1.10
MIAIR_DLNA_PORT=8200
MIAIR_WEB_PORT=8300
MIAIR_AIRPLAY_PORT_START=7000
```

其中 `MIAIR_HOSTNAME` 必须是宿主机真实的局域网 IPv4，不能填写 `127.0.0.1`、容器地址或 Docker 网桥地址。

拉取并启动：

```bash
docker pull jxydk/miairx:1.6.2
mkdir -p ./conf

docker run -d \
  --name miairx \
  --network host \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/conf:/app/conf" \
  jxydk/miairx:1.6.2
```

使用 `--network host` 时不要添加 `-p`。端口由 MiAirX 直接监听在宿主机上。

更新已有容器：

```bash
docker pull jxydk/miairx:1.6.2
docker rm -f miairx

docker run -d \
  --name miairx \
  --network host \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/conf:/app/conf" \
  jxydk/miairx:1.6.2
```

只要 `/app/conf` 已挂载到宿主机，重建容器不会删除配置。如果旧容器没有挂载配置目录，删除前先备份：

```bash
docker cp miairx:/app/conf ./conf
```

## UFW

以下示例假设局域网网段为 `192.168.1.0/24`。务必替换成实际网段。

### 默认允许出站

大多数 UFW 安装默认允许出站，只需添加入站规则：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 1900 proto udp comment 'MiAirX SSDP'
sudo ufw allow from 192.168.1.0/24 to any port 8200 proto tcp comment 'MiAirX DLNA'
sudo ufw allow from 192.168.1.0/24 to any port 8300 proto tcp comment 'MiAirX Web'
sudo ufw allow from 192.168.1.0/24 to any port 5353 proto udp comment 'MiAirX mDNS'
sudo ufw allow from 192.168.1.0/24 to any port 7000:7099 proto tcp comment 'MiAirX AirPlay'

sudo ufw reload
sudo ufw status numbered
```

如果只使用 DLNA，可以省略 UDP 5353 和 TCP 7000–7099。如果不需要从其他设备访问管理台，也可以不开放 TCP 8300。

### 默认拒绝出站

先查看策略：

```bash
sudo ufw status verbose
```

如果显示 `Default: deny (outgoing)`，还需要允许 SSDP/mDNS 组播和 MiAirX 的业务出站连接：

```bash
sudo ufw allow out to 239.255.255.250 port 1900 proto udp comment 'MiAirX SSDP multicast'
sudo ufw allow out to 224.0.0.251 port 5353 proto udp comment 'MiAirX mDNS multicast'
sudo ufw allow out from any port 1900 to 192.168.1.0/24 proto udp comment 'MiAirX SSDP replies'
sudo ufw allow out from any port 5353 to 192.168.1.0/24 proto udp comment 'MiAirX mDNS replies'
```

还必须按宿主机安全策略允许访问小米云和媒体源。MiAirX 需要发起 HTTPS 请求，过度严格的出站规则会造成登录失败或大文件无声。

## firewalld

先确认承载局域网的网卡位于可信 zone，例如 `home`：

```bash
sudo firewall-cmd --get-active-zones
```

在 `home` zone 开放端口：

```bash
sudo firewall-cmd --permanent --zone=home --add-port=1900/udp
sudo firewall-cmd --permanent --zone=home --add-port=8200/tcp
sudo firewall-cmd --permanent --zone=home --add-port=8300/tcp
sudo firewall-cmd --permanent --zone=home --add-port=5353/udp
sudo firewall-cmd --permanent --zone=home --add-port=7000-7099/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --zone=home --list-ports
```

如果局域网网卡不在 `home`，应替换成实际 zone；不要为了省事把公网接口整体加入 trusted zone。

## Windows 防火墙

本节适用于 Windows 直接运行 MiAirX。Docker Desktop 的组播限制不能通过单纯增加防火墙规则解决。

以管理员身份打开 PowerShell：

```powershell
New-NetFirewallRule -DisplayName 'MiAirX SSDP' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 1900 -Profile Private -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName 'MiAirX DLNA' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8200 -Profile Private -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName 'MiAirX Web' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8300 -Profile Private -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName 'MiAirX mDNS' -Direction Inbound -Action Allow -Protocol UDP -LocalPort 5353 -Profile Private -RemoteAddress LocalSubnet
New-NetFirewallRule -DisplayName 'MiAirX AirPlay' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7000-7099 -Profile Private -RemoteAddress LocalSubnet
```

这些规则只对“专用”网络配置文件和本地子网生效。确认当前网络不是“公用”：

```powershell
Get-NetConnectionProfile
```

查看规则：

```powershell
Get-NetFirewallRule -DisplayName 'MiAirX*' | Format-Table DisplayName,Enabled,Profile,Direction,Action
```

若端口发生变化，应同步修改或重建对应规则。不要额外按整个 `python.exe` 向所有网络开放入站连接。

## NAS 防火墙

群晖、威联通等 NAS 通常通过管理界面设置防火墙。创建“来源为本地子网”的允许规则：

```text
UDP 1900
TCP 8200
TCP 8300
UDP 5353
TCP 7000-7099
```

规则必须加在 NAS 宿主机，而不是容器内部。若 NAS 提供“允许 Docker 应用”选项，也仍需确认组播 UDP 1900/5353 没有被系统级防火墙拦截。

## 修改默认端口

可以在 `.env` 中修改：

```dotenv
MIAIR_DLNA_PORT=18200
MIAIR_WEB_PORT=18300
MIAIR_AIRPLAY_PORT_START=17000
```

此时对应的入站规则应改为：

```text
TCP 18200
TCP 18300
TCP 17000 起，每台音箱两个端口
UDP 1900 和 UDP 5353 保持不变
```

端口、主机地址或音箱列表修改后必须重启 MiAirX。

## 旧配置兼容

旧版 `conf/config.json` 可以直接挂载给新版镜像：

- 缺少 `airplay_port_start` 时自动使用默认值 7000。
- 已有账号、Cookie、DID、音箱信息、8200/8300 等配置保持不变。
- `MIAIR_AIRPLAY_PORT_START` 环境变量可以覆盖配置文件值。
- 新版保存配置后会把新字段写入 `config.json`。

环境变量优先级高于配置文件。因此如果 `.env` 固定写了某个端口，在管理台修改同一字段并重启后，仍会被 `.env` 覆盖。

## 验证与排障

检查容器是否使用 host 网络：

```bash
docker inspect miairx --format '{{.HostConfig.NetworkMode}}'
```

期望输出：

```text
host
```

检查端口监听：

```bash
sudo ss -lntup | grep -E ':(1900|5353|8200|8300|7000|7001)\b'
```

观察 SSDP 报文：

```bash
sudo tcpdump -ni any 'udp port 1900'
```

正常发现时应该看到发送到 `239.255.255.250.1900` 的 `M-SEARCH`，以及 MiAirX 返回客户端随机端口的响应。

查看日志：

```bash
docker logs --tail 200 miairx
```

### 端口已经开放但仍无法发现

继续检查：

1. 手机、播放器、音箱和宿主机是否在同一子网。
2. 路由器是否开启访客网络、AP 隔离或无线客户端隔离。
3. VPN、Tailscale、代理软件是否改变了默认网卡或组播路由。
4. `MIAIR_HOSTNAME` 是否为物理局域网 IPv4。
5. Docker 是否确实使用 host 网络。
6. 路由器或交换机的 IGMP Snooping 是否错误丢弃组播。
7. 宿主机上是否已有其他程序占用 UDP 1900、TCP 8200 或 TCP 8300。

### 管理台能打开但 DLNA 找不到

TCP 8300 正常只证明 Web 服务可用。SSDP 依赖 UDP 1900 组播，两者是独立链路。重点检查 `tcpdump` 是否能看到 `M-SEARCH`，以及 Docker host 网络和 AP 隔离。

### DLNA 能发现但播放无声

发现成功只证明 UDP 1900 正常。还要保证音箱能访问 `MIAIR_HOSTNAME:MIAIR_DLNA_PORT`，默认即宿主机 TCP 8200。大文件播放还要求容器能访问上游媒体源。
