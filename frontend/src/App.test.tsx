import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { ToastProvider } from "./components/Toast";

const config = {
  account: "user@example.com", password: "***", mi_did: "123", cookie: "***", hostname: "192.168.1.5",
  dlna_port: 8200, web_port: 8300, airplay_port_start: 7000, verbose: false, proxy_enabled: true, auto_play_on_set_uri: false,
  auto_resume_on_interrupt: true, resume_delay_seconds: 5, default_volume: 30, follow_device_volume: true,
  enable_voice_control: false, auto_restart: false, voice_poll_interval: 1,
};

function json(value: unknown) { return Promise.resolve(new Response(JSON.stringify(value), { status: 200 })); }

describe("App", () => {
  beforeEach(() => {
    window.location.hash = "#control";
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = String(input);
      if (path.endsWith("/api/status")) return json({ version: "1.0.4", hostname: "192.168.1.5", dlna_port: 8200, web_port: 8300, airplay_port_start: 7000, speakers_count: 1, is_running: true, account: "use***", mi_did: "123" });
      if (path.endsWith("/api/config")) return json(config);
      if (path.endsWith("/api/speakers")) return json([{ did: "123", name: "客厅音箱", hardware: "L05C", enabled: true, udn: "uuid:test", device_id: "" }]);
      if (path.endsWith("/api/positions")) return json({ positions: { "123": { position: 12, duration: 180, state: "PLAYING" } } });
      if (path.endsWith("/api/devices")) return json([{ miotDID: "123", name: "客厅音箱", hardware: "L05C" }]);
      return json({ success: true });
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders live speaker data and navigates between pages", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ToastProvider><App /></ToastProvider></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "客厅音箱" })).toBeInTheDocument();
    expect(screen.getByText("正在播放")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /设备管理/ }));
    expect(await screen.findByRole("heading", { name: "设备管理" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /客厅音箱/ })).toBeInTheDocument();
  });
});
