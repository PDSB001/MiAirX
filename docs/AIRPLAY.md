# AirPlay 开发说明

接收、legacy 配对、解码调度和音频输出根据协议行为独立实现，没有移植 MiAir/MiAir Next 的主接收服务。经用户明确批准，FairPlay 密钥解密引入 openairplay 的固定版本组件；不再宣称这部分是独立实现。音频解码通过 PyAV 的公开 API 完成，密码原语使用项目原有的 PyCryptodome。第三方来源与发布限制见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。

## 当前能力与限制

| 能力 | v1.7.0 |
|---|---|
| 经典 RAOP OPTIONS / ANNOUNCE / SETUP / RECORD | 已实现 |
| Apple-Challenge / RSA-OAEP 会话密钥 / AES-CBC | 已实现并有独立加密往返测试 |
| 无 PIN legacy `/pair-setup` / `/pair-verify` | 已实现 X25519、Ed25519、连续 AES-CTR；不是 HAP，也不是 FairPlay |
| 16 位 PCM、ALAC | 已实现；ALAC 使用真实编码器生成测试数据 |
| UDP RTP、RTCP 重传、timing 请求响应 | 已实现 |
| FLUSH、TEARDOWN、重复播放 | 已实现并有回归测试 |
| PCM → HTTP WAV → 小米音箱控制接口 | 已接通；实际音箱出声仍需设备验证 |
| FairPlay v3 `/fp-setup` / `fpaeskey` | 已接通两轮握手、第三方密钥解密及加密 PCM/ALAC 音频链路；支持 little-endian 主机 |
| HAP 临时配对（HKP=4）及加密控制 | 已实现 SRP-3072/SHA-512、HKDF 和 ChaCha20-Poly1305；独立客户端测试通过 |
| AP2 单音箱 realtime/type 96 | 实验性链路：binary plist、加密事件、32 字节 AEAD 密钥、16 位 PCM/ALAC → HTTP WAV |
| 持久 HAP/HKP=3、buffered/type 103、PTP、AAC、冗余 RTP、多房间 | 未实现，不广播完整 AP2 能力 |

Legacy 验证状态独立于每个 TCP 连接，30 秒后未完成的交换失效；错误签名返回 403，重复提交第二轮返回 455。接收端签名身份只在当前服务对象生命周期内有效，没有持久化配对库。无 PIN 模式只验证对方持有其自报公钥的私钥，不表示“可信用户认证”，不能替代后台密码或网络访问控制。当前不广播 legacy pairing feature bit，避免未经 Apple 实机验证就改变发送端选择的协议。HAP 临时配对现已接通，持久 HAP/HKP=3 仍返回 501。

Issue #1 的日志仅显示 POST 方法，没有请求路径。FairPlay v3 的关键缺口已接通，但尚无 iPhone 真机验证，不能认定该 Issue 已解决。要求持久 HAP、PTP、buffered AP2 或其他 FairPlay 版本的发送端仍可能失败。

## 端口

每台音箱仍保留两个固定端口号。例如第一台为 7000 / 7001：

- TCP 7000：RTSP；TCP 7001：音箱拉取 HTTP WAV。
- UDP 7000：RTP 音频；UDP 7001：RTCP 重传和 timing 报文，按报文类型分派。

两种协议都要在宿主机防火墙放行。下一台为 TCP/UDP 7002 / 7003。Docker 继续使用 host 网络。控制和 timing 共用 UDP 端口的协商行为已做本机测试，仍需实际 Apple 发送端验证。

## 无 Apple 设备的验证

```bash
python -m pytest tests/unit/test_airplay_receiver.py -v
```

测试独立构造 RTSP 和 RTP 请求，验证完整请求体、分包/粘包、有界长度、RSA 公钥反验、AES 非整块尾部、真实 ALAC 编解码、UDP 乱序/重传/序号回绕及 timing 响应。整链路测试使用真实回环 TCP/UDP 和 HTTP，将加密 ALAC/PCM 解码后的样本逐字节与输入音频比较，再检查停止与第二次播放。测试不会注册 mDNS 或访问小米云。

`python -m pytest tests/unit/test_airplay_pairing.py -v` 另外验证 legacy 双向签名、两轮 CTR 计数器连续性、重放/篡改拒绝、过期、跨连接隔离、真实 TCP 握手和 HTTP/RTSP 响应版本匹配。发送端测试独立构造请求，使用同一个底层密码库，不能视为另一个 Apple 实现的互操作认证。

另有独立 Node.js/OpenSSL 发送端测试，不调用 Python 接收端的密码函数，验证密钥交换、接收端签名、CTR 连续性和客户端签名。已在本机通过；没有 Node 的环境会跳过此项，Node 不是运行时依赖。它仍不能替代 Apple 真机测试。

