import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ExternalLink, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { queryKeys } from "../api/queries";
import { useToast } from "./Toast";

type QrStatus = "loading" | "waiting" | "scanned" | "confirmed" | "expired" | "failed";

export function XiaomiQrLogin({ onConfirmed }: { onConfirmed?: () => void }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<QrStatus>("loading");
  const [qrcodeImage, setQrcodeImage] = useState("");
  const [loginUrl, setLoginUrl] = useState("");
  const [message, setMessage] = useState("正在获取二维码…");
  const [attempt, setAttempt] = useState(0);
  const onConfirmedRef = useRef(onConfirmed);
  onConfirmedRef.current = onConfirmed;

  useEffect(() => {
    let cancelled = false;
    let sessionId = "";

    const poll = async () => {
      while (!cancelled) {
        try {
          const result = await api.pollQrLogin(sessionId);
          if (cancelled) return;
          if (result.state === "confirmed") {
            setStatus("confirmed");
            setMessage("登录成功");
            showToast("小米账号登录成功", "success");
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: queryKeys.config }),
              queryClient.invalidateQueries({ queryKey: queryKeys.speakers }),
              queryClient.invalidateQueries({ queryKey: queryKeys.health }),
            ]);
            onConfirmedRef.current?.();
            return;
          }
          if (result.state === "expired" || result.state === "failed") {
            setStatus(result.state);
            setMessage(result.message || "登录失败");
            return;
          }
          setStatus(result.state as QrStatus);
          setMessage(result.message || "等待扫码");
        } catch (error) {
          if (!cancelled) {
            setStatus("failed");
            setMessage((error as Error).message);
          }
          return;
        }
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

  const showQr = status === "waiting" || status === "scanned";
  return (
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
            <button type="button" className="button secondary" onClick={() => { setQrcodeImage(""); setLoginUrl(""); setAttempt((value) => value + 1); }}>重新获取</button>
          </div>
        )}
      </div>
      <div className={`qr-status qr-status-${status}`} role="status"><span className="qr-status-dot" /><span>{message}</span></div>
    </div>
  );
}
