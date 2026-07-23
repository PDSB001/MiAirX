# MiAirX

> 让小米 AI 音箱被 QQ 音乐、网易云、iOS 等通用客户端发现和投送。

## 它干什么

小爱音箱硬件能播任意 HTTP 音频，但软件层只认小米自家的投送指令。MiAirX 在电脑上跑一个服务，把 DLNA/AirPlay（行业标准）翻译成 MiNA API（小米私有协议），不改音箱、不改 App，纯中间翻译。

```
QQ音乐 ──DLNA──▶ MiAirX ──MiNA API──▶ 小爱音箱
```

[详细原理](docs/ARCHITECTURE.md) | [大白话版](docs/SIMPLE.md)

## 快速开始

### 1. 安装依赖

```bash
pip install aiohttp miservice-fork zeroconf pycryptodome structlog pydantic pydantic-settings
```

### 2. 配置

编辑 `conf/config.json`，填入小米账号和设备 DID：

```json
{
  "account": "你的小米账号",
  "password": "你的密码",
  "mi_did": "音箱的DID",
  "hostname": "192.168.x.x"
}
```

或直接访问 Web 界面 `http://localhost:8300` 配置。

### 3. 启动

```bash
# Windows
start.bat

# 命令行
python start.py

# 或直接
python -m miairx
```

打开 QQ 音乐 → 投屏列表 → 找到你的小爱音箱 → 投！

## 依赖

- Python 3.12+
- [miservice-fork](https://github.com/KiriChen-Wind/miservice-fork) - 小米云 API
- aiohttp - 异步 HTTP
- zeroconf - mDNS/Bonjour
- pycryptodome - AirPlay 加密

## 致谢

核心渲染器状态机引用自 [MiAir](https://github.com/KiriChen-Wind/MiAir)，感谢原作者 KiriChen-Wind 的开创性工作。

## 许可证

MIT © 2025 KiriChen-Wind (MiAir) | 2026 MiAirX Contributors
