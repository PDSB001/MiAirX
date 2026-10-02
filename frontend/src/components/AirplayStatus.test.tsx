import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { HealthStatus } from "../api/types";
import { AirplayStatus } from "./AirplayStatus";

const health: HealthStatus = {
  status: "ok", miairx: { running: true }, xiaomi: { status: "normal" }, dlna: { running: true },
  airplay: { running: true, capabilities: { raop: true, fairplay_v3: true, hap_transient: true, ap2_realtime: "experimental", persistent_pairing: false, buffered_audio: false, ptp: false, ap2_discovery: false, ios_verified: false } },
  ffmpeg: { available: true, version: null }, network: { hostname: "192.168.1.5", dlna_port: 8200, web_port: 8300, airplay_port_start: 7000 },
  speakers: [{ did: "123", name: "客厅", model: "L05C", status: "online", current_source: "AirPlay", airplay: { running: true, state: "playing", protocol: "ap2_realtime", rtsp_port: 7000, audio_port: 7001, event_port: 7100, packets: { received: 20, decoded: 18, lost: 1, invalid: 1 } } }],
};

describe("AirplayStatus", () => {
  it("distinguishes clock measurements from speaker output latency", () => {
    const speaker = health.speakers[0]!;
    render(<AirplayStatus health={{ ...health, speakers: [{ ...speaker, airplay: { ...speaker.airplay!, timing: { measured: true, samples: 2, rtt_ms: 12 }, retransmit_requests: 3, discontinuities: 1 } }] }} />);
    expect(screen.getByText(/时钟测量：有效 · RTT 12 ms · 重传请求 3 · 节奏重建 1/)).toBeInTheDocument();
    expect(screen.getByText(/RTT 是网络往返时间，不是首播延迟/)).toBeInTheDocument();
  });
  it("shows experimental capabilities separately from the active session", async () => {
    render(<AirplayStatus health={health} />);
    expect(screen.getByText("AirPlay 2 实时音频 · 实验性")).toBeInTheDocument();
    expect(screen.getByText("接收中 · AirPlay 2 实时音频（实验性）")).toBeInTheDocument();
    expect(screen.getByText(/收到 20 · 解码 18 · 丢包 1 · 无效 1/)).toBeInTheDocument();
    expect(screen.getByText(/事件 TCP 7100/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("兼容性与网络说明"));
    expect(screen.getByText(/尚未经过真实 iPhone 验证/)).toBeVisible();
    expect(screen.getByText(/持久配对、缓冲播放、PTP 同步/)).toBeVisible();
  });
  it("does not invent capability support for older backends", () => {
    const { container } = render(<AirplayStatus health={{ ...health, airplay: { running: true } }} />);
    expect(container).toBeEmptyDOMElement();
  });
  it("shows idle without stale session counters or event ports", () => {
    render(<AirplayStatus health={{ ...health, speakers: [{ ...health.speakers[0]!, airplay: { ...health.speakers[0]!.airplay!, state: "idle", protocol: null, event_port: null } }] }} />);
    expect(screen.getByText("等待连接")).toBeInTheDocument();
    expect(screen.queryByText(/收到 20/)).not.toBeInTheDocument();
    expect(screen.queryByText(/事件 TCP 7100/)).not.toBeInTheDocument();
  });
  it("keeps missing runtime state distinct from stopped services", () => {
    render(<AirplayStatus health={{ ...health, speakers: [{ ...health.speakers[0]!, airplay: undefined }] }} />);
    expect(screen.getByText("状态不可用")).toBeInTheDocument();
  });
});
