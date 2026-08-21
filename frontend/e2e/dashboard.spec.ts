import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const config = {
    account: "demo@example.com", password: "***", mi_did: "123", cookie: "***", hostname: "192.168.1.5",
    dlna_port: 8200, web_port: 8300, airplay_port_start: 7000, verbose: false, proxy_enabled: true, auto_play_on_set_uri: false,
    auto_resume_on_interrupt: true, resume_delay_seconds: 5, default_volume: 30, follow_device_volume: true,
    enable_voice_control: false, auto_restart: false, voice_poll_interval: 1, web_password: "", setup_completed: true,
  };
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    const payload = url.pathname.endsWith("/auth/status")
      ? { auth_enabled: false, authenticated: false }
      : url.pathname.endsWith("/status")
      ? { version: "1.0.4", hostname: "192.168.1.5", dlna_port: 8200, web_port: 8300, airplay_port_start: 7000, speakers_count: 1, is_running: true, account: "dem***", mi_did: "123" }
      : url.pathname.endsWith("/health") ? { status: "ok", miairx: { running: true }, xiaomi: { status: "normal" }, dlna: { running: true }, airplay: { running: true }, ffmpeg: { available: true, version: "test" }, network: { hostname: "192.168.1.5", dlna_port: 8200, web_port: 8300, airplay_port_start: 7000 }, speakers: [{ did: "123", name: "客厅音箱", model: "L05C", status: "online", current_source: "DLNA" }] }
      : url.pathname.endsWith("/config") ? config
      : url.pathname.endsWith("/speakers") ? [{ did: "123", name: "客厅音箱", hardware: "L05C", enabled: true, udn: "uuid:test", device_id: "", status: "online" }]
      : url.pathname.endsWith("/positions") ? { positions: { "123": { position: 24, duration: 180, state: "PLAYING" } } }
      : url.pathname.endsWith("/devices") ? [{ miotDID: "123", name: "客厅音箱", hardware: "L05C" }]
      : { success: true };
    await route.fulfill({ json: payload });
  });
});

test("dashboard navigation smoke test", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "播放控制" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "客厅音箱" })).toBeVisible();
  await page.getByRole("button", { name: /系统设置/ }).click();
  await expect(page.getByRole("heading", { name: "系统设置" })).toBeVisible();
  await expect(page.getByLabel("AirPlay 起始端口")).toHaveValue("7000");
  await expect(page.getByRole("button", { name: /已保存|保存全部设置/ })).toBeVisible();
});

test("mobile navigation smoke test", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "播放控制" })).toBeVisible();
  await page.getByRole("button", { name: "打开导航" }).click();
  await page.getByRole("button", { name: /设备管理/ }).click();
  await expect(page.getByRole("heading", { name: "设备管理" })).toBeVisible();
  await expect(page.getByRole("button", { name: /客厅音箱/ })).toBeVisible();
});
