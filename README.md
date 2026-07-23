<p align="center">
  <img src="docs/images/logo.png" alt="MiAirX" width="200">
</p>

<h1 align="center">MiAirX</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square">
  <img src="https://img.shields.io/github/v/release/PDSB001/MiAirX?style=flat-square">
  <img src="https://img.shields.io/badge/Platform-Win%20|%20Mac%20|%20Linux-lightgrey?style=flat-square">
</p>

<p align="center">
  <b>让 QQ音乐 · 网易云音乐 · iOS 直接投送到你的小爱音箱</b><br>
  不改固件、不改 App，纯协议翻译。
</p>

<p align="center">
  <a href="#-快速开始">快速开始</a> ·
  <a href="#-原理">原理</a> ·
  <a href="#-web-管理界面">Web界面</a> ·
  <a href="#-docker">Docker</a> ·
  <a href="docs/ARCHITECTURE.md">架构详解</a> ·
  <a href="docs/SIMPLE.md">大白话版</a>
</p>

---

## 🎯 解决的痛点

买了小爱音箱，想用 QQ 音乐、网易云音乐的"投屏"功能，但死活搜不到你的音箱。

**因为小爱音箱说"小米语"（MiNA API），音乐 App 说"通用语"（DLNA），双方互不认识。**

MiAirX 在你电脑上扮演一个翻译官：

```
QQ音乐 ──DLNA──▶  MiAirX  ──MiNA API──▶  小爱音箱
```

| 不用 MiAirX | 用了 MiAirX |
|---|---|
| 投屏列表空空如也 | 你的音箱出现在列表中 |
| 只能对着音箱喊"小爱同学" | 手机选歌 → 点投屏 → 音箱出声 |

---

## 🏗️ 原理

<p align="center">
  <img src="docs/images/architecture.png" alt="架构图" width="900">
</p>

| 阶段 | 客户端行为 | MiAirX 行为 |
|------|------------|------------|
| ① **发现** | "附近有音箱吗？"（M-SEARCH 组播） | "有！小爱音箱在这里"（SSDP 响应） |
| ② **投送** | "播这首歌，链接是 xxx"（SOAP） | 下载音频 → 生成局域网链接 → 调 MiNA API 让音箱播放 |
| ③ **追踪** | "播到第几秒了？"（GetPositionInfo） | 内部精确跟踪位置，不被小米云 API 误导 |

> 完整技术细节见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，通俗版见 [SIMPLE.md](docs/SIMPLE.md)

---

## 🚀 快速开始

### 三种安装方式

#### 方式一：Docker（最省心）

```bash
docker run -d --name miairx \
  --network host \
  -v $(pwd)/conf:/app/conf \
  ghcr.io/pdsb001/miairx:master
```

> `--network host` 让 Docker 共享主机网络，避免 DLNA 组播问题。

#### 方式二：pip 安装

```bash
pip install aiohttp miservice-fork zeroconf pycryptodome structlog pydantic pydantic-settings
```

#### 方式三：源码安装

```bash
git clone https://github.com/PDSB001/MiAirX.git
cd MiAirX
pip install -e .
```

---

### 配置 `conf/config.json`

```json
{
  "account":  "你的小米账号",
  "password": "你的密码",
  "mi_did":   "音箱的DID",
  "hostname": "192.168.x.x"
}
```

| 字段 | 说明 |
|------|------|
| `account` | 小米账号（手机号/邮箱） |
| `password` | 小米密码 |
| `mi_did` | 音箱设备 ID，**强烈建议先填一个占位** |
| `hostname` | 电脑在局域网中的 IP（**留空自动检测**） |

> 💡 **不知道 DID？** 把 `mi_did` 留空或随便填一个，启动后打开 Web 界面 → 设备管理 → 复制你要用那台的 DID → 改配置重启。

---

### 启动

```bash
# 方式 A：Windows 一键
start.bat

# 方式 B：Python 一键
python start.py

# 方式 C：模块模式（推荐用于调试）
python -m miairx --debug
```

启动成功后会看到：
```
INFO  MiAirX v1.0.0
INFO  Hostname: 192.168.1.172
INFO  DLNA  HTTP server on :8200
INFO  Web  management on :8300
INFO  Speakers registered: 小爱音箱Play增强版 (L05C)
```

---

### 投！

