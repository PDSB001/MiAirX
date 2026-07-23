# MiAirX 性能优化方案（仅代码，不实施）

---

## 目录

| # | 优化 | 影响等级 | 文件 | 预计收益 |
|---|------|---------|------|---------|
| 1 | 健康检查并行化 | 🔴 HIGH | `app.py` | 2音箱从 20s→10s 减少 50%+ |
| 2 | 消除 full buffer copy | 🔴 HIGH | `server.py` | 节省 50%+ 内存峰值 |
| 3 | Buffer TTL 自动清理 | 🔴 HIGH | `server.py` | 防止内存泄漏 |
| 4 | 消除 O(n) token 扫描 | 🟡 MED | `server.py` | create_proxy_url 从 O(n)→O(1) |
| 5 | 事件通知并行化 | 🟡 MED | `eventing.py` | N个订阅者从串行→并行 |
| 6 | 模块级导入 | 🟡 MED | `app.py` | 无意义损耗消除 |
| 7 | SSDP 消息缓存 | 🟢 LOW | `ssdp.py` | 减少 90%+ 字符串构造 |
| 8 | Range 请求避免拷贝 | 🟢 LOW | `server.py` | 减少小内存分配 |
| 9 | 渲染器状态读保护 | 🟢 LOW | `app.py` | 消除潜在竞态 |
| 10 | Seek FFmpeg 管道化 | 🟢 LOW | `server.py` | 减少磁盘 I/O |
| 11 | 停止流程并行化 | 🟢 LOW | `app.py` | 加速启动/停止 |

---

## 优化 1：健康检查并行化 🔴 HIGH

**瓶颈**：`_poll_speaker_states()` 中所有音箱串行轮询。每个 `get_status()` 可能耗时 10 秒。2 个音箱最坏 = 20 秒周期，远超 5 秒设计间隔。

**当前代码** (`app.py:294-347`)：

```python
async def _poll_speaker_states(self) -> None:
    """Poll speaker states and sync with renderers (matches MiAir)."""
    import time
    from miairx.const import (
        TRANSPORT_STATE_PAUSED,
        TRANSPORT_STATE_PLAYING,
        TRANSPORT_STATE_STOPPED,
        TRANSPORT_STATE_TRANSITIONING,
    )

    for udn, renderer in self.renderers.items():
        if not renderer.speaker:
            continue

        # ... idle detection per renderer ...

        try:
            speaker_status = await asyncio.wait_for(
                renderer.speaker.get_status(), timeout=10
            )
        except Exception as e:
            log.warning(f"[{renderer.friendly_name}] Poll failed: {e}")
            continue

        # ... state sync per renderer ...
```

**优化后**：

