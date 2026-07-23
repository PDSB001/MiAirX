# MiAirX 项目原理详解

---

## 目录

1. [DLNA 协议简介](#1-dlna-协议简介)
   - [1.1 协议栈概览](#11-协议栈概览)
   - [1.2 SSDP：设备发现](#12-ssdp设备发现)
   - [1.3 SOAP：设备控制](#13-soap设备控制)
   - [1.4 GENA：事件订阅与通知](#14-gena事件订阅与通知)
   - [1.5 UPnP AVTransport 状态机](#15-upnp-avtransport-状态机)
2. [MiAirX 是什么](#2-miairx-是什么)
3. [核心技术架构](#3-核心技术架构)
   - [3.1 总体架构图](#31-总体架构图)
   - [3.2 协议层：协议翻译器](#32-协议层协议翻译器)
   - [3.3 网络层：媒体代理服务器](#33-网络层媒体代理服务器)
   - [3.4 状态层：播放状态影子镜像](#34-状态层播放状态影子镜像)
4. [完整数据流](#4-完整数据流)
   - [4.1 设备发现与连接](#41-设备发现与连接)
   - [4.2 投送播放](#42-投送播放)
   - [4.3 播放位置追踪](#43-播放位置追踪)
   - [4.4 健康检查与状态同步](#44-健康检查与状态同步)
5. [核心组件详解](#5-核心组件详解)
   - [5.1 Application（应用编排器）](#51-application应用编排器)
   - [5.2 DlnaRenderer（DLNA 渲染器）](#52-dlnarendererdlna-渲染器)
   - [5.3 SpeakerController（音箱控制器）](#53-speakercontroller音箱控制器)
   - [5.4 MediaProxy（媒体代理）](#54-mediaproxy媒体代理)
6. [兼容性设计](#6-兼容性设计)
   - [6.1 多音箱型号适配](#61-多音箱型号适配)
   - [6.2 用户主动操作 vs 健康检查的区分](#62-用户主动操作-vs-健康检查的区分)
7. [已解决的关键问题](#7-已解决的关键问题)
8. [术语表](#8-术语表)

---

## 1. DLNA 协议简介

### 1.1 协议栈概览

DLNA（Digital Living Network Alliance）是一套让家庭设备互通的协议规范。其核心通信基础是 **UPnP（Universal Plug and Play）协议栈**，在 TCP/IP 之上构建了设备互联的标准语言。

```
┌─────────────────────────────────────────────┐
│           UPnP 协议层次                      │
├───────────┬───────────┬─────────────────────┤
│   SSDP    │   SOAP    │       GENA          │
│  (发现)   │  (控制)   │    (事件通知)        │
│   UDP     │   HTTP    │       HTTP          │
│   1900    │  TCP/IP   │      TCP/IP         │
├───────────┴───────────┴─────────────────────┤
│                UDP / TCP                    │
│                  IP                         │
└─────────────────────────────────────────────┘
```

DLNA 定义了三种角色：

| 角色 | 说明 | 举例 |
|------|------|------|
| **DMS**（Digital Media Server）| 提供内容的设备 | NAS、手机上的音乐库 |
| **DMR**（Digital Media Renderer）| 播放内容的设备 | 智能音箱、电视 |
| **DMC**（Digital Media Controller）| 控制播放的设备 | 手机上的投屏 App |

**MiAirX 把自己伪装成一个 DMR（MediaRenderer），让 QQ 音乐等 DMC 发现并控制它。**

### 1.2 SSDP：设备发现

**SSDP（Simple Service Discovery Protocol）** 是 DLNA 中的设备发现协议，基于 UDP 多播（组播 IP `239.255.255.250`，端口 `1900`）。

**工作流程**：

```
┌──────────┐                          ┌──────────────┐
│  DMC     │                          │  DMR (MiAirX) │
│ QQ音乐   │                          │               │
└────┬─────┘                          └──────┬────────┘
     │                                        │
     │  1. M-SEARCH (多播搜索)                 │
     │  "谁是 MediaRenderer？"                │
     │──────────────────────────────────────▶│
     │                                        │
     │  2. 200 OK (单播回复)                   │
     │  "我是小爱音箱Play增强版，在这⬇"        │
     │◀──────────────────────────────────────│
     │  LOCATION: http://192.168.1.x:8200/   │
     │            device/uuid/description.xml │
     │                                        │
     │  3. HTTP GET device description        │
     │     (获取设备详情)                      │
     │──────────────────────────────────────▶│
     │                                        │
     │  4. XML 设备描述                        │
     │◀──────────────────────────────────────│
     │  - deviceType: MediaRenderer:1         │
     │  - AVTransport 服务地址                │
     │  - RenderingControl 服务地址            │
     │  - ConnectionManager 服务地址           │
     │                                        │
```

**两种发现方式**：

- **主动搜索（M-SEARCH）**：DMC 发多播 `M-SEARCH * HTTP/1.1`，携带 `ST`（Search Target）头指定要搜的设备类型（如 `urn:schemas-upnp-org:device:MediaRenderer:1`）。所有匹配的 DMR 在随机延迟（0 ~ MX 秒）后单播回复 `200 OK`，含 `LOCATION` 头指向设备描述 XML 的 URL。

- **被动通知（NOTIFY）**：DMR 周期性地（MiAirX 每 30 ± 5 秒）向多播组发送 `NOTIFY * HTTP/1.1`，带 `NTS: ssdp:alive`，宣告自己在线。MiAirX 在启动时立即发送 6 组 NOTIFY（rootdevice、device type、3 个 service type），此后周期性重发。关闭前发送 `NTS: ssdp:byebye` 宣告离线。

### 1.3 SOAP：设备控制

DMC 通过 **SOAP（Simple Object Access Protocol）** 控制 DMR。SOAP 请求封装在 HTTP POST 中，URL 为设备描述 XML 中声明的 `controlURL`。

**示例：QQ 音乐发送 Play 命令**

```http
POST /device/uuid:abc/AVTransport/control HTTP/1.1
Host: 192.168.1.172:8200
SOAPAction: "urn:schemas-upnp-org:service:AVTransport:1#Play"
Content-Type: text/xml; charset="utf-8"

<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>
```

**MiAirX 响应**：

```http
HTTP/1.1 200 OK
Content-Type: text/xml; charset="utf-8"

<?xml version="1.0"?>
<s:Envelope ...>
  <s:Body>
    <u:PlayResponse xmlns:u="urn:schemas-upnp-org:service:AVTransport:1"/>
  </s:Body>
</s:Envelope>
```

**DLNA AVTransport 服务支持的完整指令集**（MiAirX 全部实现）：

| 指令（Action） | 功能 | MiAirX 内部调用 |
|---|---|---|
| `SetAVTransportURI` | 设置播放 URL（告诉音箱播什么） | `renderer.set_av_transport_uri()` → 创建代理 |
| `Play` | 开始/恢复播放 | `renderer.play()` → `controller.play_url()` |
| `Pause` | 暂停播放 | `renderer.pause()` → `controller.pause()` |
| `Stop` | 停止播放 | `renderer.stop()` → `controller.stop()` |
| `Seek` | 跳转到指定位置 | `renderer.seek()` → 重新生成带 range 的 URL |
| `Next` | 下一首 | 切换到 `next_uri` |
| `Previous` | 上一首 | （空实现，DLNA 规范允许） |
| `GetPositionInfo` | 获取当前播放位置 | 返回 `_get_elapsed_time()` |
| `GetTransportInfo` | 获取播放/暂停/停止状态 | 返回 `transport_state` |
| `GetMediaInfo` | 获取当前媒体信息 | 返回 `current_uri`、时长等 |
| `SetNextAVTransportURI` | 预加载下一首 URL | 存入 `next_uri` |
| `GetDeviceCapabilities` | 获取设备能力 | 返回支持的播放模式 |
| `GetTransportSettings` | 获取播放模式 | 返回 `NORMAL` |
| `GetCurrentTransportActions` | 获取当前可用操作 | 根据 `transport_state` 动态计算 |
| `SetPlayMode` | 设置播放模式 | （仅记录） |

**RenderingControl 服务**（控制音量）：

| 指令 | 功能 |
|---|---|
| `GetVolume` | 读取当前音量 |
| `SetVolume` | 设置音量 |
| `GetMute` | 读取静音状态 |
| `SetMute` | 设置静音 |
| `ListPresets` | 列出预设 |
| `SelectPreset` | 选择预设 |

**ConnectionManager 服务**：

| 指令 | 功能 |
|---|---|
| `GetProtocolInfo` | 返回支持的媒体格式列表（MP3 / FLAC / WAV / AAC / OGG / M4A / APE / ALAC 等） |
| `GetCurrentConnectionIDs` | 返回当前连接 ID（固定 `"0"`） |
| `GetCurrentConnectionInfo` | 返回当前连接详情 |

### 1.4 GENA：事件订阅与通知

**GENA（General Event Notification Architecture）** 是 UPnP 的事件子系统。DMC 通过订阅 DMR 的事件服务，在状态变更时收到推送通知，无需轮询。

**订阅流程**：

```
┌──────────┐                          ┌──────────────┐
│  DMC     │                          │  DMR (MiAirX) │
│ QQ音乐   │                          │               │
└────┬─────┘                          └──────┬────────┘
     │                                        │
     │ 1. SUBSCRIBE                           │
     │  "我关心你的状态变化，这是我的回调地址" │
     │  URL: /device/uuid/AVTransport/event   │
     │  CALLBACK: <http://192.168.1.100:xxx/>  │
     │  NT: upnp:event                        │
     │  TIMEOUT: Second-1800                  │
     │──────────────────────────────────────▶│
     │                                        │
     │ 2. 200 OK                              │
     │  SID: uuid:xxx...                      │
     │  TIMEOUT: Second-1800                  │
     │◀──────────────────────────────────────│
     │                                        │
     │ 3. 初始事件（立即发送）                 │
     │  NOTIFY (当前状态)                      │
     │◀──────────────────────────────────────│
     │                                        │
     │ ... 状态改变时 ...                      │
     │                                        │
     │ 4. NOTIFY (状态变更通知)               │
     │  NT: upnp:event                        │
     │  NTS: upnp:propchange                  │
     │  SEQ: 1,2,3...                         │
     │◀──────────────────────────────────────│
     │                                        │
     │ 5. 续订 (过期前重复步骤1)              │
     │──────────────────────────────────────▶│
     │                                        │
```

**LastChange 事件格式**（MiAirX 发送给 QQ 音乐的 XML）：

```xml
<?xml version="1.0"?>
<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">
  <e:property>
    <LastChange>
      &lt;Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/"&gt;
        &lt;InstanceID val="0"&gt;
          &lt;TransportState val="PLAYING"/&gt;
          &lt;CurrentTrackDuration val="0:03:45.000"/&gt;
          &lt;CurrentTrackMetaData val="...DIDL-Lite XML..."/&gt;
        &lt;/InstanceID&gt;
      &lt;/Event&gt;
    </LastChange>
  </e:property>
</e:propertyset>
```

注意 `LastChange` 的值是对内层 XML 做 `xml.sax.saxutils.escape()` 转义后的字符串，这是 UPnP 规范要求的做法。

### 1.5 UPnP AVTransport 状态机

DLNA 定义 DMR 的 `TransportState` 为以下标准状态：

```
                        SetAVTransportURI
     NO_MEDIA_PRESENT ──────────────────────▶ STOPPED
          ▲                                      │
          │                              Play()  │  Stop()
          │ Stop()                               ▼
          │                                 PLAYING
          │                                      │
          │◀─────────────────────────────────────│
          │                Stop() / Pause()      │ Pause()
          │                                      ▼
          └─────────────────────────────── PAUSED_PLAYBACK
                            Stop()           │
                                             │ Play()
                                             ▼
                                          PLAYING
```

**MiAirX 使用的状态常量**（定义在 `const.py`）：

```python
TRANSPORT_STATE_NO_MEDIA     = "NO_MEDIA_PRESENT"   # 未加载媒体
TRANSPORT_STATE_STOPPED      = "STOPPED"            # 已加载，未播放
TRANSPORT_STATE_PLAYING      = "PLAYING"            # 播放中
TRANSPORT_STATE_PAUSED       = "PAUSED_PLAYBACK"    # 暂停
TRANSPORT_STATE_TRANSITIONING = "TRANSITIONING"     # 过渡中（播放/暂停/跳转瞬态）
```

---

## 2. MiAirX 是什么

**MiAirX 是一个协议桥接器（Protocol Bridge）。** 它的核心目标：

> 让小米 AI 音箱伪装成标准 DLNA / AirPlay 渲染器，使 QQ 音乐、网易云音乐、iOS 等通用客户端无需任何改造即可直接投送播放。

**解决的矛盾**：

小米音箱硬件完全支持网络音频播放——MiNA API 的 `play_url` 能播任意 HTTP 音频流。但小米固件的软件层是封闭的：它只接受小米自家 App 和小爱同学语音的投送指令，没有对外开放 DLNA 或 AirPlay 接口。

MiAirX 不改固件、不 root 音箱，通过在局域网内运行一个 Python 服务，在外部标准协议和内部私有协议之间做翻译，打开这扇门。

**一句话概括**：给只会说"小米语"的音箱配了个同声传译，让说 DLNA（QQ 音乐）和 AirPlay（iOS）的客户端都能和它交流。

---

## 3. 核心技术架构

### 3.1 总体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         局域网 (LAN)                                 │
│                                                                     │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐                    │
│  │ QQ 音乐  │     │ 网易云   │     │ iOS设备  │     ... DLNA/       │
│  │ (DLNA)   │     │ (DLNA)   │     │ (AirPlay)│      AirPlay 客户端 │
│  └────┬─────┘     └────┬─────┘     └────┬─────┘                    │
│       │                │                │                           │
│       │ DLNA/UPnP      │ DLNA/UPnP      │ AirPlay/RAOP             │
│       ▼                ▼                ▼                           │
│  ┌──────────────────────────────────────────────────┐               │
│  │                   MiAirX                         │               │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────┐  │               │
│  │  │ DLNA Server │  │AirPlay Srv │  │Web管理界面│  │               │
│  │  │ - SSDP发现  │  │- RAOP RTSP │  │(端口8300) │  │               │
│  │  │ - SOAP控制  │  │- mDNS广播  │  │           │  │               │
│  │  │ - GENA事件  │  │            │  │           │  │               │
│  │  └──────┬──────┘  └──────┬─────┘  └───────────┘  │               │
│  │         │                │                        │               │
│  │  ┌──────┴────────────────┴──────────────────┐    │               │
│  │  │          核心调度层 (Application)          │    │               │
│  │  │  - 状态机同步（健康检查，每5秒）            │    │               │
│  │  │  - 音箱管理（多音箱注册）                   │    │               │
│  │  │  - 媒体代理管理                            │    │               │
│  │  └──────┬────────────────────────────────────┘    │               │
│  │         │                                         │               │
│  │  ┌──────┴─────────────┐  ┌──────────────────┐    │               │
│  │  │  SpeakerController │  │   MediaProxy     │    │               │
│  │  │  - play_url()      │  │  - 音频下载缓冲   │    │               │
│  │  │  - get_status()    │  │  - 短URL生成      │    │               │
│  │  │  - set_volume()    │  │  - Range请求处理  │    │               │
│  │  └──────┬──────────────┘  └──────────────────┘    │               │
│  └─────────┼─────────────────────────────────────────┘               │
│            │ MiNA API (小米私有协议)                                  │
│            ▼                                                        │
│       ┌─────────────────────────────────────┐                       │
│       │        小米云服务器                    │                       │
│       │    (api.mina.mi.com)                 │                       │
│       └──────────────────┬──────────────────┘                       │
│                          │                                          │
│                          ▼                                          │
│       ┌──────────────────────────────────────┐                      │
│       │     小爱音箱 Play 增强版               │                      │
│       │     (通过小米云接收 play_url 指令)      │                      │
│       └──────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 协议层：协议翻译器

协议层负责在 DLNA/AirPlay 和 MiNA API 之间做双向翻译。三套协议的对比如下：

|  | DLNA (UPnP) | AirPlay (RAOP) | MiNA API |
|--|------------|----------------|----------|
| **传输** | UDP 1900 (发现) + HTTP (控制/事件) | RTSP + HTTP (音频流) | HTTPS REST |
| **鉴权** | 无（局域网） | 无（局域网） | 小米账号 Cookie/Token |
| **播放** | `SetAVTransportURI` + `Play` | `ANNOUNCE` + `RECORD` | `play_url(url)` |
| **暂停** | `Pause` SOAP | `TEARDOWN` RTSP | `player_pause(device_id)` |
| **停止** | `Stop` SOAP | `TEARDOWN` RTSP | `player_stop(device_id)` |
| **音量** | `SetVolume` SOAP | `SET_PARAMETER volume` | `player_set_volume(device_id, vol)` |
| **状态** | `GetTransportInfo` + `GetPositionInfo` SOAP | （无标准接口） | `player_get_status(device_id)` → `{status, volume, ...}` |
| **进度** | 客户端轮询 `GetPositionInfo`，或订阅 UPnP 事件 | 客户端自行估算 | API 不报告代理 URL 的播放进度 |

**协议翻译的核心逻辑**（以 DLNA Play 为例）：

```
1. QQ音乐 发送 SOAP Play 请求
2. DlnaHttpServer 解析 SOAP，提取 Action="Play"
3. SoapHandler 分发到 _handle_avtransport() 
4. 调用 DlnaRenderer.play()
5. renderer 检查 transport_state:
   - STOPPED → 生成代理URL → 调 controller.play_url(proxy_url) → 设 PLAYING
   - PAUSED  → 调 controller.play_url(seek_url) → 恢复播放
6. if "resume成功": → 设 transport_state = PLAYING
7. notify_state_change() → 构造 LastChange XML → HTTP NOTIFY → QQ音乐
```

### 3.3 网络层：媒体代理服务器

媒体代理是 MiAirX 的 "翻译中间件"。它的存在原因是：

**问题**：QQ 音乐给的原始音频 URL 可能很长（含 token、签名等参数），或格式不兼容（需要 range 请求支持），或直接在外网导致音箱无法访问。

**方案**：MiAirX 在收到 `SetAVTransportURI` 时启动媒体代理流程：

```
QQ音乐 → SetAVTransportURI("https://qqmusic.xxx/stream?long_token=...")
         │
         ▼
┌────────────────────────────────────┐
│  MiAirX MediaProxy                │
│                                    │
│  1. 创建 MediaBuffer               │
│     异步下载原始URL的音频流         │
│     缓冲在内存中                   │
│                                    │
│  2. 注册到代理表                    │
│     token = secrets.token_urlsafe  │
│     proxy_url = http://MiAirX_ip  │
│                 :8200/media/{token}│
│                                    │
│  3. 音箱拉取代理 URL                │
│     get http://192.168.1.172:8200 │
│         /media/{token}             │
│     支持 Range 请求（Seek用）       │
│                                    │
│  4. 代理转发                        │
│     MediaBuffer.read(offset, len)  │
│     → 从内存缓冲区返回对应字节       │
└────────────────────────────────────┘
         │
         ▼
小米音箱 ← play_url("http://192.168.1.172:8200/media/{token}")
```

**MediaBuffer 的关键能力**：
- **异步缓冲区**：从源 URL 流式下载到内存队列，暂停/恢复由事件控制
- **Range 请求支持**：QQ 音乐的 Seek 操作需要从指定字节偏移开始读取，`MediaBuffer` 维护已下载的字节范围，对于已缓存部分直接返回，未缓存部分等待下载
- **Seek 重建**：当 Seek 目标超出已缓冲范围时，abort 现有缓冲区，从新偏移位置重新开始下载

### 3.4 状态层：播放状态影子镜像

这是整个项目最微妙的一层，也是调试时间最长的部分。

**为什么需要影子镜像？**

DLNA 客户端（QQ 音乐）需要知道音箱的实时状态：在播放吗？播到哪一秒了？音量多少？

但小米 API 有两个固有问题：

1. **`player_get_status` 不报告代理 URL 的播放状态**：当 MiAirX 通过代理 URL 投送音频时，API 持续返回 `status=0`（STOPPED），尽管音箱实际上在播放。
2. **状态查询不是即时的**：API 调用有网络延迟，且音量/进度等数据不是原子返回。

因此，MiAirX 不能单纯依赖 `player_get_status` 的返回值。它维护一套**影子状态**，通过函数回调注入到 `DlnaRenderer` 内部：

```python
# 影子状态变量（DlnaRenderer 实例属性）

transport_state: str       # DLNA 标准状态：PLAYING / PAUSED_PLAYBACK / STOPPED / NO_MEDIA_PRESENT

# 位置追踪（两段式时间模型）
_play_start_time: float    # 当前播放段开始时刻（time.time() 时间戳）
_accumulated_time: float   # 累积播放时间（暂停前的秒数）
_track_duration: float     # 总时长（秒）

# 用户操作标识
_user_stopped: bool        # True = 用户主动暂停/停止；False = 系统或音箱触发的状态变化
_last_control_time: float  # 最后一次接收到 DLNA 控制指令的时间戳

# 异常状态追踪
_stuck_paused_since: float # 陷入假暂停的时间戳（0 = 正常）
_play_grace_until: float   # 播放命令发出后的宽容期截止时间（避免音箱异步响应造成误判）
```

**位置计算公式**：

```python
def _get_elapsed_time(self) -> float:
    """返回当前播放位置（秒）"""
    if self.transport_state == TRANSPORT_STATE_PLAYING:
        # 播放中：累积时间 + 当前段已播放时长
        return self._accumulated_time + (time.time() - self._play_start_time)
    else:
        # 暂停/停止：只返回累积时间
        return self._accumulated_time
```

**状态转换时的副作用**（`_handle_state_transition()`）：

| 转换 | 对位置的影响 |
|------|-------------|
| `PLAYING → PAUSED` | `_accumulated_time += (now - _play_start_time)`<br>`_play_start_time = 0`（冻结位置）|
| `PAUSED → PLAYING` | 若 `_stuck_paused_since > 0`：<br>`_accumulated_time += (now - _stuck_paused_since)`（补偿假暂停时长）<br>`_play_start_time = now`（恢复计时）|
| `STOPPED → PLAYING` | `_play_start_time = now`（开始计时） |
| `STOPPED → PAUSED` | `_accumulated_time += (now - _play_start_time)`<br>`_play_start_time = 0` |
| → `NO_MEDIA` | `_accumulated_time = 0; _play_start_time = 0`（全部归零） |

---

## 4. 完整数据流

### 4.1 设备发现与连接

```
┌────────────┬───────────────────────────────────────────────────────┐
│  时间线      │  动作                                                 │
├────────────┼───────────────────────────────────────────────────────┤
│ T+0s       │ MiAirX 启动，UDP socket 绑定 1900 端口                  │
│            │ 加入多播组 239.255.255.250                              │
│ T+0.1s     │ 发送 SSDP NOTIFY (ssdp:alive) × 6                      │
│            │ 注册所有 renderer 的 device/service type                │
│ T+0.2s     │ 启动 DLNA HTTP Server (端口 8200)                       │
│            │ 启动 AirPlay mDNS + RTSP Server                        │
│ T+5s       │ 健康检查任务开始（每 5s 轮询音箱状态）                    │
├────────────┼───────────────────────────────────────────────────────┤
│ T+任意时刻  │ QQ音乐打开投屏列表                                      │
│            │ 发送 M-SEARCH：ST=urn:schemas-upnp-org:device:         │
│            │   MediaRenderer:1                                      │
│ T+0~3s     │ MiAirX 回复 200 OK                                     │
│            │ LOCATION: http://192.168.1.172:8200/device/            │
│            │   uuid:402077043/description.xml                       │
│ T+~0.1s    │ QQ音乐 GET description.xml                              │
│ T+~0.1s    │ QQ音乐 SUBSCRIBE AVTransport/event                      │
│ T+~0.1s    │ MiAirX 发送初始事件（当前状态）                          │
│ T+0.5s     │ 用户在QQ音乐中看到 "小爱音箱Play增强版"                   │
└────────────┴───────────────────────────────────────────────────────┘
```

### 4.2 投送播放

```
┌──────────┬────────────────────────────────────────────────────────────┐
│ QQ音乐    │  MiAirX                                                    │
├──────────┼────────────────────────────────────────────────────────────┤
│          │                                                             │
│ 1. 用户  │                                                             │
│ 点击播放  │                                                             │
│          │                                                             │
│ ──SetAVTransportURI──▶                                                │
│  (音频URL, 元数据)   │                                                  │
│                      │  2. renderer.set_av_transport_uri()              │
│                      │     - 解析元数据（DIDL-Lite XML）                 │
│                      │     - 提取歌名、歌手、时长                        │
│                      │     - 创建 MediaBuffer（异步下载原始URL）          │
│                      │     - 生成代理 URL                               │
│                      │     - transport_state = STOPPED                  │
│                      │                                                 │
│ ──Play────────────▶ │                                                 │
│                      │  3. renderer.play()                             │
│                      │     - transport_state = TRANSITIONING           │
│                      │     - controller.play_url(proxy_url)            │
│                      │       → 呼叫小米云 API:                          │
│                      │         POST play_by_music_url(                 │
│                      │           device_id, proxy_url, audio_id)        │
│                      │       → 小米云推送到音箱                          │
│                      │     - transport_state = PLAYING                 │
│                      │     - _play_start_time = time.time()           │
│                      │     - _play_grace_until = now + 15s             │
│                      │                                                 │
│                      │  4. notify_state_change()                       │
│ ◀──NOTIFY──────────│     发送 PLAYING 状态事件给 QQ音乐                 │
│   (PLAYING)         │                                                 │
│                      │                                                 │
│ 5. QQ音乐显示       │                                                 │
│    正在播放          │                                                 │
│                                                                       │
│ ──GetPositionInfo──▶ 6. 每 1-2 秒轮询位置                             │
│ ◀──RelTime: 0:01── │    返回 _get_elapsed_time()                      │
│                                                                       │
│ ──GetPositionInfo──▶ 7. 持续轮询                                      │
│ ◀──RelTime: 0:02── │                                                 │
│ ...                  │                                                 │
│ ──GetPositionInfo──▶ 8. 持续轮询                                      │
│ ◀──RelTime: 3:45── │    歌曲播完时的位置                               │
│                                                                       │
│ ──Pause───────────▶ 9. 用户暂停                                       │
│                      │    - controller.pause()                         │
│                      │    - _accumulated_time += elapsed               │
│                      │    - _play_start_time = 0                      │
│                      │    - transport_state = PAUSED_PLAYBACK          │
│                      │    - _user_stopped = True                       │
│                      │                                                 │
│ ──Play────────────▶ 10. 用户恢复播放                                  │
│                      │     - 生成 seek URL（从 _accumulated_time 偏移） │
│                      │     - controller.play_url(seek_url)             │
│                      │     - _play_start_time = time.time()            │
│                      │     - _user_stopped = False                     │
│                      │                                                 │
└──────────────────────┴─────────────────────────────────────────────────┘
```

### 4.3 播放位置追踪

**为什么用两段式时间模型？**

简单地用一个"开始播放时刻"变量无法处理暂停/恢复。DLNA 客户端需要知道的是"这首歌已经播了几秒"，而不是"这设备从什么时候开始播的"。

```
时间轴: ─────▶

实际播放: [=====播了120s=====]──暂停30s──[==播了20s==]
                                          ▲
                                          GetPositionInfo 应该返回 140s

_model实现:
  _play_start_time = T0
  _accumulated_time = 0
  → 位置 = 0 + (now - T0) = 0, 1, 2, ..., 120s  ✓

  暂停:
  _accumulated_time = 0 + (T_pause - T0) = 120s
  _play_start_time = 0
  → 位置 = 120 + 0 = 120s  (冻结)  ✓

  恢复:
  _play_start_time = T_resume
  → 位置 = 120 + (now - T_resume) = 120, 121, ..., 140s  ✓
```

**Seek 操作的位置追踪**：

Seek 不是"暂停 + 跳转"，而是"停止当前流 + 从新偏移开始播放"。

MiAirX 的处理方式：

```python
def seek(self, target_seconds: float):
    # 1. 停止音箱当前播放
    self.speaker.stop()
    
    # 2. 根据目标时间计算字节偏移
    byte_offset = self._time_to_byte_offset(target_seconds, self._track_duration, self._media_size)
    
    # 3. 生成新的代理 URL（带 range 参数）
    seek_url = self._generate_seek_url(original_source_url, byte_offset)
    
    # 4. 重新开始播放
    self.speaker.play_url(seek_url)
    
    # 5. 重置位置追踪
    self._accumulated_time = target_seconds
    self._play_start_time = time.time()
```

### 4.4 健康检查与状态同步

健康检查是 MiAirX 的核心后台任务，每 5 秒运行一次。它的作用是在音箱物理状态变化（语音控制暂停、网络中断恢复等）时同步 renderer 的影子状态。

**`_poll_speaker_states()` 的完整逻辑**：

```
对每个 renderer:
│
├─ 1. 空闲检测 (Idle Detection)
│   ├─ 条件A: transport_state == PAUSED && _stuck_paused_since > 30s
│   │   └─ _user_stopped == False → idle = True
│   │   └─ _user_stopped == True && 无订阅者 → idle = True
│   ├─ 条件B: transport_state == STOPPED && last_control > 60s && 无订阅者
│   │   └─ idle = True
│   └─ idle → reset_to_idle()（释放资源，回到 NO_MEDIA_PRESENT）→ continue
│
├─ 2. 跳过无媒体 renderer
│   └─ if not current_uri → continue
│
├─ 3. 获取音箱真实状态
│   └─ speaker.get_status() [timeout=10s]
│      ├─ 成功 → status = 0/1/2 → 映射到 STOPPED/PLAYING/PAUSED
│      └─ 异常 → log warning → continue（跳过这轮，不误判）
│
├─ 4. 过滤无变化
│   └─ transport_state == new_state → continue
│
├─ 5. 宽容期保护（Grace Period）
│   └─ play_grace_until > 0 && now < grace && PLAYING→非PLAYING
│      → continue（等待音箱异步响应完成）
│
├─ 6. 代理模式保护（关键修复！）
│   └─ new_state == STOPPED && old_state == PLAYING 
│      && proxy_url_func 存在 && 有 current_uri && !_user_stopped
│      → continue（不信任 API 返回的假 STOPPED）
│
├─ 7. PAUSED→PLAYING 恢复保护（关键修复！）
│   └─ old_state == PAUSED && new_state == PLAYING
│      ├─ _user_stopped → continue（尊重用户暂停）
│      └─ !_user_stopped → 放行（恢复位置追踪）
│
├─ 8. 执行状态转换
│   └─ transport_state = new_state
│   └─ _handle_state_transition()（调整位置追踪变量）
│   └─ if NOT (new_state==STOPPED && !_user_stopped):
│       notify_state_change()（广播给 DLNA 客户端）
```

---

## 5. 核心组件详解

### 5.1 Application（应用编排器）

**文件**：`src/miairx/app.py`

**职责**：Application 是整个 MiAirX 生命周期的主控制器。它不包含协议逻辑，只做组件注册和生命周期管理。

**`start()` 方法的初始化顺序**：

```
1. 创建共享 aiohttp ClientSession（所有 HTTP 调用复用连接）
2. AuthManager.login(mi_account, password)
   → 通过 miservice 库登录小米账号
   → 获取 MiNAService / MiIOService 客户端
3. SpeakerManager.discover_devices()
   → 通过 MiIOService 获取用户的所有小米音箱
   → 匹配配置中的 mi_did 列表
   → 创建 SpeakerController 实例（每个音箱一个）
4. 启动 DLNA Server
   ├─ SsdpServer 绑定 UDP 1900
   ├─ DlnaHttpServer 绑定 TCP 8200
   ├─ 为每个音箱创建 DlnaRenderer
   ├─ 注册到 SsdpServer（SSDP 广播）
   └─ 注册到 DlnaHttpServer（HTTP 路由）
5. 启动 AirPlay Server（如果配置启用）
   ├─ 创建共享 Zeroconf 实例
   ├─ 为每个音箱创建 SpeakerAirplay
   └─ 每个启动 AirplayServer（RTSP）+ mDNS 广告
6. 启动 Web 管理界面（aiohttp web app，端口 8300）
7. 启动健康检查后台任务（_periodic_health_check）
```

### 5.2 DlnaRenderer（DLNA 渲染器）

**文件**：`src/miairx/protocols/dlna/renderer.py`

**职责**：每个音箱对应一个 `DlnaRenderer` 实例，作为 DLNA AVTransport 状态机的核心，管理播放/暂停/跳转的全部逻辑。

**关键设计**：

1. **回调注入模式**：`proxy_url_func`、`seek_url_func`、`pre_buffer_func` 等是外部注入的回调，renderer 只关注状态转换和位置计算，代理和音频处理由外部负责。这使得 renderer 可以被单元测试独立验证。

2. **异步锁保护**：`_lock = asyncio.Lock()` 保证多个 SOAP 请求并发时状态操作的安全性。

3. **`_play_check_task()`**：播放命令发出后 15 秒检查音箱是否真的开始播放。如果 PAUSED→PLAYING 后音箱仍不报 PLAYING，自动重试一次。

4. **`_user_stopped` 标志**：区分"用户点了暂停"和"音箱自己状态跳变"。这是解决幽灵暂停系列问题的关键变量。

**核心方法调用链**：

```python
# 以 set_av_transport_uri + play 为例:

set_av_transport_uri(uri, metadata)
  ├─ 解析 URI，判定是否为视频文件
  ├─ _track_duration = 解析元数据中的时长
  ├─ 若代理启用: current_uri = proxy_url_func(uri)
  │   否则: current_uri = uri
  ├─ transport_state = STOPPED
  └─ notify_state_change() [如果之前是 NO_MEDIA]

play(speed="1")
  ├─ if STOPPED:
  │    transport_state = TRANSITIONING
  │    controller.play_url(current_uri)
  │    transport_state = PLAYING
  │    _play_start_time = time.time()
  │    _play_grace_until = time.time() + 15
  │    _start_play_check_task()  # 15s后检查
  ├─ if PAUSED:
  │    seek_url = seek_url_func(_accumulated_time)
  │    controller.play_url(seek_url)
  │    transport_state = PLAYING
  │    _play_start_time = time.time()
  │    _user_stopped = False
  ├─ _last_control_time = time.time()
  └─ notify_state_change()
```

### 5.3 SpeakerController（音箱控制器）

**文件**：`src/miairx/speaker/controller.py`

**职责**：封装所有小米 MiNA API 调用，向上层提供一个统一的音箱控制接口。

**小米 API 的两套播放接口**：

| 接口 | `play_by_music_url` | `play_by_url` |
|------|--------------------|----------------|
| **适用型号** | X08C, X08E, LX05 等（`NEED_USE_PLAY_MUSIC_API` 列表）| 其他型号 |
| **额外参数** | 需要 `audio_id` | 不需要 |
| **暂停处理** | `pause()` 实际调用 `player_stop()`（该 API 的 pause 状态报告不可靠）| 调用 `player_pause()` |

**登录失败保护**：`SpeakerController._consecutive_login_failures` 是类级别计数器，连续 6 次登录失败后触发应用重启（通过 `lifecycle.trigger_shutdown()`），由外部进程管理器（systemd/docker）重启恢复。

**`get_status()` 的语义修复**：之前所有异常都吞掉返回 `STOPPED`，导致网络抖动被误判为音箱停止。现在异常向上抛，让调用方跳过轮询。

### 5.4 MediaProxy（媒体代理）

**文件**：`src/miairx/media/proxy.py`

**职责**：将 QQ 音乐的外网音频 URL 代理为局域网 URL，支持 Range 请求。

**映射关系**：

```
media_proxy._buffers:          {token → MediaBuffer}
media_proxy._url_to_token:     {original_url → token}

token = secrets.token_urlsafe(16)  # 22字符随机token

proxy_url = http://{hostname}:{dlna_port}/media/{token}
```

**HTTP 路由处理**（`DlnaHttpServer._handle_media_request`）：

```
GET /media/{token}
  ├─ 查找 token → MediaBuffer
  ├─ 如果有 Range 头 → buffer.read(offset, length)
  │   返回 HTTP 206 Partial Content
  └─ 如果无 Range 头 → buffer.read(0, None)
      └─ 返回 HTTP 200，流式传输全部内容
```

---

## 6. 兼容性设计

### 6.1 多音箱型号适配

MiAirX 需要在不同型号的小米音箱上工作。主要差异在 API 选择上：

```python
# 需要 music API 的型号
NEED_USE_PLAY_MUSIC_API = [
    "X08C", "X08E", "X8F", "X4B",
    "LX05", "LX05A", "OH2", "OH2P",
    "X6A", "L15A", "L07A",
]
```

这些型号必须使用 `play_by_music_url(device_id, url, audio_id=DEFAULT_AUDIO_ID)`，而非通用的 `play_by_url()`。`audio_id` 是一个硬编码的常量 `"448161862632079419"`，小米内部用于标识音频来源。

### 6.2 用户主动操作 vs 健康检查的区分

这是整个项目调试阶段最核心的挑战。

**问题本质**：DLNA 状态机同时被两个源驱动：
1. **DLNA SOAP 指令**（用户操作）→ `_user_stopped = True`
2. **健康检查**（音箱物理状态）→ `_user_stopped` 不变

如果不区分，会产生两种错误：

| 情况 | 不区分的结果 | 区分后的处理 |
|------|------------|------------|
| 用户暂停，健康检查看到 PLAYING | 强制恢复播放（用户困惑） | 检查 `_user_stopped=True`，跳过 |
| 音箱偶发报 STOPPED，健康检查做 PAUSED | 广播 PAUSED 给 QQ音乐，触发幽灵暂停 | 检查 `_user_stopped=False`，内部处理但不广播 |
| 代理模式下 API 持续报 STOPPED | 反复被覆盖为 PAUSED，位置冻结 | 代理模式直接跳过 `PLAYING→STOPPED` 转换 |

---

## 7. 已解决的关键问题

### 问题 1：幽灵暂停

**现象**：QQ 音乐显示暂停但音箱在播放，随后自动恢复但进度回退。

**根因链路**：

```
音箱偶发真实报 STOPPED
→ 健康检查 STOPPED → PAUSED
→ notify_state_change() 广播 PAUSED 给 QQ 音乐
→ QQ 音乐显示暂停
→ QQ 音乐自动发 Play 恢复
→ play() 用当前位置生成 seek URL
→ 进度偏差
```

**修复**：健康检查触发的 `STOPPED→PAUSED`（非用户操作）不广播给 DLNA 客户端。只内部更新 renderer 状态，QQ 音乐无感知。

### 问题 2：幽灵进度回撤（最核心）

**现象**：正常播放中进度突然跳回几秒前——用户观察：读秒逐渐慢于实际播放，差距到 2 秒就跳回。

**确诊日志**：`PAUSED_PLAYBACK -> PAUSED (保持位置)` 持续刷屏

**完整根因链路**：

```
小爱音箱的 player_get_status API 不报告代理 URL 的播放状态
→ API 持续返回 status=0（STOPPED），不是偶发，是持续
→ 健康检查反复把 renderer 从 PLAYING 打成 PAUSED
→ _play_start_time 清零，位置永久冻结在 _accumulated_time
→ QQ 音乐每 1-2 秒轮询 GetPositionInfo，发现位置卡住不动
→ QQ 音乐判定异常，主动发送 Play 命令纠正
→ play() 用冻结的 _accumulated_time 作为 resume_position
→ 生成新的 seek URL（从冻结点开始）
→ 把已播到后面的音箱强制拉回冻结点
→ 进度回撤
```

**为什么 MiAir 原版没有这个问题**：MiAir 存在相同的潜在 bug——`PAUSED→PLAYING` 无条件 `continue`。但 MiAir 用户的场景（音箱型号/非代理投送/非 QQ 音乐客户端）未触发。MiAirX 的"小爱音箱 Play 增强版 + QQ 音乐 + 代理模式"恰好踩中 API 不报告代理播放状态的特性。

**完整修复（4 处配套）**：

| # | 位置 | 修复内容 |
|---|------|---------|
| 1 | `controller.get_status()` | 出错抛异常而非返回 STOPPED（防网络错误伪装） |
| 2 | `_poll_speaker_states()` | 代理模式下 `PLAYING→STOPPED` 直接跳过（核心修复） |
| 3 | `_poll_speaker_states()` | `PAUSED→PLAYING` 仅 `_user_stopped` 时跳过 |
| 4 | `_handle_state_transition()` | PAUSED→PLAYING 恢复时补偿假暂停冻结的时间 |

### 问题 3：Web UI 设备选择失效

**现象**：前端选择设备后无法确认切换。

**根因**：小米 API 返回的设备对象字段名是 `miotDID`，前端用 `dev.did` 读取，永远是 `undefined`。

**修复**：统一使用 `miotDID` 字段。

---

## 8. 术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| **DLNA** | Digital Living Network Alliance | 数字生活网络联盟，制定家庭媒体共享标准 |
| **UPnP** | Universal Plug and Play | 通用即插即用协议，DLNA 的核心通信基础 |
| **SSDP** | Simple Service Discovery Protocol | 简单服务发现协议（UDP 多播，端口 1900） |
| **SOAP** | Simple Object Access Protocol | 简单对象访问协议（HTTP POST XML，DLNA 的控制通道） |
| **GENA** | General Event Notification Architecture | 通用事件通知架构（HTTP 订阅/通知） |
| **DMC** | Digital Media Controller | 数字媒体控制器（如 QQ 音乐的投屏功能） |
| **DMR** | Digital Media Renderer | 数字媒体渲染器（MiAirX 伪装的目标角色） |
| **DMS** | Digital Media Server | 数字媒体服务器（提供内容的设备） |
| **AVTransport** | AVTransport Service | DLNA 的播放控制服务（Play/Pause/Stop/Seek） |
| **RenderingControl** | RenderingControl Service | DLNA 的渲染控制服务（音量/静音） |
| **ConnectionManager** | ConnectionManager Service | DLNA 的连接管理服务（协议协商） |
| **SCPD** | Service Control Protocol Description | 服务控制协议描述（描述服务支持的动作和状态变量） |
| **DIDL-Lite** | Digital Item Declaration Language | DLNA 用于描述媒体元数据的 XML 格式 |
| **RAOP** | Remote Audio Output Protocol | Apple AirPlay 的音频传输协议 |
| **MiNA** | Mi AI Service | 小米 AI 云服务 API（控制音箱的私有协议） |
| **DID** | Device ID | 小米设备的唯一标识符（如 `402077043`） |
| **UDN** | Unique Device Name | DLNA 中设备的 UUID（格式：`uuid:xxxxxxxx`） |
| **RTP** | Real-time Transport Protocol | 实时传输协议（AirPlay 音频流使用） |
| **mDNS** | Multicast DNS | 多播 DNS（Apple Bonjour/AirPlay 使用的零配置网络发现协议） |
