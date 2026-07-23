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
  <img src="docs/images/architecture.png" alt="架构图" width="800">
</p>

**三步完成投送**：

| 阶段 | 客户端做什么 | MiAirX 做什么 |
|------|------------|--------------|
| ① 发现 | "附近有音箱吗？"（M-SEARCH） | "有！小爱音箱在这里"（SSDP 回复） |
| ② 投送 | "播这首歌，链接是 xxx"（SOAP） | 下载音频 → 生成局域网链接 → 发给音箱 |
| ③ 追踪 | "播到第几秒了？"（GetPositionInfo） | 自己跟踪位置，不被小米 API 误导 |

> 完整技术细节见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)，通俗版见 [SIMPLE.md](docs/SIMPLE.md)

---

## 🚀 快速开始

### 前置要求

- **Python 3.12+**
- 小米音箱和电脑在**同一个 Wi-Fi**
- 不需要在音箱上做任何改动

### 1. 安装

```bash
pip install aiohttp miservice-fork zeroconf pycryptodome structlog pydantic pydantic-settings
```

### 2. 配置

编辑 `conf/config.json`：

```json
{
  "account": "你的小米账号",
  "password": "你的密码",
  "mi_did": "音箱的DID",
  "hostname": "192.168.x.x"
}
```

> 🔍 不知道 DID？启动后在 Web 界面 `http://localhost:8300` → 设备管理 → 能看到你的所有音箱

### 3. 启动

```bash
# Windows
start.bat

# 命令行
python start.py

# 或 Python 模块模式
python -m miairx
```

### 4. 投！

打开 QQ音乐 / 网易云音乐 → 投屏列表 → 找到 `XiaoAI L05C` → 🎵

---

## 🎛️ Web 管理界面

启动后访问 `http://localhost:8300`

| 功能 | 说明 |
|------|------|
| **媒体控制** | 播放/暂停/停止/音量/进度条 |
| **设备管理** | 选择要桥接的小米音箱 |
| **设置** | 修改配置、重启服务 |

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
