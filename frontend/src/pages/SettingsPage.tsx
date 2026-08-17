import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ChevronDown, ExternalLink, FlaskConical, KeyRound, Network, RefreshCw, Rocket, Save, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { configQuery, queryKeys } from "../api/queries";
import type { AppConfig, ConfigUpdate } from "../api/types";
import { ErrorState, LoadingState, PageHeader, Toggle } from "../components/Ui";
import { useToast } from "../components/Toast";

interface Draft extends AppConfig {
  cookieUserId: string;
  cookiePassToken: string;
  webPassword: string;
}

function makeDraft(config: AppConfig): Draft {
  return { ...config, password: "", cookieUserId: "", cookiePassToken: "", webPassword: "" };
}

function VersionPanel() {
  const version = useQuery({ queryKey: ["version"], queryFn: () => api.version(), retry: false });
  const data = version.data;
  return (
    <details className="compatibility-panel version-panel">
      <summary>
        <span className="compatibility-symbol"><Rocket size={18} /></span>
        <span><strong>版本检测</strong><small>检查 GitHub 上的最新发布版本</small></span>
        {data?.update_available && <em className="update-badge">有新版本</em>}
        <ChevronDown className="details-chevron" size={18} />
      </summary>
      <div className="compatibility-content version-content">
        {version.isLoading && <p className="version-line muted">正在检查更新…</p>}
        {version.isError && <p className="version-line muted">检查失败：{(version.error as Error).message}</p>}
        {data && (
          <div className="version-line">
            <span>当前版本</span>
            <strong>v{data.current_version}</strong>
            {data.latest_version && (
              <>
                <span>最新版本</span>
                <strong>{data.latest_version}</strong>
              </>
            )}
          </div>
        )}
        {data?.update_available && data.url && (
          <a className="button secondary small" href={data.url} target="_blank" rel="noreferrer"><ExternalLink size={15} />查看更新</a>
        )}
        {data && !data.update_available && !data.error && (
          <p className="version-line muted">当前已是最新版本。</p>
        )}
        {data?.error && <p className="version-line muted">无法连接 GitHub，稍后可重试。</p>}
        <button className="button secondary small" onClick={() => void version.refetch()} disabled={version.isFetching}>重新检查</button>
      </div>
    </details>
  );
}