```python
async def _poll_speaker_states(self) -> None:
    """Poll speaker states and sync with renderers (parallelized)."""
    # --- Extract per-renderer work into a helper coroutine ---
    async def _poll_one(self, udn: str, renderer: DlnaRenderer) -> None:
        """Poll a single renderer (runs concurrently with others)."""
        if not renderer.speaker:
            return

        # Idle detection
        idle = False
        if (
            renderer.current_uri
            and renderer.transport_state == TRANSPORT_STATE_PAUSED
            and renderer._stuck_paused_since > 0
            and (time.time() - renderer._stuck_paused_since) > 30
        ):
            if not renderer._user_stopped:
                idle = True
            elif renderer.event_manager and not renderer.event_manager.has_subscribers():
                idle = True
        elif (
            renderer.current_uri
            and renderer.transport_state == TRANSPORT_STATE_STOPPED
            and renderer._last_control_time > 0
            and (time.time() - renderer._last_control_time) > 60
            and renderer.event_manager
            and not renderer.event_manager.has_subscribers()
        ):
            idle = True

        if idle:
            await renderer.reset_to_idle()
            renderer._stuck_paused_since = 0.0
            return

        if not renderer.current_uri:
            return

        try:
            speaker_status = await asyncio.wait_for(
                renderer.speaker.get_status(), timeout=10
            )
        except Exception as e:
            log.warning(f"[{renderer.friendly_name}] Poll failed: {e}")
            return

        new_state = STATUS_MAP.get(speaker_status, TRANSPORT_STATE_STOPPED)
        if renderer.transport_state == new_state:
            return

        old_state = renderer.transport_state
        if old_state == TRANSPORT_STATE_TRANSITIONING:
            return
        if (
            renderer._play_grace_until > 0
            and time.time() < renderer._play_grace_until
            and old_state == TRANSPORT_STATE_PLAYING
            and new_state != TRANSPORT_STATE_PLAYING
        ):
            return
        if (
            new_state == TRANSPORT_STATE_STOPPED
            and old_state == TRANSPORT_STATE_PLAYING
            and renderer.proxy_url_func
            and renderer.current_uri
            and not renderer._user_stopped
        ):
            return
        if old_state == TRANSPORT_STATE_PAUSED and new_state == TRANSPORT_STATE_PLAYING:
            if renderer._user_stopped:
                return

        renderer.transport_state = new_state
        log_msg = self._handle_state_transition(udn, renderer, old_state, new_state)

        if not (new_state == TRANSPORT_STATE_STOPPED and not renderer._user_stopped):
            await renderer.notify_state_change()
        log.info(f"[{renderer.friendly_name}] State sync: {log_msg}")

    # --- Fire all polls concurrently ---
    tasks = [
        _poll_one(self, udn, renderer)
        for udn, renderer in self.renderers.items()
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

**注意**：需要将 `_poll_one` 提取为静态方法或在模块级别定义，以避免闭包捕获 `self` 两次。

更好的做法——提取为独立的 `PollState` 数据类：

```python
# 在 app.py 类外部定义（文件顶部附近）

_STATUS_MAP = {0: TRANSPORT_STATE_STOPPED, 1: TRANSPORT_STATE_PLAYING, 2: TRANSPORT_STATE_PAUSED}

async def _poll_one_renderer(app, udn: str, renderer) -> None:
    """Poll a single renderer's speaker state (for use with asyncio.gather)."""
    if not renderer.speaker:
        return

    if (
        renderer.current_uri
        and renderer.transport_state == TRANSPORT_STATE_PAUSED
        and renderer._stuck_paused_since > 0
        and (time.time() - renderer._stuck_paused_since) > 30
    ):
        idle = (not renderer._user_stopped) or (
            renderer.event_manager and not renderer.event_manager.has_subscribers()
        )
    elif (
        renderer.current_uri
        and renderer.transport_state == TRANSPORT_STATE_STOPPED
        and renderer._last_control_time > 0
        and (time.time() - renderer._last_control_time) > 60
        and renderer.event_manager
        and not renderer.event_manager.has_subscribers()
    ):
        idle = True
    else:
        idle = False

    if idle:
        await renderer.reset_to_idle()
        renderer._stuck_paused_since = 0.0
        return

    if not renderer.current_uri:
        return

    try:
        speaker_status = await asyncio.wait_for(
            renderer.speaker.get_status(), timeout=10
        )
    except Exception as e:
        log.warning(f"[{renderer.friendly_name}] Poll failed: {e}")
        return

    new_state = _STATUS_MAP.get(speaker_status, TRANSPORT_STATE_STOPPED)
    if renderer.transport_state == new_state:
        return

    old_state = renderer.transport_state
    if old_state == TRANSPORT_STATE_TRANSITIONING:
        return
    if (
        renderer._play_grace_until > 0
        and time.time() < renderer._play_grace_until
        and old_state == TRANSPORT_STATE_PLAYING
        and new_state != TRANSPORT_STATE_PLAYING
    ):
        return
    if (
        new_state == TRANSPORT_STATE_STOPPED
        and old_state == TRANSPORT_STATE_PLAYING
        and renderer.proxy_url_func
        and renderer.current_uri
        and not renderer._user_stopped
    ):
        return
    if old_state == TRANSPORT_STATE_PAUSED and new_state == TRANSPORT_STATE_PLAYING:
        if renderer._user_stopped:
            return

    renderer.transport_state = new_state
    log_msg = app._handle_state_transition(udn, renderer, old_state, new_state)

    if not (new_state == TRANSPORT_STATE_STOPPED and not renderer._user_stopped):
        await renderer.notify_state_change()
    log.info(f"[{renderer.friendly_name}] State sync: {log_msg}")
