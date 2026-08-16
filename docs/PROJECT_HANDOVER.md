# MiAirX 项目交接

最后更新：2026-08-16

## 当前状态

MiAirX 当前版本线为 1.0.4。核心 DLNA、AirPlay 1、媒体代理、多设备配置和管理台均已实现。工作区中的管理台已经迁移到 React/TypeScript，根路径使用新页面，旧页面保留在 `/legacy`。

最近一轮重点改动：

- 修复旧自动切歌任务影响新媒体的问题
- 大文件改为流式代理，避免整文件等待与内存压力
- Zeroconf 限制为 IPv4，减少 Docker IPv6 错误
- SSDP 主动发现与 Docker 发现速度优化
- Web 管理台迁移到 React + Vite + TanStack Query
- Docker 改成前端构建、Python 运行的多阶段镜像
- CI 增加前端、浏览器和静态产物一致性检查

## 关键目录

```text
MiAirX/
├── src/miairx/
│   ├── app.py                  应用生命周期与状态同步
│   ├── cli.py                  命令行、环境变量覆盖
│   ├── auth/                   小米登录和 Cookie
│   ├── config/                 Pydantic 配置和持久化
│   ├── media/                  缓冲、代理、转码
│   ├── protocols/dlna/         SSDP、SOAP、GENA、渲染器
│   ├── protocols/airplay/      RAOP/RTSP、mDNS、音频流
│   ├── speaker/                小米音箱控制器
│   └── web/                    aiohttp API 和生产静态资源
├── frontend/                   React/TypeScript 管理台
├── tests/                      Python 单元与集成测试
├── docs/                       用户和开发文档
├── Dockerfile                  多阶段生产镜像
└── .github/workflows/          Python、前端和镜像 CI
```

## 开发入口

后端：

```bash
python -m pip install -e ".[dev]"
pytest tests -q
miairx --verbose
```

前端：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

完整步骤见 [开发指南](DEVELOPMENT.md)。

## 必须保持的行为

### 媒体 generation

`DlnaRenderer._media_generation` 用于判断自动下一曲任务是否已经过期。任何替换当前 URI 的路径都应推进 generation；旧任务不能停止新媒体。

### 大文件流式代理

`MediaBuffer.streaming_mode` 让大文件和未知长度媒体绕过完整内存缓冲。修改代理时同时覆盖：

- 普通 GET
- Range 请求
- 上游断开
- 客户端断开
- token/buffer 回收

### 状态同步保护

健康检查得到的云端状态可能滞后。不要移除 TRANSITIONING、grace period、用户停止标记和假 STOPPED 保护，除非有客户端和真实音箱回归证据。

### IPv4 广播

SSDP 和 AirPlay Zeroconf 当前明确使用 IPv4。Docker 环境中恢复双栈广播前，必须验证没有 IPv6 路由的宿主机不会持续报错。

### 静态前端产物

`frontend/pnpm build` 输出到 `src/miairx/web/static/app/`。源码和产物需要一起提交，CI 会拒绝不一致的产物。

## 配置注意点

- `hostname` 必须是音箱可访问的局域网地址。
- 管理台保存不会热重启服务。
- `proxy_enabled`、`auto_play_on_set_uri`、`enable_voice_control`、`voice_poll_interval` 是兼容性保留字段，当前没有完整运行路径。
- `auto_restart` 只请求退出，需要外部监督器拉起。
- `conf/config.json` 含敏感信息，绝不能提交。

## 验证基线

修改后至少运行：

```bash
pytest tests -q

cd frontend
pnpm check
pnpm test:e2e
```

涉及打包时再运行：

```bash
python -m build
docker build -t miairx:test .
```

本地没有 Docker CLI 时，以 GitHub Docker workflow 的多架构构建结果为准，但不要省略 Dockerfile 静态审查。

## 已知限制

- 管理台没有认证，只适合可信 LAN。
- Docker Desktop 的虚拟网络通常无法正确承载组播。
- AirPlay 1 对发送端版本和音频格式较敏感。
- 媒体源的 DRM、过期签名或特殊鉴权不在 MiAirX 能力范围内。
- Web 直连 `/api/play` 是直接音箱控制，不一定拥有 DLNA metadata 和完整 duration。
- 部分配置字段仍为保留项，后续应实现或移除。

## 后续优先级

1. 为 Web API 增加局域网认证或可选访问令牌。
2. 对配置更新增加后端校验和明确的热重载能力边界。
3. 为大文件流式代理增加更多上游异常与 Range 集成测试。
4. 整理 AirPlay 兼容矩阵并补充真实设备回归。
5. 将保留配置字段实现或迁移清理。

## 发版检查

- 更新 `pyproject.toml` 与 `src/miairx/__init__.py` 版本
- 更新 CHANGELOG/Release notes 和必要文档
- 确认 Python、frontend、Playwright、wheel 构建通过
- 确认 GHCR amd64/arm64 镜像通过
- 从干净环境安装 wheel 做一次启动检查
- Docker 使用 host 网络做一次真实 SSDP 发现检查
