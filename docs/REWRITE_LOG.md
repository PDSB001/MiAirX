# MiAirX 修复日志

## 性能优化：第一批 (2026-07-23)

### 12. app.py — 健康检查并行化
- **瓶颈**: `_poll_speaker_states()` 对所有音箱串行轮询，每个 `get_status()` 可耗时 10s，N 音箱最坏 N×10s
- **修复**: 提取 `_poll_one_renderer()` 为模块级协程，`_poll_speaker_states()` 改为 `asyncio.gather(*tasks)` 并行执行
- **配套**: `import time` 和 `TRANSPORT_STATE_*` 移到模块顶部，`_handle_state_transition` 清理局部 import，`_STATUS_MAP` 提为模块级常量避免每轮重建 dict
- **收益**: 2 音箱轮询周期从最长 20s 降到 10s
- **回滚**: 恢复 `_poll_speaker_states` 为串行 `for` 循环，恢复局部 import

### 13. server.py — 消除 full buffer copy (memoryview)
- **瓶颈**: `_handle_media_request` L480 `data = bytes(buffer.data)` 全量复制整首音频到新内存
- **修复**: 改用 `data_view = memoryview(buffer.data)`，`memoryview[pos:chunk_end]` 切片零拷贝；`_handle_range_request` 签名从 `bytes` 改为 `memoryview`
- **收益**: 50MB 音频从峰值 ~100MB（原数据 + copy）降到 ~50MB
- **回滚**: 恢复 `data = bytes(buffer.data)`，`_handle_range_request` 参数类型改回 `bytes`

### 14. server.py — Buffer TTL 自动清理
- **瓶颈**: `_media_buffers`/`_proxy_tokens`/`_url_to_buffer` 只增不减，播 10 首后 10 个完整音频全在内存中
- **修复**: 新增 `_gc_buffers()` 后台任务（每 60s 清理 300s 未访问的 buffer），`start()` 中启动，`stop()` 中取消
- **收益**: 自动回收旧歌 buffer，防止无限增长
- **回滚**: 删除 `_gc_buffers` 方法，`start()`/`stop()` 中删除相关 GC 代码

## 性能优化：第二批 (2026-07-23)

### 15. server.py — 消除 O(n) token 扫描 (_buffer_to_token)
- **瓶颈**: `create_proxy_url` L75-78 对 `_proxy_tokens` 做 O(n) 扫描找 token，buffer 越多越慢
- **修复**: 新增 `_buffer_to_token: dict[str, str]` 反向索引；`create_proxy_url` 改用 `_buffer_to_token.get(buffer_id)` O(1)；`create_seek_url` 和 `_gc_buffers` 同步维护
- **收益**: 已有 buffer 的 token 查找从遍历全部→一次字典查表
- **回滚**: 删除 `_buffer_to_token` 字典及相关代码，恢复 `create_proxy_url` 的 for 循环扫描

### 16. eventing.py — 事件通知并行化
- **瓶颈**: `notify()` L93-94 fire-and-forget 为每个订阅者创建 task，无超时控制，慢订阅者可能卡住整个通知
- **修复**: 改为 `asyncio.gather(*tasks)` 并行发送，每个订阅者 `asyncio.wait_for(timeout=5.0)`；内部 `_notify_one` 捕获 TimeoutError 自己处理，外层 `return_exceptions=True`
- **收益**: 多订阅者并发 NOTIFY，单个僵尸连接 5s 超时自动跳过
- **回滚**: 恢复 `notify()` 为 `for sid, sub: asyncio.create_task(self._send_notify(sub, event_xml))`

## 性能优化：第三批 (2026-07-23)