```

`_poll_speaker_states` 简化为：

```python
async def _poll_speaker_states(self) -> None:
    """Poll all speaker states in parallel."""
    tasks = [_poll_one_renderer(self, udn, r) for udn, r in self.renderers.items()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

**收益**：2 音箱从最长 20 秒（串行）降到 10 秒（并行），接近设计的 5 秒间隔。

---

## 优化 2：消除 full buffer copy 🔴 HIGH

**瓶颈**：`_handle_media_request` 第 480 行 `data = bytes(buffer.data)` 将整个音频文件内存复制一份。50MB 的 MP3 → 额外消耗 50MB。

**当前代码** (`server.py:479-507`)：

```python
        # Get data
        data = bytes(buffer.data)  # ← 完整复制！50MB MP3 → 50MB 额外内存
        total_size = len(data)
        content_type = buffer.content_type

        # Handle Range request
        range_header = request.headers.get("Range", "")
        if range_header:
            return self._handle_range_request(request, data, content_type, range_header)

        # Full request
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(total_size),
            "Accept-Ranges": "bytes",
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        # Send data in chunks
        pos = 0
        while pos < total_size:
            chunk_end = min(pos + 65536, total_size)
            await response.write(data[pos:chunk_end])  # ← 每次切片又产生小 copy
            pos = chunk_end

        await response.write_eof()
        return response
```

**优化后**（使用 `memoryview` 零拷贝切片）：

```python
        # --- Use memoryview for zero-copy slicing ---
        data_view = memoryview(buffer.data)  # 零拷贝视图，不复制数据
        total_size = len(data_view)
        content_type = buffer.content_type

        # Handle Range request (also using memoryview)
        range_header = request.headers.get("Range", "")
        if range_header:
            return self._handle_range_request_v2(
                request, data_view, content_type, range_header
            )

        # Full request
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(total_size),
            "Accept-Ranges": "bytes",
        }

        response = web.StreamResponse(status=200, headers=headers)
        await response.prepare(request)

        # Send data in chunks — memoryview slices are zero-copy
        CHUNK = 65536
        pos = 0
        while pos < total_size:
            chunk_end = min(pos + CHUNK, total_size)
            await response.write(data_view[pos:chunk_end])  # memoryview 切片不复制！
            pos = chunk_end

        await response.write_eof()
        return response
```

配合新增的 `_handle_range_request_v2`（见优化 8）。

**收益**：50MB 音频文件从峰值 ~100MB（原数据 + copy）降到 ~50MB。内存减半。

---

## 优化 3：Buffer TTL 自动清理 🔴 HIGH

**瓶颈**：`_media_buffers`、`_proxy_tokens`、`_url_to_buffer` 三个字典只增不减。旧歌的 buffer 永远不释放。播放 10 首歌后，10 个完整音频都在内存中。

**当前代码**：没有任何清理逻辑。

**优化后**（在 `DlnaHttpServer` 中新增）：

```python
    # 添加到 __init__:
    #   self._gc_task: Optional[asyncio.Task] = None

    async def _gc_buffers(self):
        """Periodic buffer garbage collection.
        
        每 60 秒清理超过 300 秒未访问的 buffer。
        """
        while True:
            try:
                await asyncio.sleep(60)
                
                now = time.time()
                expired_buffer_ids = []
                
                for bid, buf in self._media_buffers.items():
                    if buf.is_expired(max_age=300):
                        expired_buffer_ids.append(bid)
                
                for bid in expired_buffer_ids:
                    buf = self._media_buffers.pop(bid, None)
                    if buf:
                        buf.cancel()
                        buf.cleanup()
                
                # Clean up proxy_tokens pointing to expired buffers
                expired_tokens = []
                for token, (bid, udn) in self._proxy_tokens.items():
                    if bid not in self._media_buffers:
                        expired_tokens.append(token)
                for token in expired_tokens:
                    self._proxy_tokens.pop(token, None)
                
                # Clean up url_to_buffer for expired buffers
                expired_urls = []
                for url, bid in self._url_to_buffer.items():
                    if bid not in self._media_buffers:
                        expired_urls.append(url)
                for url in expired_urls:
                    self._url_to_buffer.pop(url, None)
                
                if expired_buffer_ids:
                    log.info(
                        f"Buffer GC: cleaned {len(expired_buffer_ids)} expired buffers, "
                        f"{len(self._media_buffers)} remaining"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Buffer GC error: {e}")

    def start(self) -> None:
        """Start the HTTP server."""
        # ... existing code ...
        self._gc_task = asyncio.create_task(self._gc_buffers())

    async def stop(self) -> None:
        """Stop the HTTP server."""
        if self._gc_task:
            self._gc_task.cancel()
        # ... existing code ...
```

**关联改动**：`MediaBuffer.read_range` 已在访问时更新 `self.last_accessed`（第 101 行），但 `_handle_media_request` 的直接读取没有。需要补：

```python
    # MediaBuffer 新增方法
    def touch(self):
        """Update last_accessed timestamp."""
        self.last_accessed = time.time()
```

在 `_handle_media_request` 优化版开头加 `buffer.touch()`。

**收益**：播放 10 首歌后自动回收前 9 首的内存，避免无限增长。

---

## 优化 4：消除 O(n) token 扫描 🟡 MED

**瓶颈**：`create_proxy_url` 第 74-77 行在已有 buffer 时做 O(n) 扫描找 token。buffer 越多越慢。

**当前代码** (`server.py:69-77`)：

```python
    def create_proxy_url(self, remote_url: str, udn: str) -> str:
        """Create a proxy URL for the given remote URL."""
        if remote_url in self._url_to_buffer:
            buffer_id = self._url_to_buffer[remote_url]
            # O(n) scan!
            for token, (bid, _) in self._proxy_tokens.items():
                if bid == buffer_id:
                    return f"http://{self.hostname}:{self.dlna_port}/media/{token}"
```

**优化后**（加一个反向索引）：

```python
    # 在 __init__ 中新增:
    #   self._buffer_to_token: dict[str, str] = {}  # buffer_id -> token

    def create_proxy_url(self, remote_url: str, udn: str) -> str:
        """Create a proxy URL for the given remote URL."""
        if remote_url in self._url_to_buffer:
            buffer_id = self._url_to_buffer[remote_url]
            # O(1) 直接查找！
            if buffer_id in self._buffer_to_token:
                token = self._buffer_to_token[buffer_id]
                return f"http://{self.hostname}:{self.dlna_port}/media/{token}"

        # Create new buffer and token
        buffer_id = secrets.token_urlsafe(16)
        token = secrets.token_urlsafe(16)

        buffer = MediaBuffer(remote_url)
        self._media_buffers[buffer_id] = buffer
        self._proxy_tokens[token] = (buffer_id, udn)
        self._buffer_to_token[buffer_id] = token  # ← 维护反向索引
        self._url_to_buffer[remote_url] = buffer_id

        # ... rest unchanged ...
```

**同步维护**：在 `create_seek_url` 和 `_gc_buffers` 中也维护 `_buffer_to_token`：

```python
    # create_seek_url 中新增 token 时:
    self._buffer_to_token[seek_bid] = token

    # _gc_buffers 清理时:
    for bid in expired_buffer_ids:
        self._buffer_to_token.pop(bid, None)
```

---

## 优化 5：事件通知并行化 🟡 MED

**瓶颈**：`EventManager.notify()` 第 93-94 行对每个订阅者 fire-and-forget 创建 task。可以更干净地用 `asyncio.gather`。

**当前代码** (`eventing.py:76-94`)：

```python
    async def notify(self, renderer) -> None:
        """Send notification to all subscribers (fire-and-forget)."""
        if not self._subscriptions:
            return

        event_xml = build_last_change_event(
            transport_state=renderer.transport_state,
            volume=renderer.volume,
        )

        expired_sids = [sid for sid, sub in self._subscriptions.items() if sub.expired]
        for sid in expired_sids:
            del self._subscriptions[sid]

        # Fire-and-forget — no error visibility, no concurrency control
        for sid, sub in self._subscriptions.items():
            asyncio.create_task(self._send_notify(sub, event_xml))
```

**优化后**（并行 gather，timeout 保护，避免无限制并发）：

```python
    async def notify(self, renderer) -> None:
        """Send notification to all subscribers in parallel (with timeout)."""
        if not self._subscriptions:
            return

        event_xml = build_last_change_event(
            transport_state=renderer.transport_state,
            volume=renderer.volume,
        )

        # Remove expired
        expired_sids = [sid for sid, sub in self._subscriptions.items() if sub.expired]
        for sid in expired_sids:
            del self._subscriptions[sid]

        if not self._subscriptions:
            return

        # Send to all subscribers in parallel, with per-subscriber timeout
        # Using asyncio.gather is cleaner than fire-and-forget tasks
        # and provides better error isolation
        async def _notify_one(sub: Subscription) -> None:
            try:
                await asyncio.wait_for(self._send_notify(sub, event_xml), timeout=5.0)
            except asyncio.TimeoutError:
                log.debug(f"Event notify timeout for {sub.sid}")
            except Exception as e:
                log.debug(f"Event notify failed for {sub.sid}: {e}")

        await asyncio.gather(
            *[_notify_one(sub) for sub in self._subscriptions.values()],
            return_exceptions=False  # we already catch inside _notify_one
        )
```

**收益**：多个订阅者的 NOTIFY 并发发送，不会被一个慢的订阅者卡住。且加了 5 秒 timeout 防止僵尸连接。

---

## 优化 6：模块级导入 🟡 MED

**瓶颈**：`_poll_speaker_states` 每 5 秒执行一次 `import time` 和 `from miairx.const import ...`。虽然 Python 有 import 缓存，但仍有字典查表开销。

**当前代码** (`app.py:296-302`)：

```python
    async def _poll_speaker_states(self) -> None:
        """Poll speaker states and sync with renderers (matches MiAir)."""
        import time                                            # ← 每次 import
        from miairx.const import (                             # ← 每次 import
            TRANSPORT_STATE_PAUSED,
            TRANSPORT_STATE_PLAYING,
            TRANSPORT_STATE_STOPPED,
            TRANSPORT_STATE_TRANSITIONING,
        )
```

**优化后**（移到文件顶部）：

```python
# 文件顶部（第 1 行附近已有 import asyncio, logging 等，直接加）
import time
from miairx.const import (
    TRANSPORT_STATE_PAUSED,
    TRANSPORT_STATE_PLAYING,
    TRANSPORT_STATE_STOPPED,
    TRANSPORT_STATE_TRANSITIONING,
)
```

同样，`_send_initial_event` 第 438 行的 `from miairx.protocols.dlna.eventing import build_last_change_event` 也应该移到文件顶部。

---

## 优化 7：SSDP 消息缓存 🟢 LOW

**瓶颈**：每 30 秒 `_periodic_alive` → `_send_alive()` 对每个 renderer 重新构造 6 条 NOTIFY 消息（字符串拼接 + encode）。

**当前代码** (`ssdp.py:180-187`)：

```python
    async def _send_alive(self):
        """Send NOTIFY alive."""
        if not self._transport:
            return
        for udn in self.renderers:
            for nt, usn in self._get_search_targets(udn):
                data = self._build_notify_alive(nt, usn, udn)
                self._transport.sendto(data, (SSDP_ADDR, SSDP_PORT))
```

**优化后**（注册时预构建缓存）：

```python
    # 在 __init__ 中新增:
    #   self._alive_msgs: dict[str, list[bytes]] = {}  # udn -> [msg_bytes, ...]

    def register_renderer(self, udn: str, friendly_name: str):
        """Register a renderer and pre-build SSDP messages."""
        self.renderers[udn] = friendly_name
        
        # Pre-build all alive messages for this renderer
        msgs = []
        for nt, usn in self._get_search_targets(udn):
            msgs.append(self._build_notify_alive(nt, usn, udn))
        self._alive_msgs[udn] = msgs
        
        log.info(f"SSDP registered renderer: {friendly_name} (uuid:{udn})")

    async def _send_alive(self):
        """Send pre-built NOTIFY alive messages."""
        if not self._transport:
            return
        for udn in self.renderers:
            for data in self._alive_msgs.get(udn, ()):
                self._transport.sendto(data, (SSDP_ADDR, SSDP_PORT))
```

同理缓存 M-SEARCH 响应：

```python
    # __init__ 新增:
    #   self._msearch_replies: dict[str, dict[str, bytes]] = {}  # udn -> {st: msg}

    def _build_all_msearch_replies(self, udn: str) -> dict[str, bytes]:
        """Pre-build all M-SEARCH reply messages for a renderer."""
        replies = {}
        for nt, usn in self._get_search_targets(udn):
            replies[nt] = self._build_msearch_response(nt, usn, udn)
        return replies

    def register_renderer(self, udn: str, friendly_name: str):
        # ... existing ...
        self._msearch_replies[udn] = self._build_all_msearch_replies(udn)

    def handle_msearch(self, data: bytes, addr: tuple):
        # ... parse st ...
        # 用缓存的消息
        for udn in self.renderers:
            msg = self._msearch_replies.get(udn, {}).get(st)
            if msg is not None:
                delay = random.uniform(0, mx)
                asyncio.get_running_loop().call_later(
                    delay, lambda m=msg, a=addr: self._transport.sendto(m, a)
                )
```

**收益**：每 30 秒省去字符串拼接 + encode。M-SEARCH 响应也从每次动态构建变成 O(1) 查表。

---

## 优化 8：Range 请求避免拷贝 🟢 LOW

**瓶颈**：`_handle_range_request` 第 530 行 `chunk = data[start:end+1]` 创建了另一个数据切片拷贝。

**当前代码** (`server.py:509-544`)：

```python
    def _handle_range_request(self, request, data, content_type, range_header):
        # data is bytes
        chunk = data[start:end + 1]  # ← 又拷贝
        return web.Response(body=chunk, status=206, headers=headers)
```

**优化后**（配合优化 2 的 memoryview）：

```python
    def _handle_range_request_v2(
        self,
        request: web.Request,
        data_view: memoryview,
        content_type: str,
        range_header: str,
    ) -> web.Response:
        """Handle Range request (zero-copy with memoryview)."""
        try:
            total_size = len(data_view)
            range_spec = range_header.replace("bytes=", "").strip()
            start_str, end_str = range_spec.split("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else total_size - 1
            end = min(end, total_size - 1)

            if start > end or start >= total_size:
                return web.Response(status=416, text="Range not satisfiable")

            # memoryview slices are zero-copy — just a view, no allocation
            chunk = data_view[start:end + 1]
            content_length = end - start + 1

            headers = {
                "Content-Type": content_type,
                "Content-Length": str(content_length),
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Accept-Ranges": "bytes",
            }

            # web.Response(body=memoryview) works — aiohttp supports it
            return web.Response(body=chunk, status=206, headers=headers)

        except Exception as e:
            log.error(f"Range request error: {e}")
            return web.Response(status=400, text="Invalid range")
```

**收益**：Range 请求不再产生额外内存分配。

---

## 优化 9：渲染器状态读保护 🟢 LOW

**瓶颈**：`_poll_speaker_states` 读取 `renderer.transport_state` 时没有加锁，与 `renderer.play()/pause()` 的写入存在理论上的竞态。

**说明**：在 CPython 的 GIL 下，字符串属性读写是原子的，不会出现"读到半个字符串"。且 asyncio 单线程不会中断。**实际风险极低**，主要为了标明意图。

**如需加锁**，在 `DlnaRenderer` 中新增一个读状态的方法：

```python
    # DlnaRenderer 新增:
    def get_transport_state(self) -> str:
        """Thread-safe transport state read."""
        return self.transport_state  # asyncio 单线程下安全
```

**结论**：Asyncio 单线程模型 + GIL 保证当前实现已安全。这个优化是可选的代码文档化改进。

---

## 优化 10：Seek FFmpeg 管道化 🟢 LOW

**瓶颈**：`_ffmpeg_seek` 将整个音频写入临时文件 → FFmpeg 读文件 → 输出到另一临时文件 → Python 再读回来。多一次磁盘 I/O。

**当前代码** (`server.py:189-237`)：完整的 `NamedTemporaryFile` 写入 + `subprocess` 调用。

**优化后**（stdin 管道，避免写磁盘）：

```python
    async def _ffmpeg_seek_v2(self, data: bytes, seconds: float, content_type: str) -> Optional[bytes]:
        """Seek using FFmpeg (piped stdin/stdout, no disk I/O)."""
        import shutil

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                ffmpeg_path,
                "-y",
                "-ss", str(seconds),
                "-i", "pipe:0",        # ← 从 stdin 读
                "-c", "copy",
                "-f", "mp4" if "mp4" in content_type else "mp3",
                "pipe:1",              # ← 输出到 stdout
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=data),  # ← 直接管道传入
                timeout=30.0,
            )

            if process.returncode != 0:
                log.warning(f"FFmpeg seek failed: {stderr.decode()[:200]}")
                return None

            return stdout

        except asyncio.TimeoutError:
            log.warning("FFmpeg seek timeout")
            try:
                process.kill()
            except Exception:
                pass
            return None
        except Exception as e:
            log.warning(f"FFmpeg seek error: {e}")
            return None
```

**收益**：无磁盘临时文件，纯内存管道。减少 I/O，也减少 SSD 写入寿命消耗。

---

## 优化 11：停止流程并行化 🟢 LOW

**瓶颈**：`_stop_airplay_server` 第 267 行串行调用 `airplay.stop()`。多个 AirPlay 服务的停止串行等待。

**当前代码** (`app.py:265-273`)：

```python
    async def _stop_airplay_server(self) -> None:
        """Stop AirPlay server components."""
        for did, airplay in self._airplay_services.items():
            try:
                await airplay.stop()  # ← 串行停止
            except Exception as e:
                log.warning(f"Failed to stop AirPlay for {did}: {e}")
```

**优化后**：

```python
    async def _stop_airplay_server(self) -> None:
        """Stop AirPlay server components (parallel)."""
        async def _stop_one(did: str, airplay) -> None:
            try:
                await asyncio.wait_for(airplay.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                log.warning(f"Timeout stopping AirPlay for {did}")
            except Exception as e:
                log.warning(f"Failed to stop AirPlay for {did}: {e}")

        if self._airplay_services:
            await asyncio.gather(
                *[_stop_one(did, ap) for did, ap in self._airplay_services.items()],
                return_exceptions=True,
            )

        self._airplay_services.clear()
        # ... zeroconf cleanup as before ...
```

**收益**：N 个 AirPlay 服务停止从 N × stop_time 降到 max(stop_time)。一般只有 1-2 个音箱，收益小。

---

## 优先级建议

| 优先级 | 优化编号 | 理由 |
|--------|---------|------|
| **第一批** | 1, 2, 3 | 并行轮询节省 50% 周期；内存减半；防泄漏。立竿见影。 |
| **第二批** | 4, 5, 6 | O(1) 查表、并行通知、消除重复 import。小改动大收益。 |
| **第三批** | 7, 8, 10, 11 | 锦上添花。缓存/管道化/并行停止。 |
| **可选** | 9 | 实际上已经线程安全，声明式优化。 |

## 实施注意事项

1. **优化 1** 改动最大，测试时重点关注：`_handle_state_transition` 是否仍在正确上下文执行、`notify_state_change` 是否正常广播
2. **优化 2** 需要确认 aiohttp 的 `StreamResponse.write(memoryview)` 兼容性（aiohttp 3.8+ 已支持，当前项目在 pyproject.toml 中有此依赖）
3. **优化 10** 需要测试 `ffmpeg -i pipe:0` 实际能否正确处理格式检测（部分编码/封装格式依赖文件 seek，管道可能失败——实际测试后如不稳定则回退到磁盘方式）
4. **优化 3** (Buffer GC) 建议 300 秒的参数可配，更保守的场景可能用 600 秒
