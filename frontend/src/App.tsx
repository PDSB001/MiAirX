import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api/client";
import { configQuery, queryKeys } from "./api/queries";
import { AppShell } from "./components/AppShell";
import { useHashPage } from "./hooks/useHashPage";
import { ControlPage } from "./pages/ControlPage";
import { DevicesPage } from "./pages/DevicesPage";
import { LoginPage } from "./pages/LoginPage";
import { LogsPage } from "./pages/LogsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SetupWizard } from "./pages/SetupWizard";

export default function App() {
  const [page, setPage] = useHashPage();
  const auth = useQuery({ queryKey: queryKeys.auth, queryFn: api.authStatus, retry: false });
  const locked = auth.data?.auth_enabled && !auth.data.authenticated;
  const config = useQuery({ ...configQuery, enabled: auth.isSuccess && !locked });
  const [wizardRequested, setWizardRequested] = useState(false);
  const [wizardFinished, setWizardFinished] = useState(false);
  const [firstWizardActive, setFirstWizardActive] = useState(false);
  const [openQrRequested, setOpenQrRequested] = useState(false);

  useEffect(() => {
    const titles: Record<string, string> = { control: "播放控制", devices: "设备管理", settings: "系统设置", logs: "日志与诊断" };
    document.title = `${titles[page]} · MiAirX`;
  }, [page]);

  useEffect(() => {
    if (config.data?.setup_completed === false) setFirstWizardActive(true);
  }, [config.data?.setup_completed]);

  if (auth.isLoading) {
    return <div className="login-view"><div className="login-card"><p className="login-loading">正在检查登录状态…</p></div></div>;
  }

  if (locked) {
    return <LoginPage onSuccess={() => void auth.refetch()} />;
  }

  if (config.isLoading || !config.data) {
    return <div className="login-view"><div className="login-card"><p className="login-loading">正在读取安装状态…</p></div></div>;
  }

  const firstSetup = (config.data.setup_completed === false || firstWizardActive) && !wizardFinished;
  if (firstSetup || wizardRequested) {
    return <SetupWizard config={config.data} canClose={!firstSetup} onClose={() => setWizardRequested(false)} onComplete={() => { setWizardFinished(true); setFirstWizardActive(false); setWizardRequested(false); setPage("control"); void config.refetch(); }} />;
  }

  return (
    <AppShell page={page} setPage={setPage}>
      {page === "control" && <ControlPage onRelogin={() => { setOpenQrRequested(true); setPage("settings"); }} />}
      {page === "devices" && <DevicesPage />}
      {page === "settings" && <SettingsPage onRunSetup={() => setWizardRequested(true)} openQrRequested={openQrRequested} onQrOpened={() => setOpenQrRequested(false)} />}
      {page === "logs" && <LogsPage />}
    </AppShell>
  );
}
