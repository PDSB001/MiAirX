import type { ActionResponse, AppConfig, AppStatus, AuthStatus, ConfigUpdate, HealthStatus, PlaybackErrorCode, PositionsResponse, QrPollResponse, QrStartResponse, Speaker, VersionInfo, XiaomiDevice } from "./types";

const playbackMessages: Partial<Record<PlaybackErrorCode, string>> = {
  SOURCE_UNAVAILABLE: "音频来源无法访问，请检查链接是否有效。",
  SPEAKER_UNAVAILABLE: "音箱当前离线或不可用。",
  XIAOMI_AUTH_EXPIRED: "小米登录已失效，请重新扫码登录。",
  MINA_REQUEST_FAILED: "小米音箱服务请求失败，请稍后重试。",
  TRANSCODE_FAILED: "音频转换失败，请检查 FFmpeg 或更换格式。",
  UNSUPPORTED_MEDIA: "不支持此媒体地址或音频格式。",
  NETWORK_CONFIGURATION_ERROR: "网络配置有误，音箱无法访问该来源。",
};

export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly errorCode?: PlaybackErrorCode) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = payload as { error?: string; message?: string; error_code?: PlaybackErrorCode } | null;
    const errorCode = error?.error_code;
    throw new ApiError(errorCode ? playbackMessages[errorCode] ?? error?.error ?? errorCode : error?.error ?? error?.message ?? `请求失败 (${response.status})`, response.status, errorCode);
  }
  return payload as T;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (password: string) => post<ActionResponse>("/api/auth/login", { password }),
  logout: () => post<ActionResponse>("/api/auth/logout", {}),
  startQrLogin: () => post<QrStartResponse>("/api/auth/qrcode", {}),
  pollQrLogin: (sessionId: string) => request<QrPollResponse>(`/api/auth/qrcode/poll?session_id=${encodeURIComponent(sessionId)}`),
  status: () => request<AppStatus>("/api/status"),
  health: () => request<HealthStatus>("/api/health"),
  version: (force = false) => request<VersionInfo>(`/api/version${force ? "?force=1" : ""}`),
  config: () => request<AppConfig>("/api/config"),
  speakers: () => request<Speaker[]>("/api/speakers"),
  devices: () => request<XiaomiDevice[]>("/api/devices"),
  discoverSpeakers: () => request<XiaomiDevice[]>("/api/devices/discover"),
  positions: () => request<PositionsResponse>("/api/positions"),
  saveConfig: (config: ConfigUpdate) => post<ActionResponse>("/api/config", config),
  play: (did: string, url: string) => post<ActionResponse>("/api/play", { did, url }),
  pause: (did: string) => post<ActionResponse>("/api/pause", { did }),
  stop: (did: string) => post<ActionResponse>("/api/stop", { did }),
  volume: (did: string, volume: number) => post<ActionResponse>("/api/volume", { did, volume }),
  seek: (did: string, position: number) => post<ActionResponse>("/api/seek", { did, position }),
};
