import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AppConfig } from "../api/types";
import { ToastProvider } from "../components/Toast";
import { SetupWizard } from "./SetupWizard";

const config: AppConfig = {
  account: "", password: "", mi_did: "", cookie: "", hostname: "",
  dlna_port: 8200, web_port: 8300, airplay_port_start: 7000, verbose: false,
  auto_resume_on_interrupt: false, resume_delay_seconds: 5, default_volume: 30,
  follow_device_volume: true, auto_restart: false, web_password: "", setup_completed: false,
};

function json(value: unknown) { return Promise.resolve(new Response(JSON.stringify(value), { status: 200 })); }

it("completes the new-install wizard using QR login and discovered speakers", async () => {
  const completed = vi.fn();
  const savedPayloads: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const path = String(input);
    if (path === "/api/auth/qrcode") return json({ success: true, session_id: "qr-1", qrcode_image: "data:image/png;base64,AA==" });
    if (path.startsWith("/api/auth/qrcode/poll")) return json({ success: true, state: "confirmed" });
    if (path === "/api/devices/discover") return json([{ miotDID: "123", name: "客厅音箱", hardware: "L05C" }]);
    if (path === "/api/health") return json({ status: "ok", miairx: { running: true }, xiaomi: { status: "normal" }, dlna: { running: true }, airplay: { running: true }, ffmpeg: { available: true, version: "test" }, network: { hostname: "192.168.1.5", dlna_port: 8200, web_port: 8300, airplay_port_start: 7000 }, speakers: [{ did: "123", name: "客厅音箱", model: "L05C", status: "online", current_source: null }] });
    if (path === "/api/config" && init?.method === "POST") {
      const payload = JSON.parse(String(init.body)) as Record<string, unknown>;
      savedPayloads.push(payload);
      return json({ success: true, reauth_required: Boolean(payload.web_password) });
    }
    if (path === "/api/config") return json(config);
    if (path === "/api/auth/login") return json({ success: true });
    return json({ success: true });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const user = userEvent.setup();
  render(<QueryClientProvider client={client}><ToastProvider><SetupWizard config={config} canClose={false} onClose={() => undefined} onComplete={completed} /></ToastProvider></QueryClientProvider>);

  await user.click(screen.getByRole("button", { name: /继续/ }));
  await user.type(screen.getByLabelText("管理密码"), "admin123");
  await user.type(screen.getByLabelText("确认密码"), "admin123");
  await user.click(screen.getByRole("button", { name: /继续/ }));
  expect(await screen.findByText("小米账号已就绪")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /继续/ }));
  expect(await screen.findByRole("button", { name: /客厅音箱/ })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /继续/ }));
  expect(await screen.findByRole("heading", { name: "网络与服务" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /继续/ }));
  expect(await screen.findByRole("heading", { name: "配置检查" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /完成设置/ }));
  expect(await screen.findByRole("heading", { name: "设置完成" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "进入 Dashboard" }));

  expect(completed).toHaveBeenCalledOnce();
  await waitFor(() => expect(savedPayloads).toContainEqual({ setup_completed: true }));
});
