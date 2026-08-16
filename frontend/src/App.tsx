import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "./api/client";
import { AppShell } from "./components/AppShell";
import { useHashPage } from "./hooks/useHashPage";
import { ControlPage } from "./pages/ControlPage";
import { DevicesPage } from "./pages/DevicesPage";
import { LoginPage } from "./pages/LoginPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  const [page, setPage] = useHashPage();
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authStatus, retry: false });
  const locked = auth.data?.auth_enabled && !auth.data.authenticated;

  useEffect(() => {
    const titles = { control: "播放控制", devices: "设备管理", settings: "系统设置" };
    document.title = `${titles[page]} · MiAirX`;
  }, [page]);

  if (auth.isLoading) {
    return <div className="login-view"><div className="login-card"><p className="login-loading">正在检查登录状态…</p></div></div>;
  }

  if (locked) {
    return <LoginPage onSuccess={() => void auth.refetch()} />;
  }

  return (
    <AppShell page={page} setPage={setPage}>
      {page === "control" && <ControlPage />}
      {page === "devices" && <DevicesPage />}
      {page === "settings" && <SettingsPage />}
    </AppShell>
  );
}
