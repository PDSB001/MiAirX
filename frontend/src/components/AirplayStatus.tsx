import type { HealthStatus } from "../api/types";

export function AirplayStatus({ health }: { health: HealthStatus }) {
  const capabilities = health.airplay.capabilities;
  if (!capabilities) return null;
  return (
    <section className="airplay-panel" aria-label="AirPlay 接收状态">
      <div className="airplay-panel-heading"><h2>AirPlay 接收</h2><span className="source-state">{health.airplay.running ? "服务运行中" : "服务未就绪"}</span></div>
      <div className="airplay-capabilities">
        {capabilities.raop && <span>经典 RAOP</span>}
        {capabilities.fairplay_v3 && <span>FairPlay v3</span>}
        {capabilities.hap_transient && <span>HAP 临时配对</span>}
        {capabilities.ap2_realtime === "experimental" && <span className="experimental">AirPlay 2 实时音频 · 实验性</span>}
      </div>
      <p className="airplay-description">能力标签表示服务端已实现的路径，不代表当前连接或设备兼容性。当前仍以经典 RAOP 广播供发现。</p>
      <details className="airplay-details"><summary>兼容性与网络说明</summary>
        <p>{!capabilities.ios_verified && "尚未经过真实 iPhone 验证。"}{!capabilities.ap2_discovery && "未启用完整 AirPlay 2 广播。"}不支持的功能：{[!capabilities.persistent_pairing && "持久配对", !capabilities.buffered_audio && "缓冲播放", !capabilities.ptp && "PTP 同步"].filter(Boolean).join("、") || "无"}。</p>
        <p>RTSP / RTP 与 HTTP / RTCP 的两个端口均需放行 TCP + UDP；实验性实时会话额外使用 RTSP + 100 的 TCP 事件端口（按需监听）。Docker host 网络不会自动绕过宿主机防火墙。发现需要 UDP 5353；DLNA 还需 UDP 1900。</p>
      </details>
      <div className="airplay-receivers">
        {health.speakers.map((speaker) => {
          const runtime = speaker.airplay;
          return <article key={speaker.did} className="airplay-receiver">
            <div><strong>{speaker.name}</strong><span>{!runtime ? "状态不可用" : !runtime.running ? "未运行" : runtime.state === "playing" ? "接收中" : runtime.state === "connected" ? "会话已连接" : "等待连接"}{runtime?.protocol && ` · ${runtime.protocol === "ap2_realtime" ? "AirPlay 2 实时音频（实验性）" : "经典 RAOP"}`}</span></div>
            {runtime && <>
              <p>RTSP / RTP {runtime.rtsp_port} · HTTP / RTCP {runtime.audio_port}{runtime.event_port !== null && ` · 事件 TCP ${runtime.event_port}`}</p>
              {runtime.protocol && <p>收到 {runtime.packets.received} · 解码 {runtime.packets.decoded} · 丢包 {runtime.packets.lost} · 无效 {runtime.packets.invalid}<small>计数仅属于当前会话，断开后清零；收到数据不等于音箱已出声。</small></p>}
              {runtime.protocol && runtime.timing && <p>时钟测量：{runtime.timing.measured ? `有效 · RTT ${runtime.timing.rtt_ms ?? "—"} ms` : "等待有效样本 / 已过期"} · 重传请求 {runtime.retransmit_requests ?? 0} · 节奏重建 {runtime.discontinuities ?? 0}<small>RTT 是网络往返时间，不是首播延迟；接收端节奏控制不等于音箱输出同步。</small></p>}
            </>}
          </article>;
        })}
        {health.speakers.length === 0 && <p className="airplay-description">选择音箱后，将在这里显示接收状态和监听端口。</p>}
      </div>
    </section>
  );
}
