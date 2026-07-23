# MiAirX 项目交接文档

## 项目概述

MiAirX 是基于原始 MiAir 项目的现代化重构版本，为小米 AI 音箱提供 DLNA 和 AirPlay 支持。

**项目位置**: `C:\Users\jxy\PycharmProjects\MiAirX`
**原始项目**: `C:\Users\jxy\PycharmProjects\MiAir`

## 快速启动

```bash
# 进入项目目录
cd C:\Users\jxy\PycharmProjects\MiAirX

# 安装依赖
py -m pip install aiohttp miservice-fork zeroconf pycryptodome structlog pydantic pydantic-settings

# 配置账号
# 编辑 conf/config.json，填入小米账号信息

# 启动服务
set PYTHONPATH=src
py -m miairx

# 或使用启动脚本
start.bat
```

## 项目结构

```
MiAirX/
├── src/miairx/
│   ├── __init__.py             # 版本: 1.0.0
│   ├── cli.py                  # 命令行入口
│   ├── app.py                  # 应用编排器（核心！）
│   ├── const.py                # 常量定义
│   ├── core/                   # 核心模块
│   ├── config/                 # 配置模块
│   ├── auth/                   # 认证模块
│   ├── speaker/                # 音箱控制
│   ├── protocols/
│   │   ├── dlna/               # DLNA 协议（重点）
│   │   └── airplay/            # AirPlay 协议
│   ├── media/                  # 媒体处理
│   └── web/                    # Web 管理
├── tests/                      # 测试
├── conf/config.json            # 配置文件
├── start.bat                   # Windows 启动脚本
└── README.md                   # 文档
```

## 核心模块说明

### 1. app.py - 应用编排器

这是整个应用的核心，负责：
- 初始化所有组件
- 启动 DLNA/AirPlay/Web 服务器
- 健康检查和状态轮询
- 状态同步逻辑（关键！）

**重要函数**:
- `start()`: 启动应用
- `_poll_speaker_states()`: 轮询音箱状态
- `_sync_renderer_state()`: 同步渲染器状态（有重要保护逻辑）
- `_auto_resume_after_delay()`: 自动恢复播放

### 2. protocols/dlna/renderer.py - DLNA 渲染器

DLNA 渲染器状态机，处理：
- 播放/暂停/停止/Seek
- 位置追踪
- 状态通知

**重要方法**:
- `set_av_transport_uri()`: 设置媒体 URI
- `play()`: 开始播放（支持从暂停位置继续）
- `pause()`: 暂停
- `stop()`: 停止
- `seek()`: 跳转
- `notify_state_change()`: 发送状态变更通知

### 3. protocols/dlna/server.py - DLNA HTTP 服务器

处理所有 HTTP 请求：
- 设备描述 XML
- SOAP 控制请求
- 事件订阅
- 媒体代理

**重要方法**:
- `_handle_device_request()`: 处理设备请求
- `_handle_soap()`: 处理 SOAP 请求
- `_handle_event()`: 处理事件订阅
- `_handle_media_request()`: 处理媒体代理请求
- `create_proxy_url()`: 创建代理 URL
- `create_seek_url()`: 创建 Seek URL（关键！）

### 4. protocols/dlna/eventing.py - 事件管理

管理 UPnP 事件订阅：
- 订阅/续订/取消
- 发送事件通知
- 持久 HTTP session

**重要函数**:
- `build_last_change_event()`: 构建 LastChange 事件 XML

### 5. media/buffer.py - 媒体缓冲

异步下载音频文件：
- 支持 Range 请求
- 内存管理
- 下载完成检测

## 关键实现细节

### 1. 状态同步保护逻辑（app.py）

```python
async def _sync_renderer_state(self, udn, renderer, speaker_status):
    # 1. TRANSITIONING 保护：play()/seek() 执行中不覆盖状态
    if old_state == TransportState.TRANSITIONING:
        return
    
    # 2. 宽限期保护：宽限期内不覆盖 PLAYING 状态
    if renderer._play_grace_until > 0 and time.time() < renderer._play_grace_until:
        return
    
    # 3. PAUSED -> PLAYING 跳过
    if old_state == TransportState.PAUSED and new_state == TransportState.PLAYING:
        return
    
    # 4. STOPPED -> PAUSED 转换：保持播放位置
    if new_state == TransportState.STOPPED:
        renderer.transport_state = TransportState.PAUSED  # 不是 STOPPED！
        # 启动自动恢复
```

### 2. SOAP 响应格式（templates.py）

必须使用和原项目完全一致的格式：
```python
def soap_response(service_urn, action, params):
    params_xml = ""
    for key, value in params.items():
        params_xml += f"        <{key}>{escape(str(value))}</{key}>\n"
    
    return f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
            s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:{action}Response xmlns:u="{service_urn}">
{params_xml}    </u:{action}Response>
  </s:Body>
</s:Envelope>"""
```

### 3. 事件订阅响应（server.py）

SUBSCRIBE 响应后必须发送初始事件：
```python
async def _handle_event(self, request, renderer):
    if request.method == "SUBSCRIBE":
        sid = manager.subscribe(callback, timeout)
        
        # 重置音量初始化标志
        renderer._volume_initialized = False
        
        # 发送初始事件（后台任务）
        asyncio.create_task(self._send_initial_event(manager, sid, renderer))
        
        return web.Response(
            status=200,
            headers={"SID": sid, "TIMEOUT": f"Second-{timeout}"},
        )
```