### 17. ssdp.py — SSDP 消息预构建缓存
- **瓶颈**: 每 30s `_send_alive` 和每次 M-SEARCH 都动态构造字符串 + encode，共 6 条/渲染器
- **修复**: `register_renderer` 时 `_pre_build_messages()` 一次性构建所有 NOTIFY alive 和 M-SEARCH 响应的 bytes，存入 `_alive_msgs` 和 `_msearch_replies` 缓存；`_send_alive` 和 `handle_msearch` 直接用缓存
- **收益**: 周期性 alive 和 M-SEARCH 响应从"字符串拼接+encode"变成 O(1) 查表
- **回滚**: 删除 `_alive_msgs`/`_msearch_replies` 缓存，恢复 `_send_alive` 中的 `_build_notify_alive()` 调用和 `handle_msearch` 中的 `_build_msearch_response()` 调用

### 18. server.py — FFmpeg Seek 管道化
- **瓶颈**: `_ffmpeg_seek` 将全部音频数据写入临时文件 → FFmpeg 读文件 → 输出到另一临时文件 → Python 再读回，多一次磁盘 I/O
- **修复**: 改用 `-i pipe:0` + `pipe:1`，通过 `process.communicate(input=data)` 在内存管道完成全部操作；新增 30s timeout 保护
- **收益**: 无临时文件，无磁盘 I/O
- **注意**: 部分音视频格式的 FFmpeg 管道模式可能需要 format probe，如不稳定则回退磁盘方式
- **回滚**: 恢复 tempfile + NamedTemporaryFile 版本

### 19. app.py — AirPlay 停止并行化
- **瓶颈**: `_stop_airplay_server` 串行 `await airplay.stop()`，多 AirPlay 服务逐个等待
- **修复**: 改为 `asyncio.gather(*tasks)` 并行停止，每个 `asyncio.wait_for(timeout=5.0)`
- **收益**: N 个 AirPlay 服务停止从 N×stop_time 降到 max(stop_time)
- **回滚**: 恢复为 `for did, airplay: await airplay.stop()` 串行循环

## 杂项优化 (2026-07-23)

### 20. 默认音量 38→40
- **文件**: `config/models.py`, `renderer.py`, `config-example.json`
- **回滚**: 三个文件中 `38`/`50` 改回原值

### 21. 日志分级 (默认 WARNING+)
- **文件**: `core/logging.py`, `app.py`, `server.py`
- **修改**: 默认 console 日志级别从 INFO→WARNING，`-v` 模式下仍为 DEBUG；文件日志始终 DEBUG
- **配套**: 核心启停消息从 `log.info`→`log.warning`（启动/停止/DLNA 启停/Buffer GC），其余内部日志（状态同步、renderer 注册、代理创建等）保持 INFO 默认不可见
- **回滚**: `core/logging.py` 中 `console_level` 恢复为 `logging.DEBUG if verbose else logging.INFO`；恢复被提升到 WARNING 的 info 消息

---

## 本次修复内容 (2026-07-22)

### 1. media/proxy.py — 键值反转 Bug (运行时)
- **问题**: `register_buffer()` 第49行 `self._url_to_token[token] = url`，键值反了
- **影响**: 同 URL 去重失效，重复创建 buffer，内存泄漏
- **修复**: 改为 `self._url_to_token[url] = token`

### 2. web/api.py — 删除死代码
- **问题**: 整个文件 193 行未被任何代码引用，`web/app.py` 已自含同名处理器
- **修复**: 删除文件

### 3. core/lifecycle.py — 弃用 API
- **问题**: 第76行 `asyncio.get_event_loop()` 在 Python 3.10+ 产生 DeprecationWarning
- **修复**: 改为 `asyncio.get_running_loop()`

### 4. protocols/dlna/eventing.py — 弃用 API
- **问题**: 3处 `asyncio.get_event_loop().time()` 产生 DeprecationWarning
- **修复**: 全部改为 `time.monotonic()`，添加 `import time`

### 5. protocols/dlna/server.py — 清理死代码
- **问题**: `_handle_range_request` 中创建 `StreamResponse` 但从未使用
- **修复**: 删除 4 行死代码

