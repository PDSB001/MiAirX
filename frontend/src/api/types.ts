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
  setup_completed: boolean;
}

export interface Speaker {
  did: string;
  name: string;
  hardware: string;
  enabled: boolean;
  udn: string;
  device_id: string;
  status: "online" | "offline" | "unknown";
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
  setup_completed: boolean;
}

export type XiaomiLoginStatus = "normal" | "expired" | "network_error" | "service_unavailable" | "not_configured" | "unknown";

export interface HealthSpeaker {
  did: string;
  name: string;
  model: string;
  status: "online" | "offline" | "unknown";
  current_source: "DLNA" | "AirPlay" | null;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  miairx: { running: boolean };
  xiaomi: { status: XiaomiLoginStatus };
  dlna: { running: boolean };
  airplay: { running: boolean };
  ffmpeg: { available: boolean; version: string | null };
  network: { hostname: string; dlna_port: number; web_port: number; airplay_port_start: number };
  speakers: HealthSpeaker[];
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

export interface QrStartResponse {
  success: boolean;
  session_id?: string;
  qrcode_image?: string;
  login_url?: string;
  error?: string;
}

export interface QrPollResponse {
  success: boolean;
  state: string;
  message?: string;
  user_id?: string;
}

export type ConfigUpdate = Partial<AppConfig>;

export interface ActionResponse {
  success: boolean;
  error?: string;
  message?: string;
  restart_required?: boolean;
  reauth_required?: boolean;
  error_code?: PlaybackErrorCode;
}

export type PlaybackErrorCode = "SOURCE_UNAVAILABLE" | "SPEAKER_UNAVAILABLE" | "XIAOMI_AUTH_EXPIRED" | "MINA_REQUEST_FAILED" | "TRANSCODE_FAILED" | "UNSUPPORTED_MEDIA" | "NETWORK_CONFIGURATION_ERROR";
