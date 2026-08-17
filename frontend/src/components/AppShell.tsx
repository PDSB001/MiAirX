import { Gauge, Menu, RadioTower, ScrollText, Settings2, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import type { PageId } from "../api/types";
import { statusQuery } from "../api/queries";

const nav: Array<{ id: PageId; label: string; caption: string; icon: typeof Gauge }> = [
  { id: "control", label: "播放控制", caption: "音箱与投放", icon: Gauge },
  { id: "devices", label: "设备管理", caption: "小米云设备", icon: RadioTower },
  { id: "settings", label: "系统设置", caption: "连接与偏好", icon: Settings2 },
  { id: "logs", label: "日志诊断", caption: "实时日志与诊断包", icon: ScrollText },
];

export function AppShell({ page, setPage, children }: { page: PageId; setPage: (page: PageId) => void; children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const status = useQuery(statusQuery);
  const navigate = (id: PageId) => { setPage(id); setMobileOpen(false); };

  return (
    <div className="app-shell">
      <button className="mobile-menu" aria-label="打开导航" onClick={() => setMobileOpen(true)}><Menu size={22} /></button>
      {mobileOpen && <button className="sidebar-scrim" aria-label="关闭导航" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar ${mobileOpen ? "is-open" : ""}`}>
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">
            <i className="brand-arc arc-one" />
            <i className="brand-arc arc-two" />
            <i className="brand-core" />
          </div>
          <div><strong>MiAirX</strong><span>Sound, connected.</span></div>
          <button className="sidebar-close" aria-label="关闭导航" onClick={() => setMobileOpen(false)}><X size={20} /></button>
        </div>
        <nav aria-label="主导航">
          <span className="nav-label">Workspace</span>
          {nav.map(({ id, label, caption, icon: Icon }) => (
            <button className={page === id ? "active" : ""} aria-current={page === id ? "page" : undefined} onClick={() => navigate(id)} key={id}>
              <Icon size={19} />
              <span><strong>{label}</strong><small>{caption}</small></span>
            </button>
          ))}
        </nav>
        <div className="sidebar-status">
          <div className={`status-dot ${status.data?.is_running ? "online" : ""}`} />
          <div>
            <strong>{status.data?.is_running ? "服务运行中" : status.isError ? "连接中断" : "正在连接"}</strong>
            <span>{status.data ? `v${status.data.version} · ${status.data.hostname}` : "MiAirX service"}</span>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <div className="ambient-field" aria-hidden="true"><i /><i /><i /></div>
        {children}
      </main>
    </div>
  );
}