### 6. protocols/dlna/renderer.py — 从 MiAir 完整搬运
- **来源**: `MiAir/miair/dlna/renderer.py`
- **适配点** (仅以下4处与 MiAir 不同):
  - 类名 `DLNARenderer` → `DlnaRenderer`
  - import 路径 `miair.*` → `miairx.*`
  - `event_manager.notify_all(event_xml)` → `event_manager.notify(self)`
  - 添加 `TransportState` 兼容类 (供 `__init__.py` 导入)
- **逻辑**: 与 MiAir 逐字节一致，零修补

### 7. app.py 健康检查 — 从 MiAir 完整搬运
- **来源**: `MiAir/miair/dlna/device_server.py` 的 `_poll_speaker_states` / `_handle_state_transition` / `_auto_resume_after_delay`
- **适配点** (仅以下1处与 MiAir 不同):
  - MiAir 的 `get_status()` 返回 dict，用 `status.get("status", 0)`
  - MiAirX 的 `get_status()` 返回 int，直接用 `speaker_status`
- **逻辑**: 与 MiAir 逐字节一致，零修补

### 8. speaker/controller.py — get_status() 错误语义修复 (幽灵暂停/进度回退根因)
- **问题**: `get_status()` 的 `except Exception` 返回 `SpeakerStatus.STOPPED`，把所有瞬态错误（网络抖动/超时/登录失败）都翻译成"音箱停止了"。健康检查拿到这个假 STOPPED → 触发 `STOPPED→PAUSED` → 广播 UPnP 给 QQ 音乐 → 幽灵暂停 → QQ 音乐发 Play 恢复 → 重新生成 Seek URL → 进度回退
- **根因分析**: MiAir 的 `get_status()` 返回 dict，出错时语义不同；MiAirX 的 int 返回值 + `except: return STOPPED` 让错误和真实停止无法区分。健康检查是按 MiAir 设计的，假设 `get_status()` 不会把错误伪装成 STOPPED
- **修复**: 
  - `except Exception: return STOPPED` → 删除 try/except，让异常向上传播
  - 非 dict 响应（None/格式异常）→ `raise RuntimeError` 而非返回 STOPPED
  - 两个调用点（`app.py` 健康检查、`airplay/speaker_airplay.py` 轮询）都已有 `except Exception` 保护，会 `continue`/`log.warning` 跳过该轮，不误判为真实停止
- **回滚**: 第 161-175 行恢复为原 `try/except: return SpeakerStatus.STOPPED` 结构（会重新引入幽灵暂停）

### 11. app.py — 代理模式不信任音箱假 STOPPED (进度回撤真正根因)
- **确诊**: 日志 `PAUSED_PLAYBACK -> PAUSED (保持位置)` 持续刷屏。小爱音箱的 `player_get_status` API **不报告代理 URL 的播放状态**（DLNA 投送的代理流不被 API 识别为"播放中"），持续返回 `status=0`。健康检查拿这个假 STOPPED 反复触发 `PLAYING→PAUSED`，位置永久冻结在 `_accumulated_time`，QQ 音乐轮询 GetPositionInfo 发现位置卡住 → 发 Play 纠正 → `play()` 用冻结的 `resume_position` 生成 seek URL → 把音箱拉回冻结点 → 进度回撤
- **为何前序修复无效**: 第 8/9/10 项都假设音箱"偶发"报 STOPPED；实际是"持续"报 STOPPED（API 行为），`PAUSED→PLAYING` 恢复永远等不到 PLAYING
- **修复**: 健康检查里，代理模式（`proxy_url_func` 存在 + 有 `current_uri`）下 `PLAYING→STOPPED` 转换直接 `continue`——renderer 的 `play()` 成功即代表在播放，位置由 `_play_start_time` 实时追踪，不依赖音箱 API 确认
- **非代理模式不受影响**: 直接 URL 投送时音箱 API 报告正确状态，仍走原逻辑
- **回滚**: 删除 grace period 检查后新增的 `if (new_state == STOPPED and old_state == PLAYING and proxy_url_func ...): continue` 块