### 4. 媒体代理（server.py）

必须等待下载完成后再提供服务：
```python
async def _handle_media_request(self, request):
    # 等待下载完成（像原项目一样）
    if not buffer.is_complete and not buffer.is_error:
        success = await buffer.wait_ready(timeout=120)
    
    # 使用 web.StreamResponse 流式传输
    response = web.StreamResponse(status=200, headers=headers)
    await response.prepare(request)
    await response.write(data)
```

### 5. Seek 功能（server.py）

暂停后从原位置继续播放：
```python
async def create_seek_url(self, original_url, seek_seconds, duration, udn):
    # 1. 等待缓冲完成
    await buffer.wait_ready()
    
    # 2. 尝试 FFmpeg seek
    seeked_data = await self._ffmpeg_seek(data, seek_seconds, content_type)
    
    # 3. 回退：格式感知 seek
    if seeked_data is None:
        seeked_data = self._format_seek(data, seek_ratio, content_type)
    
    # 4. 创建新的 seeked 缓冲
    seek_buf = MediaBuffer(original_url)
    seek_buf.data = seeked_data
    seek_buf.is_complete = True
```

## 遇到的问题及解决方案

### 问题 1: DLNA 发现失败

**原因**: SSDP 使用了错误的事件循环函数

**解决方案**:
```python
# 错误
asyncio.get_event_loop().call_later(...)

# 正确
asyncio.get_running_loop().call_later(...)
```

### 问题 2: QQ音乐连接后秒断

**原因**: SOAP 响应格式不一致

**解决方案**:
- 使用 `escape()` 转义参数值
- 使用 `utf-8` 编码（小写）
- 使用和原项目完全一致的缩进格式

### 问题 3: 播放后秒断

**原因**: 健康检查轮询没有保护逻辑

**解决方案**:
- 实现 TRANSITIONING 保护
- 实现宽限期保护
- 实现 PAUSED -> PLAYING 跳过
- 实现 STOPPED -> PAUSED 转换

### 问题 4: 媒体代理失败

**原因**: 没有等待下载完成

**解决方案**:
```python
# 等待下载完成
success = await buffer.wait_ready(timeout=120)
```

### 问题 5: 暂停后从头播放

**原因**: 没有实现 seek_url_func

**解决方案**:
- 实现 `create_seek_url` 方法
- 使用 FFmpeg 或格式感知的 seek

### 问题 6: asyncio 未导入

**原因**: server.py 缺少 `import asyncio`

**解决方案**: 添加 `import asyncio`

### 问题 7: HTTP 响应头冲突

**原因**: 同时设置 `content_type` 和 `headers`

**解决方案**: 只使用 `content_type` 参数

## 原项目关键文件参考

原始 MiAir 项目位于 `C:\Users\jxy\PycharmProjects\MiAir`，关键文件：

- `miair/dlna/renderer.py`: DLNA 渲染器状态机
- `miair/dlna/device_server.py`: DLNA HTTP 服务器（1443 行，God Object）
- `miair/dlna/eventing.py`: 事件管理
- `miair/dlna/templates.py`: XML 模板
- `miair/dlna/soap_handler.py`: SOAP 处理
- `miair/dlna/ssdp.py`: SSDP 发现
- `miair/airplay/server.py`: AirPlay 服务器
- `miair/speaker.py`: 音箱控制
- `miair/auth.py`: 认证管理

## 测试

```bash
# 运行所有测试
set PYTHONPATH=src
py -m pytest tests/ -v

# 运行特定测试
py -m pytest tests/unit/test_dlna_renderer.py -v
```

**测试结果**: 85 个测试全部通过

## 待完成工作

### 1. AirPlay 功能完善

- [ ] FairPlay3 DRM 支持
- [ ] 更多 iOS 版本兼容
- [ ] 多房间同步

### 2. 媒体处理优化

- [ ] 更多音频格式支持
- [ ] 流式转码（不等待下载完成）
- [ ] 内存优化

### 3. Web UI 改进

- [ ] 更丰富的管理功能
- [ ] 实时状态更新
- [ ] 移动端优化

### 4. 测试完善

- [ ] 集成测试
- [ ] 端到端测试
- [ ] 性能测试

### 5. 文档完善

- [ ] 用户手册
- [ ] 开发者文档
- [ ] API 文档

## 注意事项

1. **严格遵循原项目逻辑**: DLNA 协议有很多细节，必须严格遵循原项目的实现
2. **SOAP 响应格式**: 必须使用 `escape()` 转义，使用 `utf-8` 编码
3. **事件订阅**: SUBSCRIBE 响应后必须发送初始事件
4. **状态同步**: 必须有保护逻辑，避免覆盖 PLAYING 状态
5. **媒体代理**: 必须等待下载完成后再提供服务
6. **Seek 功能**: 暂停后必须从原位置继续播放

## 联系方式

如有问题，请参考：
- 原始项目: `C:\Users\jxy\PycharmProjects\MiAir`
- 项目文档: `README.md`
- 测试文件: `tests/`

---

**最后更新**: 2026-07-22
**项目状态**: ✅ 核心功能完成，可正常使用