这些检查证明本机经典链路的行为，不等同于具体 iOS 版本、真实网络和小爱音箱固件的端到端验证。

## 收集真机问题

开启详细日志后记录请求方法、路径和会话结束时的包计数。日志不输出 SDP、二进制请求正文或会话密钥。FairPlay 记录状态码和正文长度；未支持的握手另外记录 Content-Type，不记录正文。持久 HAP/HKP=3 `/pair-*` 返回 501 不是开放更多端口就能解决。

`python -m pytest tests/unit/test_airplay_fairplay.py tests/unit/test_airplay_receiver.py -v` 验证四种握手 mode、报文长度/版本/顺序、过期、跨连接隔离、已知解密向量，以及 RSA/FairPlay 两种加密下的 PCM/ALAC → UDP → HTTP 逐样本验证和重复播放。向量来自固定提交 `ae067228d76df011375164814b729932ed55ca2f` 的 [独立 C/Go 对照测试](https://github.com/omarroth/doubletake/blob/ae067228d76df011375164814b729932ed55ca2f/internal/airplay/fairplay_key_test.go)，没有移植其接收服务。

移除上游密码调试输出和全局 stdout 重定向，保留算术与表数据。接入层在进入组件前检查固定长度、FPLY 头、mode 和状态。该上游解密器不校验封装密钥的 MAC；不能宣称任意正文篡改都会在握手阶段被检测。其固定响应/参考 SAP 方案也不等同于完整 AirPlay 2 SAP。

## 与参考项目主链路的源码差异

核对的是固定提交中的实际调用，不依据 README 的功能宣称：

- [MiAir server.py，4416ffd](https://github.com/KiriChen-Wind/MiAir/blob/4416ffd679340581ea64eddaeff6672d20fad85a/miair/airplay/server.py)
- [MiAir Next server.py，163afd0](https://github.com/deerwan/miair-next/blob/163afd07f3175c6686b9c0cb0322f4e300c7699e/backend/app/engine/airplay/server.py)

| 对照项 | 上述两份主服务 | MiAirX 当前实现 |
|---|---|---|
| FairPlay | `/fp-setup` 保存 164 字节 keymsg；ANNOUNCE 将 `fpaeskey`、IV、keymsg 传入 `FairPlayAES` 解密 | 同类 v3 链路已接通；组件固定版本、去除密钥输出，状态严格按连接隔离 |
| POST 配对 | 主服务显式分支是 `/fp-setup`，其他 POST 默认 200；不能由配对模块存在就认定 HAP 已接通 | 接通 legacy 验证与 transient HAP；持久配对返回 501 |
| 协议组织 | 大量接收、解码、定时和缓冲逻辑集中在 server.py | 分帧、密码、legacy 配对、解码、UDP 接收分为小模块 |
| 会话状态 | `_fp_keymsg` 等密码状态放在服务对象；需另查并发会话约束才能判断隔离效果 | 每连接握手状态；播放独占锁；密钥/解码器/UDP 接收器按会话隔离 |
| UDP 与定时 | 独立 audio/control/timing socket；有 `PlaybackPacer` 和主动 timing 交换 | 两个固定 UDP 端口；timing/control 共用；主动 NTP 测量、RTP 接收端 pacing 与有界速率校正，不承诺精确输出同步 |
| 重传和乱序 | 有 `JitterBuffer` 等实现 | 有界 512 包窗口、序号回绕、重传请求及有限丢包补静音；策略不是等价移植 |
| 解码 | PyAV CodecContext / AudioResampler | 同样使用公开 PyAV API；明确支持 16 位 PCM、ALAC，不宣称 AAC |

FairPlay v3 会话密钥解密与接收端 timing/pacing 缺口现已补上。剩余差异包括精确输出同步、持久配对、AP2 buffered/PTP 和真实 Apple 发送端的协商行为。上述差异是代码结构与活跃调用点的对照，不代表已经证明谁的实机稳定性更好。

引入的 [openairplay fairplay3.py](https://github.com/openairplay/airplay2-receiver/blob/6c343d3679ddb561c61566985acaaf587d0a3bd3/ap2/fairplay3.py) 约 655 KB，包含固定变换数据。保留上游署名并附带 GPLv2 全文；原创部分的 MIT LICENSE 未改，包含它的完整构建按上游声明的 GPLv2 条款分发。源流许可及响应常量权利疑点仍未解决，本次发布不代表许可审查已完成，见 [分发说明](../DISTRIBUTION_LICENSE.md)。

Legacy 协议行为另与 [pyatv 发送端](https://github.com/postlund/pyatv/blob/master/pyatv/protocols/airplay/srp.py) 和 [UxPlay 配对流程](https://github.com/FDH2/UxPlay/blob/master/lib/pairing.c) 核对；只使用协议规则，不移植其实现。

## 阅读参考

- [MiAir 接收服务](https://github.com/KiriChen-Wind/MiAir/tree/main/miair/airplay)
- [MiAir Next 接收服务及测试](https://github.com/deerwan/miair-next/tree/main/backend)
- [Shairport Sync](https://github.com/mikebrady/shairport-sync)
- [AirConnect](https://github.com/philippe44/AirConnect)

本次只引入 FairPlay 解密组件和固定响应记录，不引入竞品主接收器或外置播放服务；发布仍保留尚未解决的许可来源疑点，不宣称 MIT-only 或已获得额外再分发授权。

## HAP 与 AP2 实验链路

HAP 只实现 `X-Apple-HKP: 4` + transient flag 0x10 的 M1–M4，协议 PIN 是 3939，不建立持久信任库，也不是后台管理员登录。M3 证明验证失败时不启用加密；M4 明文发送后，立即切换为最多 1024 字节一帧的加密连接。支持 M3 后粘包的加密请求；标签/长度/计数器错误立即断线。每连接最多 3 次初始化、每来源 IP 每分钟最多 5 次，限速状态有界，不输出密码证明或密钥。

AP2 binary-plist SETUP 必须在同一连接完成临时配对和加密切换；明文请求返回 403。支持 NTP/None 协商：NTP 模式指定 timingPort 后进行主动探测，None 模式不主动探测；尚无 PTP 或精确音箱输出同步。仅接受一个 realtime/type 96 流、32 字节 ChaCha20-Poly1305 密钥及 16 位 PCM/ALAC。先验证音频标签，再接受序号和进入乱序缓冲；未完成配置时 RECORD 返回 455。其余模式明确拒绝，不伪造成功。

## 接收稳定性与时钟边界

经典 SETUP 的 timing_port 与 AP2 NTP 的 timingPort 用于每秒最多一次的主动 timing 探测；仅接受匹配来源端口、未消费的 origin、有效往返时间的回复。测量采用单调时间，不受本机墙钟调整影响；估计超过 10 秒未更新即过期。同步报文提供延迟信息与有界时钟速率估计，不直接套用其绝对播放时刻。

RTP 按采样率与时间戳控制向 HTTP 输出 PCM 的节奏，等待时继续收取音频和控制报文。小幅速率修正使用连续增量锚点；大幅跳变或停顿则重新锚定，避免长期等待和追赶突发。缺包在 100 ms 窗口内最多请求三次重传，丢包补静音仍有界；超过接收窗口且至少 250 ms 未收到有效新音频后，恢复到新的前向序号。FLUSH 清空接收缓冲并按新的序号/时间戳拒绝旧包。

这些是单音箱接收端的尽力节奏控制，不是 DAC 输出同步。小米音箱通过 HTTP 获取 WAV，其缓存、首播和输出时刻不能被当前链路可靠测量；因此不能据此承诺精确时延、多房间同步或消除所有首播延迟。一小时测试为加速虚拟时间模型，真实回环测试另覆盖连续切歌和正常/异常断线重连，仍需真实 Apple 设备和音箱验证。

当前不新增 `_airplay._tcp` 广播或完整 AP2 feature bits。独立客户端可直接测试接口，但不承诺 iPhone 自动选择 AP2；普通发现仍使用经典 RAOP/FairPlay。SRP/控制传输采用独立实现，pyatv/openairplay 只用于核对协议，不引入其主接收器、PyAudio 或播放器。

AP2 事件通道还需要 TCP `RTSP 端口 + 100`，例如 7000 → 7100、7002 → 7102；默认 50 台可放行 TCP 7100–7199。自定义起点 17000 时对应 17100。不要让事件端口与其他服务或音箱端口重叠；冲突返回 503，不偷偷换端口。只有 RTSP 配置为自动端口 0 的测试场景使用自动事件端口。经典 RAOP 不需要这些额外端口。

测试前安装开发依赖 `pip install -e ".[dev]"`，运行 `python -m pytest tests/unit/test_airplay_hap.py tests/unit/test_airplay_ap2.py -v`。SRP 客户端使用 BSD 许可的 srptools（仅开发依赖）；控制帧另与 Node/OpenSSL 对照（无 Node 时此独立对照项跳过）。真实回环 TCP/UDP/HTTP 测试涵盖 M4 明文→加密切换/粘包、错误标签断线、限速、加密事件、plist 协商、PCM/ALAC 音频逐样本比较、失败模式和重连。未安装 srptools 会跳过 SRP/相关网络测试，不表示协议验证成功。
