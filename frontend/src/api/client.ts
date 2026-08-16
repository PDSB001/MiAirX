import type { ActionResponse, AppConfig, AppStatus, AuthStatus, ConfigUpdate, PositionsResponse, Speaker, XiaomiDevice } from "./types";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
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
    const error = payload as { error?: string; message?: string } | null;
    throw new ApiError(error?.error ?? error?.message ?? `请求失败 (${response.status})`, response.status);
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
  status: () => request<AppStatus>("/api/status"),
  config: () => request<AppConfig>("/api/config"),
  speakers: () => request<Speaker[]>("/api/speakers"),
  devices: () => request<XiaomiDevice[]>("/api/devices"),
  positions: () => request<PositionsResponse>("/api/positions"),
  saveConfig: (config: ConfigUpdate) => post<ActionResponse>("/api/config", config),
  play: (did: string, url: string) => post<ActionResponse>("/api/play", { did, url }),
  pause: (did: string) => post<ActionResponse>("/api/pause", { did }),
  stop: (did: string) => post<ActionResponse>("/api/stop", { did }),
  volume: (did: string, volume: number) => post<ActionResponse>("/api/volume", { did, volume }),
  seek: (did: string, position: number) => post<ActionResponse>("/api/seek", { did, position }),
};
