import { useEffect } from "react";
import { AppShell } from "./components/AppShell";
import { useHashPage } from "./hooks/useHashPage";
import { ControlPage } from "./pages/ControlPage";
import { DevicesPage } from "./pages/DevicesPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  const [page, setPage] = useHashPage();
  useEffect(() => {
    const titles = { control: "播放控制", devices: "设备管理", settings: "系统设置" };
    document.title = `${titles[page]} · MiAirX`;
  }, [page]);
  return (
    <AppShell page={page} setPage={setPage}>
      {page === "control" && <ControlPage />}
      {page === "devices" && <DevicesPage />}
      {page === "settings" && <SettingsPage />}
    </AppShell>
  );
}