### 10. app.py — PAUSED→PLAYING 恢复位置追踪 (幽灵进度回撤根因)
- **确诊链路**: 音箱偶发真实报 STOPPED → 健康检查 STOPPED→PAUSED 时 `_play_start_time=0`（位置冻结在 `_accumulated_time`）→ 下一轮音箱恢复 PLAYING 但 `PAUSED→PLAYING` 被**无条件 continue** → renderer 永久卡 PAUSED、位置永远冻结 → QQ 音乐轮询 GetPositionInfo 发现位置卡住 → 主动发 Play 恢复 → `play()` 用落后的 `_accumulated_time` 生成 seek URL → 把已播到后面的音箱**强制拉回冻结点** → 进度回撤
- **修复1** (`_poll_speaker_states`): `PAUSED→PLAYING` 的 `continue` 前加 `if renderer._user_stopped`——用户主动暂停才跳过；健康检查假暂停（`_user_stopped=False`）放行恢复位置追踪
- **修复2** (`_handle_state_transition` PAUSED→PLAYING 分支): 恢复时用 `_stuck_paused_since` 补偿假暂停期间冻结的时间到 `_accumulated_time`，避免位置整体落后
- **为何 MiAir 无此修复**: MiAir 第 1294 行同样无条件跳过 `PAUSED→PLAYING`，存在**相同潜在 bug**，但 MiAir 用户场景（音箱型号/DLNA 客户端）未触发；MiAirX 的"小爱音箱 Play 增强版 + QQ 音乐"恰好触发
- **配套关系**: 与第 9 项（STOPPED→PAUSED 抑制广播）配合——第 9 项防止 QQ 音乐收到假 PAUSED，第 10 项防止位置冻结后被拉回
- **回滚**: 恢复第 371 行为无条件 `continue`；恢复 `_handle_state_transition` PAUSED→PLAYING 分支为仅 `_play_start_time = time.time()`

### 9. app.py — 健康检查 STOPPED→PAUSED 抑制广播 (幽灵暂停残余根因)
- **问题**: `get_status()` 修复后，音箱**本身**偶发真实返回 `status=0`（缓冲切换/内部状态跳变）仍会触发 `STOPPED→PAUSED`，外层无条件 `notify_state_change()` 广播 PAUSED 给 QQ 音乐 → 幽灵暂停 → QQ 音乐发 Play 恢复 → 重新生成 Seek URL → 进度回退
- **修复**: `_poll_speaker_states` 第 379 行，`notify_state_change()` 前加条件：`new_state == STOPPED and not _user_stopped` 时跳过。用户主动 pause/stop（`_user_stopped=True`）仍正常广播
- **为何 MiAir 原版无此补丁**: MiAir 用户少用 QQ 音乐媒体代理，PAUSED 事件敏感度低；MiAirX 场景下 QQ 音乐对 PAUSED 高度敏感，属必要适配
- **回滚**: 删除第 379-386 行的 `if not (...)` 条件，恢复为无条件 `await renderer.notify_state_change()`

## 回滚方法

### PyCharm Local History (推荐)
1. 右键文件 → Local History → Show History
2. 选择 2026-07-22 修复前的版本 → Revert

### 手动回滚
- `media/proxy.py`: 第49行改回 `self._url_to_token[token] = url` (会重新引入 bug)
- `web/api.py`: 从 Local History 恢复
- `renderer.py` / `app.py`: 从 `MiAir/miair/` 重新搬运

## 文件状态总览

| 文件 | 状态 | 说明 |
|------|------|------|
| media/proxy.py | 已修 | 键值反转 bug |
| web/api.py | 已删 | 死代码 |
| core/lifecycle.py | 已修 | 弃用 API |
| protocols/dlna/eventing.py | 已修 | 弃用 API |
| protocols/dlna/server.py | 已修 | 清理死代码 |
| protocols/dlna/renderer.py | 已搬运 | 从 MiAir 完整搬运 |
| app.py | 已搬运 | 健康检查从 MiAir 搬运 |
| 其余 38 个文件 | 无需改动 | 审计通过 |