export function SettingsPage() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const config = useQuery(configQuery);
  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => { if (!draft && config.data) setDraft(makeDraft(config.data)); }, [config.data, draft]);

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("配置尚未加载");
      if (draft.dlna_port < 1 || draft.dlna_port > 65535 || draft.web_port < 1 || draft.web_port > 65535) throw new Error("端口必须在 1–65535 之间");
      const speakerCount = Math.max(1, draft.mi_did.split(",").filter((did) => did.trim()).length);
      const airplayPortEnd = draft.airplay_port_start + speakerCount * 2 - 1;
      if (draft.airplay_port_start < 1 || airplayPortEnd > 65535) throw new Error("AirPlay 端口段超出 1–65535");
      if ([draft.dlna_port, draft.web_port].some((port) => port >= draft.airplay_port_start && port <= airplayPortEnd)) throw new Error("AirPlay 端口段不能与 DLNA 或管理端口重叠");
      if (draft.resume_delay_seconds < 1 || draft.resume_delay_seconds > 15) throw new Error("恢复延迟必须在 1–15 秒之间");
      const payload: ConfigUpdate = {
        account: draft.account.trim(), hostname: draft.hostname.trim(), dlna_port: draft.dlna_port, web_port: draft.web_port, airplay_port_start: draft.airplay_port_start,
        verbose: draft.verbose, proxy_enabled: draft.proxy_enabled, auto_play_on_set_uri: draft.auto_play_on_set_uri,
        auto_resume_on_interrupt: draft.auto_resume_on_interrupt, resume_delay_seconds: draft.resume_delay_seconds,
        default_volume: draft.default_volume, follow_device_volume: draft.follow_device_volume,
        enable_voice_control: draft.enable_voice_control, auto_restart: draft.auto_restart,
        voice_poll_interval: draft.voice_poll_interval,
      };
      if (draft.password.trim()) payload.password = draft.password;
      if (draft.cookieUserId.trim() && draft.cookiePassToken.trim()) payload.cookie = `userId=${draft.cookieUserId.trim()}; passToken=${draft.cookiePassToken.trim()}`;
      if (draft.webPassword.trim()) payload.web_password = draft.webPassword;
      return api.saveConfig(payload);
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.config });
      setDraft((current) => current ? { ...current, password: "", cookieUserId: "", cookiePassToken: "", webPassword: "" } : current);
      if (result.restart_required) {
        showToast("配置已保存；管理端口变更需重启 MiAirX 后生效", "info");
      } else {
        showToast("配置已保存并自动生效", "success");
      }
    },
    onError: (error: Error) => showToast(error.message, "error"),
  });

  const update = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => current ? { ...current, [key]: value } : current);
  const hasChanges = Boolean(draft && config.data && (
    draft.password.trim() ||
    draft.cookieUserId.trim() ||
    draft.cookiePassToken.trim() ||
    draft.webPassword.trim() ||
    JSON.stringify(draft) !== JSON.stringify(makeDraft(config.data))
  ));
  const reload = async () => {
    const result = await config.refetch();
    if (result.data) { setDraft(makeDraft(result.data)); showToast("已恢复服务端配置"); }
  };

  return (
    <div className="page-view settings-page">
      <PageHeader eyebrow="System preferences" title="系统设置" description="配置小米账号、网络端口与播放行为。敏感凭据不会在页面中回显。" action={<button className="button secondary" onClick={() => void reload()} disabled={config.isFetching}><RefreshCw className={config.isFetching ? "spin" : ""} size={17} />重新载入</button>} />
      {config.isLoading && <LoadingState label="正在读取配置" />}
      {config.isError && <ErrorState message={(config.error as Error).message} retry={() => void config.refetch()} />}
      {draft && (
        <form onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon"><UserRound size={20} /></div><div><h2>小米账号</h2><p>用于读取账号下的设备并调用音箱播放能力。</p></div></div>
            <div className="form-grid two-columns">
              <label className="field"><span>账号</span><input autoComplete="username" value={draft.account} onChange={(event) => update("account", event.target.value)} placeholder="手机号或邮箱" /></label>
              <label className="field"><span>密码</span><input type="password" autoComplete="new-password" value={draft.password} onChange={(event) => update("password", event.target.value)} placeholder={config.data?.password ? "已保存；留空保持不变" : "输入小米账号密码"} /></label>
            </div>
            <div className="credential-panel">
              <div className="credential-title"><KeyRound size={18} /><span><strong>Cookie 登录</strong><small>密码登录受限时可使用 userId 与 passToken。</small></span>{config.data?.cookie && <em>已保存</em>}</div>
              <div className="form-grid two-columns">
                <label className="field"><span>userId</span><input value={draft.cookieUserId} onChange={(event) => update("cookieUserId", event.target.value)} placeholder="输入新的 userId" /></label>
                <label className="field"><span>passToken</span><input type="password" value={draft.cookiePassToken} onChange={(event) => update("cookiePassToken", event.target.value)} placeholder={config.data?.cookie ? "已保存；留空保持不变" : "输入 passToken"} /></label>
              </div>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon blue"><Network size={20} /></div><div><h2>网络服务</h2><p>决定 DLNA、管理台和 AirPlay 的监听地址与固定端口。</p></div></div>
            <div className="form-grid network-grid">
              <label className="field span-wide"><span>局域网地址</span><input value={draft.hostname} onChange={(event) => update("hostname", event.target.value)} placeholder="留空自动探测" /><small>留空则每次启动自动探测本机局域网 IP；也可手动填写其他设备可访问的宿主机 IPv4 地址。</small></label>
              <label className="field"><span>DLNA 端口</span><input type="number" min={1} max={65535} value={draft.dlna_port} onChange={(event) => update("dlna_port", Number(event.target.value))} /></label>
              <label className="field"><span>管理端口</span><input type="number" min={1} max={65535} value={draft.web_port} onChange={(event) => update("web_port", Number(event.target.value))} /></label>
              <label className="field"><span>AirPlay 起始端口</span><input type="number" min={1} max={65534} value={draft.airplay_port_start} onChange={(event) => update("airplay_port_start", Number(event.target.value))} /><small>每台音箱依次占用两个 TCP 端口。</small></label>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon blue"><ShieldCheck size={20} /></div><div><h2>后台安全</h2><p>给管理台设置访问密码，防止局域网内他人操作你的音箱。</p></div></div>
            <div className="form-grid two-columns">
              <label className="field"><span>后台密码</span><input type="password" autoComplete="new-password" value={draft.webPassword} onChange={(event) => update("webPassword", event.target.value)} placeholder={config.data?.web_password ? "已设置；留空保持不变" : "留空表示不启用登录保护"} /></label>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon violet"><SlidersHorizontal size={20} /></div><div><h2>播放偏好</h2><p>调整投放、恢复播放与音量的默认行为。</p></div></div>
            <div className="toggle-grid">
              <Toggle checked={draft.auto_resume_on_interrupt} onChange={(value) => update("auto_resume_on_interrupt", value)} label="中断后自动恢复" description="语音或其他播放打断后恢复原媒体。" />
              <Toggle checked={draft.follow_device_volume} onChange={(value) => update("follow_device_volume", value)} label="跟随设备音量" description="保留音箱当前音量，不主动覆盖。" />
            </div>
            <div className="form-grid three-columns compact-fields">
              <label className="field"><span>默认音量</span><div className="suffix-input"><input type="number" min={0} max={100} disabled={draft.follow_device_volume} value={draft.default_volume} onChange={(event) => update("default_volume", Number(event.target.value))} /><b>%</b></div></label>
              <label className="field"><span>恢复延迟</span><div className="suffix-input"><input type="number" min={1} max={15} value={draft.resume_delay_seconds} onChange={(event) => update("resume_delay_seconds", Number(event.target.value))} /><b>秒</b></div></label>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon green"><Activity size={20} /></div><div><h2>运行与诊断</h2><p>控制语音协同、服务自恢复和日志粒度。</p></div></div>
            <div className="toggle-grid">
              <Toggle checked={draft.auto_restart} onChange={(value) => update("auto_restart", value)} label="失败后请求重启" description="连续登录失败时退出，由 Docker 或 systemd 负责拉起。" />
              <Toggle checked={draft.verbose} onChange={(value) => update("verbose", value)} label="详细日志" description="输出更多诊断信息，排障完成后建议关闭。" />
            </div>
          </section>

          <details className="compatibility-panel">
            <summary><span className="compatibility-symbol"><FlaskConical size={18} /></span><span><strong>兼容性保留项</strong><small>用于旧配置兼容，当前主流程尚未接入</small></span><ChevronDown className="details-chevron" size={18} /></summary>
            <div className="compatibility-content">
              <p>这些字段可以保存，但当前版本不会改变媒体代理或语音控制行为。通常保持原值即可。</p>
              <div className="toggle-grid">
                <Toggle checked={draft.proxy_enabled} onChange={(value) => update("proxy_enabled", value)} label="媒体代理标志" description="当前 DLNA 路径会自动使用代理，此标志暂不控制它。" />
                <Toggle checked={draft.auto_play_on_set_uri} onChange={(value) => update("auto_play_on_set_uri", value)} label="Set URI 自动播放标志" description="保留字段，当前播放状态机尚未读取。" />
                <Toggle checked={draft.enable_voice_control} onChange={(value) => update("enable_voice_control", value)} label="语音控制标志" description="保留字段，当前没有独立语音控制器。" />
              </div>
              <div className="form-grid three-columns compact-fields">
                <label className="field"><span>语音轮询间隔</span><div className="suffix-input"><input type="number" min={1} max={60} value={draft.voice_poll_interval} onChange={(event) => update("voice_poll_interval", Number(event.target.value))} /><b>秒</b></div></label>
              </div>
            </div>
          </details>

          <VersionPanel />
          <div className={`save-bar ${hasChanges ? "has-changes" : "is-saved"}`}><div><strong>{hasChanges ? "有未保存的更改" : "配置已是最新"}</strong><span>{hasChanges ? "保存不会自动重启，也不会打断正在播放的内容。" : "修改任意设置后，可在这里统一保存。"}</span></div><button type="submit" className="button primary large" disabled={!hasChanges || save.isPending}><Save size={18} />{save.isPending ? "正在保存" : hasChanges ? "保存全部设置" : "已保存"}</button></div>
        </form>
      )}
    </div>
  );
}
