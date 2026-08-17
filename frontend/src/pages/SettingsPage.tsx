import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, Fingerprint, KeyRound, Network, QrCode, RefreshCw, Rocket, Save, ShieldCheck, SlidersHorizontal, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { configQuery, queryKeys } from "../api/queries";
import type { AppConfig, ConfigUpdate } from "../api/types";
import { Modal } from "../components/Modal";
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

type QrStatus = "loading" | "waiting" | "scanned" | "confirmed" | "expired" | "failed";

function QrLoginModal({ onClose }: { onClose: () => void }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<QrStatus>("loading");
  const [qrcodeImage, setQrcodeImage] = useState("");
  const [loginUrl, setLoginUrl] = useState("");
  const [message, setMessage] = useState("正在获取二维码…");
  const [attempt, setAttempt] = useState(0);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // A single effect drives fetch-QR + serial long-poll. It depends only on
  // `attempt` (bumped to re-fetch the QR), NOT on `status`, so the poll loop
  // runs uninterrupted and the scan-state change is reflected instantly.
  useEffect(() => {
    let cancelled = false;
    let sessionId = "";

    const poll = async () => {
      while (!cancelled) {
        let result;
        try {
          result = await api.pollQrLogin(sessionId);
        } catch (error) {
          if (!cancelled) {
            setStatus("failed");
            setMessage((error as Error).message);
          }
          return;
        }
        if (cancelled) return;

        if (result.state === "confirmed") {
          setStatus("confirmed");
          setMessage("登录成功");
          showToast("小米账号登录成功", "success");
          void queryClient.invalidateQueries({ queryKey: queryKeys.config });
          void queryClient.invalidateQueries({ queryKey: queryKeys.speakers });
          window.setTimeout(() => onCloseRef.current(), 900);
          return;
        }
        if (result.state === "expired" || result.state === "failed") {
          setStatus(result.state as QrStatus);
          setMessage(result.message || "登录失败");
          return;
        }
        setStatus(result.state as QrStatus);
        setMessage(result.message || "等待扫码");
      }
    };

    const begin = async () => {
      setStatus("loading");
      setMessage("正在获取二维码…");
      try {
        const result = await api.startQrLogin();
        if (cancelled) return;
        if (!result.success || !result.session_id) throw new Error(result.error || "获取二维码失败");
        sessionId = result.session_id;
        setQrcodeImage(result.qrcode_image || "");
        setLoginUrl(result.login_url || "");
        setStatus("waiting");
        setMessage("请使用小米账号 App 扫码");
        void poll();
      } catch (error) {
        if (!cancelled) {
          setStatus("failed");
          setMessage((error as Error).message);
        }
      }
    };

    void begin();
    return () => { cancelled = true; };
  }, [attempt, queryClient, showToast]);

  const restart = () => {
    setQrcodeImage("");
    setLoginUrl("");
    setAttempt((value) => value + 1);
  };

  const showQr = status === "waiting" || status === "scanned";

  return (
    <Modal open transparent title="扫码登录小米账号" description="用小米账号 App 扫码，登录后凭据自动写入并立即生效。" onClose={onClose}>
      <div className="qr-body">
        <div className="qr-stage">
          {status === "loading" && <div className="qr-state"><RefreshCw className="spin" size={32} /><p>正在获取二维码…</p></div>}
          {showQr && qrcodeImage && <img className="qr-image" src={qrcodeImage} alt="登录二维码" />}
          {showQr && !qrcodeImage && loginUrl && <a className="button secondary" href={loginUrl} target="_blank" rel="noreferrer"><ExternalLink size={15} />打开登录链接</a>}
          {status === "confirmed" && <div className="qr-state"><CheckCircle2 className="qr-success" size={32} /><p>登录成功</p></div>}
          {(status === "expired" || status === "failed") && (
            <div className="qr-state">
              <AlertTriangle className="qr-error" size={32} />
              <p>{message}</p>
              <button type="button" className="button secondary" onClick={restart}>重新获取</button>
            </div>
          )}
        </div>
        <div className={`qr-status qr-status-${status}`} role="status">
          <span className="qr-status-dot" />
          <span>{message}</span>
        </div>
      </div>
    </Modal>
  );
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
  const [qrOpen, setQrOpen] = useState(false);
  const [loginMethod, setLoginMethod] = useState<"password" | "cookie" | "qr">("password");
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
        verbose: draft.verbose,
        auto_resume_on_interrupt: draft.auto_resume_on_interrupt, resume_delay_seconds: draft.resume_delay_seconds,
        default_volume: draft.default_volume, follow_device_volume: draft.follow_device_volume,
        auto_restart: draft.auto_restart,
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
        <form className="settings-form" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
          <div className="settings-col">
          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon"><UserRound size={20} /></div><div><h2>小米账号</h2><p>用于读取账号下的设备并调用音箱播放能力。</p></div></div>
            <div className="login-tabs" role="tablist" aria-label="登录方式">
              <button type="button" role="tab" aria-selected={loginMethod === "password"} className={loginMethod === "password" ? "active" : ""} onClick={() => setLoginMethod("password")}><KeyRound size={15} />密码登录</button>
              <button type="button" role="tab" aria-selected={loginMethod === "cookie"} className={loginMethod === "cookie" ? "active" : ""} onClick={() => setLoginMethod("cookie")}><Fingerprint size={15} />Cookie 登录{config.data?.cookie && <em className="login-saved-dot" aria-label="已保存凭据" />}</button>
              <button type="button" role="tab" aria-selected={loginMethod === "qr"} className={loginMethod === "qr" ? "active" : ""} onClick={() => setLoginMethod("qr")}><QrCode size={15} />扫码登录</button>
            </div>

            {loginMethod === "password" && (
              <div className="form-grid two-columns">
                <label className="field"><span>账号</span><input autoComplete="username" value={draft.account} onChange={(event) => update("account", event.target.value)} placeholder="手机号或邮箱" /></label>
                <label className="field"><span>密码</span><input type="password" autoComplete="new-password" value={draft.password} onChange={(event) => update("password", event.target.value)} placeholder={config.data?.password ? "已保存；留空保持不变" : "输入小米账号密码"} /></label>
              </div>
            )}

            {loginMethod === "cookie" && (
              <div className="form-grid two-columns">
                <label className="field"><span>userId</span><input value={draft.cookieUserId} onChange={(event) => update("cookieUserId", event.target.value)} placeholder="输入新的 userId" /></label>
                <label className="field"><span>passToken</span><input type="password" value={draft.cookiePassToken} onChange={(event) => update("cookiePassToken", event.target.value)} placeholder={config.data?.cookie ? "已保存；留空保持不变" : "输入 passToken"} /></label>
              </div>
            )}

            {loginMethod === "qr" && (
              <div className="qr-login-panel">
                <p>使用小米账号 App 扫码登录，无需输入账号密码。登录成功后凭据自动写入并立即生效。</p>
                <button type="button" className="button secondary" onClick={() => setQrOpen(true)}><QrCode size={15} />开始扫码登录</button>
                {config.data?.cookie && <small>当前已保存 Cookie 凭据，扫码登录后将覆盖。</small>}
              </div>
            )}
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
          </div>
          <div className="settings-col">
          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon blue"><ShieldCheck size={20} /></div><div><h2>后台安全</h2><p>给管理台设置访问密码，防止局域网内他人操作你的音箱。</p></div></div>
            <div className="form-grid">
              <label className="field"><span>后台密码</span><input type="password" autoComplete="new-password" value={draft.webPassword} onChange={(event) => update("webPassword", event.target.value)} placeholder={config.data?.web_password ? "已设置；留空保持不变" : "留空表示不启用登录保护"} /></label>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title"><div className="settings-icon violet"><SlidersHorizontal size={20} /></div><div><h2>播放偏好</h2><p>调整投放、恢复播放与音量的默认行为。</p></div></div>
            <div className="toggle-grid">
              <Toggle checked={draft.auto_resume_on_interrupt} onChange={(value) => update("auto_resume_on_interrupt", value)} label="中断后自动恢复" description="语音或其他播放打断后恢复原媒体。" />
              <Toggle checked={draft.follow_device_volume} onChange={(value) => update("follow_device_volume", value)} label="跟随设备音量" description="保留音箱当前音量，不主动覆盖。" />
            </div>
            <div className="form-grid two-columns compact-fields">
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
          </div>

          <VersionPanel />
          <div className={`save-bar ${hasChanges ? "has-changes" : "is-saved"}`}><div><strong>{hasChanges ? "有未保存的更改" : "配置已是最新"}</strong><span>{hasChanges ? "保存不会自动重启，也不会打断正在播放的内容。" : "修改任意设置后，可在这里统一保存。"}</span></div><button type="submit" className="button primary large" disabled={!hasChanges || save.isPending}><Save size={18} />{save.isPending ? "正在保存" : hasChanges ? "保存全部设置" : "已保存"}</button></div>
        </form>
      )}
      {qrOpen && <QrLoginModal onClose={() => setQrOpen(false)} />}
    </div>
  );
}
