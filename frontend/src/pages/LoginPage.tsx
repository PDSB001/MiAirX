import { LockKeyhole } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import { useToast } from "../components/Toast";

export function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const { showToast } = useToast();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!password.trim()) return;
    setPending(true);
    try {
      const result = await api.login(password);
      if (!result.success) throw new Error(result.error || "登录失败");
      showToast("登录成功", "success");
      onSuccess();
    } catch (error) {
      showToast((error as Error).message, "error");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="login-view">
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-mark" aria-hidden="true">
            <i className="brand-arc arc-one" />
            <i className="brand-arc arc-two" />
            <i className="brand-core" />
          </div>
          <div>
            <strong>MiAirX</strong>
            <span>Sound, connected.</span>
          </div>
        </div>
        <h1>管理台已上锁</h1>
        <p>请输入后台密码以继续访问。</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>后台密码</span>
            <div className="input-with-icon">
              <LockKeyhole size={18} />
              <input
                autoFocus
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="输入 web_password"
              />
            </div>
          </label>
          <button className="button primary large login-submit" type="submit" disabled={pending || !password.trim()}>
            {pending ? "正在验证" : "登录"}
          </button>
        </form>
      </div>
    </div>
  );
}
