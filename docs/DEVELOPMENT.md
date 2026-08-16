# 开发指南

## 环境

- Python 3.12+
- Node.js 22+；CI 和 Docker 使用 Node 24
- pnpm 11.19.0
- FFmpeg：本地可选，媒体转换和可靠 Seek 建议安装

## 后端开发

```bash
python -m pip install -e ".[dev]"
pytest tests -q
```

Windows 上没有 `python` 命令时，可以使用：

```powershell
py -3 -m pip install -e ".[dev]"
$env:PYTHONPATH = (Resolve-Path src).Path
py -3 -m pytest tests -q
```

启动：

```bash
miairx --verbose
```

或从源码直接启动：

```bash
python start.py
```

## 前端开发

管理台位于 `frontend/`，使用 React、TypeScript、Vite、TanStack Query、Tailwind 基础层和 CSS 变量设计系统。

先启动 MiAirX 后端，再开一个终端：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

访问：

```text
http://127.0.0.1:5173/static/app/
```

Vite 会把 `/api` 请求代理到 `http://127.0.0.1:8300`。开发地址使用 `/static/app/` 是为了与生产资源基址保持一致。

## 前端构建

```bash
cd frontend
pnpm build
```

输出目录是：

```text
src/miairx/web/static/app/
```

生产资源需要提交到仓库，原因是：

- wheel/sdist 构建不要求使用者安装 Node。
- Python 包可以直接包含完整管理台。
- CI 会重新构建并用 `git diff` 检查产物是否与源码一致。

旧前端 `src/miairx/web/static/index.html` 保留为 `/legacy`，不要在构建时覆盖。

## 测试

### 前端完整检查

```bash
cd frontend
pnpm check
```

它依次运行：

1. TypeScript 严格类型检查
2. Vitest + Testing Library 单元测试
3. Vite 生产构建

### 浏览器冒烟测试

第一次运行需要安装 Chromium：

```bash
cd frontend
pnpm exec playwright install chromium
pnpm test:e2e
```

Playwright 使用路由 mock，不会控制真实音箱或修改真实配置，并覆盖桌面端和移动端导航。

### Python 检查

```bash
ruff check . --select E9,F63,F7,F82
pytest tests -q
python -m build
```

验证 wheel 是否包含前端：

```bash
unzip -l dist/*.whl | grep 'miairx/web/static/app'
```

Windows 可以使用 `tar -tf dist\miairx-*.whl` 查看 wheel 内容。

## Web API 契约

前端当前使用以下同源接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/status` | 版本和服务状态 |
| GET/POST | `/api/config` | 读取/保存配置 |
| GET | `/api/speakers` | 已注册音箱 |
| GET | `/api/devices` | 小米云设备 |
| GET | `/api/positions` | 播放位置和状态 |
| POST | `/api/play` | URL 播放 |
| POST | `/api/pause` | 暂停 |
| POST | `/api/stop` | 停止 |
| POST | `/api/volume` | 音量 |
| POST | `/api/seek` | 进度跳转 |

修改响应字段时要同步更新 `frontend/src/api/types.ts`、相关查询和测试。

## CI

`.github/workflows/ci.yml` 包含：

- Linux/Windows × Python 3.12/3.13 测试矩阵
- Ruff 关键错误检查
- Pyright 建议性检查
- 前端类型、单测和生产构建
- Playwright Chromium 冒烟测试
- 静态产物一致性检查
- wheel 和 sdist 构建

`.github/workflows/docker.yml` 在主分支、PR 和版本标签上构建多架构镜像；主分支和标签会推送到 GHCR。

## 提交前清单

```text
[ ] 没有提交 conf/config.json、token、媒体签名 URL
[ ] Python 测试通过
[ ] pnpm check 通过
[ ] pnpm test:e2e 通过
[ ] 生产静态资源已更新
[ ] 用户可见变化已更新 README/docs
[ ] Dockerfile 或依赖变化已检查多架构影响
```

## 发版

版本号至少需要在以下位置保持一致：

- `pyproject.toml`
- `src/miairx/__init__.py`

推荐流程：

```bash
pnpm --dir frontend check
pytest tests -q
python -m build
git tag vX.Y.Z
git push origin master --tags
```

发布前还应确认 GitHub Actions 和 Docker 多架构构建全部通过。