#### 📱 QQ 音乐
1. 打开 QQ 音乐 → 选歌 → 播放界面右上角 **···** → **投屏**
2. 在设备列表里点 **XiaoAI L05C**
3. 音箱出声

#### 🎵 网易云音乐
1. 打开网易云 → 选歌 → 播放界面 **分享** → **投屏到设备**
2. 选 **XiaoAI L05C**
3. 音箱出声

#### 🍎 iOS
1. 从控制中心拉出 **隔空播放**（AirPlay）
2. 选 **XiaoAI L05C**
3. 任何 App 的音频都会路由到音箱

> 💡 设备名可能显示为 `XiaoAI L05C (xxxxxxx)`（硬件型号 + DID），取决于你的网络环境。

---

## 🎛️ Web 管理界面

启动后访问 **http://localhost:8300**

| 标签 | 功能 |
|------|------|
| **📊 状态** | 服务运行状态、网络信息、音箱在线情况 |
| **🎵 媒体控制** | 当前播放曲目、播放/暂停/停止、音量、进度跳转 |
| **📱 设备管理** | 已发现的小米音箱列表、启用/禁用、复制 DID |
| **⚙️ 设置** | 查看/修改配置、重启服务 |

| 操作 | 方法 |
|------|------|
| 复制 DID | 设备管理 → 音箱卡片 → 点 DID |
| 切换音箱 | 设备管理 → 点击要启用的音箱 |
| 调整音量 | 媒体控制 → 拖动音量条 |
| 跳转进度 | 媒体控制 → 拖动进度条 |

---

## 🗂️ 项目结构

```
MiAirX/
├── start.py                 # 一键启动
├── start.bat                # Windows 启动
├── Dockerfile               # Docker 部署
├── conf/                    # 配置目录
│   └── config.json
├── src/miairx/
│   ├── cli.py               # CLI 入口
│   ├── app.py               # 核心编排器
│   ├── const.py             # DLNA 常量
│   ├── auth/                # 小米账号认证
│   ├── config/              # 配置管理
│   ├── core/                # 基础设施
│   ├── media/               # 音频处理 & 代理
│   ├── speaker/             # 音箱控制
│   ├── protocols/
│   │   ├── dlna/            # DLNA/UPnP 协议
│   │   └── airplay/         # AirPlay 协议
│   └── web/                 # Web 管理界面
└── tests/                   # 测试
```

---

## 🐳 Docker

```bash
# 直接拉 GitHub 自动编译的镜像
docker pull ghcr.io/pdsb001/miairx:master

docker run -p 8200:8200 -p 8300:8300 \
  -v $(pwd)/conf:/app/conf \
  ghcr.io/pdsb001/miairx:master
```

> 每次 push 到 master，GitHub Actions 自动构建 amd64 + arm64 镜像并推送到 ghcr.io。

---

## 📦 依赖

| 依赖 | 用途 |
|------|------|
| [miservice-fork](https://github.com/KiriChen-Wind/miservice-fork) | 小米云 API |
| aiohttp | 异步 HTTP |
| zeroconf | AirPlay mDNS 广播 |
| pycryptodome | AirPlay 加密 |
| structlog | 结构化日志 |
| pydantic | 配置验证 |

---

## 💡 常见问题

<details>
<summary><b>Q: 投屏列表里看不到音箱？</b></summary>

- 确认电脑和音箱**同一 Wi-Fi**
- 确认 Windows 防火墙放行了 1900(UDP)、8200(TCP)、8300(TCP)
- 尝试关闭 VPN/代理
</details>

<details>
<summary><b>Q: 播放了但没有声音？</b></summary>

- 检查音箱音量
- 检查 Web UI 中音箱是否已启用（设备管理 → 确保勾选）
- 查看控制台日志中的错误信息
</details>

<details>
<summary><b>Q: 进度条不准确？</b></summary>

部分客户端（如网易云音乐）不轮询进度接口，而是依赖 UPnP 事件推送。这在 FAQ 中是已知的限制。
</details>

---

## 🧪 开发

```bash
pip install -e ".[dev]"
pytest --cov=src
```

---

## 🙏 致谢

核心 DLNA 状态机及 MiNA API 桥接逻辑源自 [MiAir](https://github.com/KiriChen-Wind/MiAir)，感谢原作者 **KiriChen-Wind** 的开创性工作。

---

## 📄 许可证

MIT © 2025 KiriChen-Wind (MiAir) | 2026 MiAirX Contributors
