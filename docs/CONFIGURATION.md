# 配置参考

MiAirX 默认从 `conf/config.json` 读取配置。第一次通过 `start.py` 启动时会从 `config-example.json` 创建该文件；通过 wheel 直接运行时，配置存储也会在需要时创建目录。

> `conf/config.json` 含账号、密码或 Cookie，已被 Git 忽略。不要上传、粘贴到公开 Issue 或打进镜像。

## 配置来源与优先级

```text
命令行参数 > 环境变量 > conf/config.json > 默认值
```

通过 `--config` 可以切换配置目录：

```bash
miairx --config /path/to/conf
```

## 最小配置

推荐先启动管理台，再在页面中填写凭据并选择设备。手工配置的最小示例：

```json
{
  "account": "your-xiaomi-account",
  "password": "your-password",
  "mi_did": "123456789",
  "hostname": "192.168.1.10"
}
```

多音箱使用逗号分隔：

```json
{
  "mi_did": "123456789,987654321"
}
```

## 登录方式

### 账号密码

填写 `account` 和 `password`。如果小米登录风控阻止密码登录，可以改用 Cookie。

### Cookie

Cookie 字符串至少需要 `userId` 和 `passToken`：

```json
{
  "cookie": "userId=123456; passToken=replace-with-your-token"
}
```

管理台只显示凭据已经保存，不会回显原值。留空保存会保留已有敏感值；填写新值才会替换。

## 字段表

| 字段 | 默认值 | 当前行为 |
|---|---:|---|
| `account` | `""` | 小米账号 |
| `password` | `""` | 小米账号密码 |
| `cookie` | `""` | `userId`/`passToken` 登录字符串，优先用于 Cookie 登录 |
| `mi_did` | `""` | 一个或多个设备 DID，逗号分隔 |
| `hostname` | 自动检测 | 必须是手机和音箱可访问的主机 IPv4 地址 |
| `dlna_port` | `8200` | DLNA HTTP、SOAP 和媒体代理端口 |
| `web_port` | `8300` | 管理台和 JSON API 端口 |
| `airplay_port_start` | `7000` | AirPlay 固定 TCP 端口段起点；每台启用音箱依次占用两个端口 |
| `conf_path` | `"conf"` | 配置及日志目录；通常通过 `--config` 设置 |
| `verbose` | `false` | 开启详细日志；启动时读取 |
| `auto_resume_on_interrupt` | `false` | DLNA 播放被外部状态打断时尝试恢复 |
| `resume_delay_seconds` | `5` | 自动恢复等待时间；模型会限制在 1–15 秒 |
| `default_volume` | `30` | 不跟随设备音量时，首次播放应用的音量 |
| `follow_device_volume` | `true` | 保留音箱当前音量，不主动套用默认音量 |
| `auto_restart` | `false` | 连续登录失败达到阈值时请求进程退出；需 Docker/systemd 等监督器负责拉起 |
| `proxy_enabled` | `false` | 兼容性保留字段；当前 DLNA 路径会自动使用媒体代理 |
| `auto_play_on_set_uri` | `false` | 兼容性保留字段；当前版本尚未接入播放状态机 |
| `enable_voice_control` | `false` | 兼容性保留字段；当前版本尚未接入独立语音控制器 |
| `voice_poll_interval` | `1` | 与语音控制器配套的保留字段，当前不生效 |
| `speakers` | `{}` | 每台音箱的详细信息，由程序和设备选择流程维护 |

## 环境变量

| 变量 | 类型 | 说明 |
|---|---|---|
| `MI_USER` | string | 小米账号 |
| `MI_PASS` | string | 小米密码 |
| `MI_DID` | string | DID 列表 |
| `MIAIR_HOSTNAME` | string | 主机局域网 IPv4 |
| `MIAIR_DLNA_PORT` | integer | DLNA 端口 |
| `MIAIR_WEB_PORT` | integer | Web 端口 |
| `MIAIR_AIRPLAY_PORT_START` | integer | AirPlay TCP 起始端口 |
| `MIAIR_VERBOSE` | boolean | `true`、`1` 或 `yes` 表示开启 |

Docker Compose 可以把敏感值放进未提交的 `.env` 文件，而不是直接写进 Compose 文件：

```dotenv
MI_USER=your-account
MI_PASS=your-password
MI_DID=
MIAIR_HOSTNAME=192.168.1.10
MIAIR_AIRPLAY_PORT_START=7000
```

## 命令行参数

```text
--config, -c       配置目录
--verbose, -v      详细日志
--account, -a      小米账号
--password, -p     小米密码
--did, -d          设备 DID
--hostname         对外广播的主机地址
--dlna-port        DLNA 端口
--web-port         管理台端口
--airplay-port-start  AirPlay TCP 起始端口
--version          显示版本
```

完整帮助以当前安装版本为准：

```bash
miairx --help
```

## 修改何时生效

管理台会把配置写入文件，但不会主动重启服务。以下变化必须手动重启：

- 账号、密码或 Cookie
- 音箱 DID 列表
- 主机地址、DLNA/Web 端口和 AirPlay 起始端口
- 详细日志和运行策略

只在管理台中调整音量或发送播放控制，不需要重启。

## 旧配置升级

旧版 `conf/config.json` 可以直接用于新版 MiAirX，不需要手工补字段：

- 缺少 `airplay_port_start` 时使用默认值 `7000`。
- 已有账号、Cookie、DID、音箱配置和 DLNA/Web 端口保持不变。
- 新版管理台保存后会把新增字段写回配置文件。
- 未识别的历史字段会被忽略，不会阻止应用启动。

使用 Docker 时，环境变量优先于 `config.json`。例如 `.env` 中存在 `MIAIR_AIRPLAY_PORT_START=17000`，即使管理台保存为 7000，重启容器后仍会被环境变量覆盖。

端口与宿主机防火墙的对应关系见 [防火墙与局域网发现](FIREWALL.md)。

## 安全建议

- 只在可信局域网开放 8300；管理台当前没有认证。
- 不要把 `conf/` 挂载到多人可读目录。
- Docker/NAS 上建议限制配置目录权限。
- 分享日志前搜索并移除账号、DID、媒体 URL 和局域网地址。
