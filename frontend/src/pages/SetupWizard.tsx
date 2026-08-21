import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, ChevronLeft, ChevronRight, LoaderCircle, Network, QrCode, ShieldCheck, Speaker, Sparkles, Stethoscope } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { configQuery, healthQuery, queryKeys } from "../api/queries";
import type { AppConfig, XiaomiDevice } from "../api/types";
import { XiaomiQrLogin } from "../components/XiaomiQrLogin";

const steps = ["欢迎", "管理密码", "小米账号", "选择音箱", "网络服务", "检查", "完成"];

function deviceDid(device: XiaomiDevice) { return device.miotDID || device.did || ""; }

export function SetupWizard({ config, canClose, onComplete, onClose }: { config: AppConfig; canClose: boolean; onComplete: () => void; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [xiaomiReady, setXiaomiReady] = useState(Boolean(config.cookie || config.account));
  const [devices, setDevices] = useState<XiaomiDevice[]>([]);
  const [selected, setSelected] = useState(() => new Set(config.mi_did.split(",").map((did) => did.trim()).filter(Boolean)));
  const [network, setNetwork] = useState({ hostname: config.hostname, dlna_port: config.dlna_port, web_port: config.web_port, airplay_port_start: config.airplay_port_start });
  const discoveryRun = useRef(false);
  const health = useQuery({ ...healthQuery, enabled: step >= 5 });

  useEffect(() => {
    if (step !== 3 || discoveryRun.current) return;
    discoveryRun.current = true;
    setBusy(true);
    setError("");
    api.discoverSpeakers()
      .then((found) => {
        setDevices(found);
        if (selected.size === 0) setSelected(new Set(found.map(deviceDid).filter(Boolean)));
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setBusy(false));
  }, [selected.size, step]);

  const selectedDevices = useMemo(() => devices.filter((device) => selected.has(deviceDid(device))), [devices, selected]);

  const saveAndContinue = async () => {
    setError("");
    setBusy(true);
    try {
      if (step === 1) {
        if (!config.web_password && password.length < 6) throw new Error("管理密码至少需要 6 个字符");
        if (password && password !== confirmPassword) throw new Error("两次输入的管理密码不一致");
        if (password) {
          const result = await api.saveConfig({ web_password: password });
          if (result.reauth_required) {
            await api.login(password);
            queryClient.setQueryData(queryKeys.auth, { auth_enabled: true, authenticated: true });
          }
        }
      } else if (step === 2 && !xiaomiReady) {
        throw new Error("请先完成小米账号扫码登录");
      } else if (step === 3) {
        if (selected.size === 0) throw new Error("请至少选择一台音箱");
        await api.saveConfig({ mi_did: [...selected].join(",") });
      } else if (step === 4) {
        await api.saveConfig(network);
      } else if (step === 5) {
        await api.saveConfig({ setup_completed: true });
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: queryKeys.config }),
          queryClient.invalidateQueries({ queryKey: queryKeys.health }),
          queryClient.invalidateQueries({ queryKey: queryKeys.speakers }),
        ]);
      }
      setStep((value) => Math.min(6, value + 1));
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggleDevice = (did: string) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(did)) next.delete(did); else next.add(did);
    return next;
  });

  return (
    <main className="wizard-view">
      <section className="wizard-card">
        <header className="wizard-header">
          <div><span className="eyebrow">MiAirX 1.6.2</span><h1>首次使用向导</h1></div>
          {canClose && <button type="button" className="button ghost small" onClick={onClose}>退出向导</button>}
        </header>
        <ol className="wizard-progress" aria-label="设置进度">
          {steps.map((label, index) => <li key={label} className={index === step ? "active" : index < step ? "done" : ""}><i>{index < step ? <Check size={12} /> : index + 1}</i><span>{label}</span></li>)}
        </ol>

        <div className="wizard-content">
          {step === 0 && <div className="wizard-intro"><div className="wizard-hero-icon"><Sparkles size={34} /></div><h2>几分钟内完成 MiAirX 设置</h2><p>向导会复用现有的扫码登录、设备发现与热重载能力。DLNA 和 AirPlay 默认开启，网络地址默认自动探测。</p></div>}
          {step === 1 && <div className="wizard-step"><div className="wizard-step-title"><ShieldCheck size={24} /><div><h2>保护管理后台</h2><p>{config.web_password ? "已设置管理密码；留空可保持不变。" : "设置访问管理台时使用的密码。"}</p></div></div><div className="form-grid two-columns"><label className="field"><span>管理密码</span><input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder={config.web_password ? "留空保持当前密码" : "至少 6 个字符"} /></label><label className="field"><span>确认密码</span><input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} placeholder="再次输入密码" /></label></div></div>}
          {step === 2 && <div className="wizard-step"><div className="wizard-step-title"><QrCode size={24} /><div><h2>登录小米账号</h2><p>优先使用扫码登录，凭据将安全保存并立即热重载。</p></div></div>{xiaomiReady ? <div className="wizard-success"><CheckCircle2 size={24} /><div><strong>小米账号已就绪</strong><span>可以继续发现账号下的音箱。</span></div><button type="button" className="button secondary small" onClick={() => setXiaomiReady(false)}>重新扫码</button></div> : <XiaomiQrLogin onConfirmed={() => setXiaomiReady(true)} />}</div>}
          {step === 3 && <div className="wizard-step"><div className="wizard-step-title"><Speaker size={24} /><div><h2>自动发现并选择音箱</h2><p>无需手填 DID；已配置但暂时离线的音箱不会被删除。</p></div></div>{busy ? <div className="wizard-loading"><LoaderCircle className="spin" />正在发现小米音箱…</div> : <div className="wizard-device-list">{devices.map((device) => { const did = deviceDid(device); const active = selected.has(did); return <button type="button" key={did} className={active ? "selected" : ""} onClick={() => toggleDevice(did)}><Speaker size={20} /><span><strong>{device.name || "未命名音箱"}</strong><small>{device.hardware || device.model || "未知型号"}</small></span><i>{active && <Check size={14} />}</i></button>; })}{devices.length === 0 && !error && <p className="wizard-empty">没有发现音箱，请确认小米账号状态后重试。</p>}</div>}</div>}
          {step === 4 && <div className="wizard-step"><div className="wizard-step-title"><Network size={24} /><div><h2>网络与服务</h2><p>推荐保留自动设置；只有特殊网络或端口冲突时才需修改。</p></div></div><div className="wizard-service-defaults"><span><CheckCircle2 size={17} />DLNA 默认开启</span><span><CheckCircle2 size={17} />AirPlay 默认开启</span><span><CheckCircle2 size={17} />局域网地址自动探测</span></div><details className="wizard-advanced"><summary>高级网络设置</summary><div className="form-grid two-columns"><label className="field"><span>局域网地址</span><input value={network.hostname} onChange={(event) => setNetwork({ ...network, hostname: event.target.value })} placeholder="留空自动探测" /></label><label className="field"><span>DLNA 端口</span><input type="number" value={network.dlna_port} onChange={(event) => setNetwork({ ...network, dlna_port: Number(event.target.value) })} /></label><label className="field"><span>管理端口</span><input type="number" value={network.web_port} onChange={(event) => setNetwork({ ...network, web_port: Number(event.target.value) })} /></label><label className="field"><span>AirPlay 起始端口</span><input type="number" value={network.airplay_port_start} onChange={(event) => setNetwork({ ...network, airplay_port_start: Number(event.target.value) })} /></label></div></details></div>}
          {step === 5 && <div className="wizard-step"><div className="wizard-step-title"><Stethoscope size={24} /><div><h2>配置检查</h2><p>确认核心服务和账号状态。Unknown 不会阻止完成，稍后会自动刷新。</p></div></div><div className="wizard-checks"><CheckRow label="MiAirX" ok={health.data?.miairx.running} /><CheckRow label="Xiaomi 登录" ok={health.data?.xiaomi.status === "normal"} detail={health.data?.xiaomi.status} /><CheckRow label="DLNA" ok={health.data?.dlna.running} /><CheckRow label="AirPlay" ok={health.data?.airplay.running} /><CheckRow label="FFmpeg" ok={health.data?.ffmpeg.available} optional /><CheckRow label="已选音箱" ok={selected.size > 0} detail={`${selectedDevices.length || selected.size} 台`} /></div></div>}
          {step === 6 && <div className="wizard-intro"><div className="wizard-hero-icon success"><CheckCircle2 size={36} /></div><h2>设置完成</h2><p>MiAirX 已保存配置并热重载相关服务。接下来可以在 Dashboard 查看系统健康和音箱状态。</p><button type="button" className="button primary large" onClick={onComplete}>进入 Dashboard</button></div>}
        </div>

        {error && <div className="wizard-error" role="alert">{error}</div>}
        {step < 6 && <footer className="wizard-actions"><button type="button" className="button secondary" disabled={step === 0 || busy} onClick={() => { setError(""); setStep((value) => Math.max(0, value - 1)); }}><ChevronLeft size={16} />上一步</button><button type="button" className="button primary" disabled={busy} onClick={() => void saveAndContinue()}>{busy ? <LoaderCircle className="spin" size={16} /> : null}{step === 5 ? "完成设置" : "继续"}<ChevronRight size={16} /></button></footer>}
      </section>
    </main>
  );
}

function CheckRow({ label, ok, detail, optional = false }: { label: string; ok?: boolean; detail?: string; optional?: boolean }) {
  return <div><i className={ok ? "ok" : optional ? "optional" : "pending"}>{ok ? <Check size={14} /> : "·"}</i><strong>{label}</strong><span>{detail || (ok ? "正常" : optional ? "未安装（可选）" : "等待确认")}</span></div>;
}
