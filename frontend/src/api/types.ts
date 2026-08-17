export type PageId = "control" | "devices" | "settings" | "logs";

export interface AppStatus {
  version: string;
  hostname: string;
  dlna_port: number;
  web_port: number;
  airplay_port_start: number;
  speakers_count: number;
  is_running: boolean;
  account: string;
  mi_did: string;
}

export interface Speaker {
  did: string;
  name: string;
  hardware: string;
  enabled: boolean;
  udn: string;
  device_id: string;
}

export interface XiaomiDevice {
  miotDID?: string;
  did?: string;
  name?: string;
  hardware?: string;
  model?: string;
  [key: string]: unknown;
}

export interface PlaybackPosition {
  position: number;
  duration: number;
  state: string;
}

export interface PositionsResponse {
  positions: Record<string, PlaybackPosition>;
}

export interface AppConfig {
  account: string;
  password: string;
  mi_did: string;
  cookie: string;
  hostname: string;
  dlna_port: number;
  web_port: number;
  airplay_port_start: number;
  verbose: boolean;
  auto_resume_on_interrupt: boolean;
  resume_delay_seconds: number;
  default_volume: number;
  follow_device_volume: boolean;
  auto_restart: boolean;
  web_password: string;
}

export interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
}

export interface VersionInfo {
  current_version: string;
  latest_version: string | null;
  url: string | null;
  update_available: boolean;
  error: string | null;
}

export type ConfigUpdate = Partial<AppConfig>;

export interface ActionResponse {
  success: boolean;
  error?: string;
  message?: string;
  restart_required?: boolean;
}
