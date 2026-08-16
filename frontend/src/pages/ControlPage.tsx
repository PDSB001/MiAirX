import { useMutation, useQuery } from "@tanstack/react-query";
import { CirclePause, CircleStop, Link2, Play, Radio, Speaker as SpeakerIcon, Volume2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { configQuery, positionsQuery, speakersQuery, statusQuery } from "../api/queries";
import type { PlaybackPosition, Speaker } from "../api/types";
import { Modal } from "../components/Modal";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/Ui";
import { useToast } from "../components/Toast";

function formatTime(value = 0) {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours > 0
    ? [hours, minutes, rest].map((part) => String(part).padStart(2, "0")).join(":")
    : [minutes, rest].map((part) => String(part).padStart(2, "0")).join(":");
}

function stateLabel(state?: string) {
  const normalized = state?.toUpperCase();
  if (normalized === "PLAYING") return "正在播放";
  if (normalized === "PAUSED_PLAYBACK") return "已暂停";
  if (normalized === "TRANSITIONING") return "正在切换";
  if (normalized === "STOPPED") return "已停止";
  return "等待投放";
}

function SpeakerCard({ speaker, position, defaultVolume, openPlay }: { speaker: Speaker; position?: PlaybackPosition; defaultVolume: number; openPlay: () => void }) {
  const { showToast } = useToast();
  const [volume, setVolume] = useState(defaultVolume);
  const [seekValue, setSeekValue] = useState<number | null>(null);
  const action = useMutation({
    mutationFn: ({ kind, value }: { kind: "pause" | "stop" | "volume" | "seek"; value?: number }) => {
      if (kind === "pause") return api.pause(speaker.did);
      if (kind === "stop") return api.stop(speaker.did);
      if (kind === "seek") return api.seek(speaker.did, value ?? 0);
      return api.volume(speaker.did, value ?? volume);
    },
    onSuccess: (_, variables) => {
      if (variables.kind !== "volume" && variables.kind !== "seek") {
        showToast(variables.kind === "pause" ? "已发送暂停指令" : "已停止播放", "success");
      }
    },
    onError: (error: Error) => showToast(error.message, "error"),
  });
  const duration = position?.duration ?? 0;
  const shownPosition = seekValue ?? position?.position ?? 0;
  const isPlaying = position?.state?.toUpperCase() === "PLAYING";

  return (
    <article className="speaker-card">
      <div className="speaker-card-head">
        <div className={`speaker-glyph ${isPlaying ? "playing" : ""}`}>
          <SpeakerIcon size={25} />
          {isPlaying && <span className="mini-equalizer" aria-hidden="true"><i /><i /><i /></span>}
        </div>
        <div className="speaker-identity">
          <div className="speaker-name-row">
            <h2>{speaker.name || `XiaoAI ${speaker.hardware}` || speaker.did}</h2>
            <span className={`playback-state ${isPlaying ? "active" : ""}`}><i />{stateLabel(position?.state)}</span>
          </div>
          <p>{speaker.hardware || "小米智能音箱"} <span>·</span> {speaker.did}</p>
        </div>
        <button className="button primary compact" onClick={openPlay}><Play size={17} fill="currentColor" />播放 URL</button>
      </div>

      <div className="timeline-block">
        <input
          aria-label={`${speaker.name} 播放进度`}
          className="range timeline"
          type="range"
          min={0}
          max={Math.max(duration, 1)}
          value={Math.min(shownPosition, Math.max(duration, 1))}
          disabled={duration <= 0 || action.isPending}
          onChange={(event) => setSeekValue(Number(event.target.value))}
          onPointerUp={() => { if (seekValue !== null) action.mutate({ kind: "seek", value: seekValue }); setSeekValue(null); }}
          onKeyUp={() => { if (seekValue !== null) action.mutate({ kind: "seek", value: seekValue }); setSeekValue(null); }}
        />
        <div className="timeline-meta"><span>{formatTime(shownPosition)}</span><span>{duration > 0 ? formatTime(duration) : "--:--"}</span></div>
      </div>

      <div className="speaker-controls">
        <div className="transport-actions">
          <button className="control-button" disabled={action.isPending} onClick={() => action.mutate({ kind: "pause" })}><CirclePause size={20} /><span>暂停</span></button>
          <button className="control-button danger" disabled={action.isPending} onClick={() => action.mutate({ kind: "stop" })}><CircleStop size={20} /><span>停止</span></button>
        </div>
        <div className="volume-control">
          <Volume2 size={19} />
          <input
            aria-label={`${speaker.name} 音量`}
            className="range"
            type="range"
            min={0}
            max={100}
            value={volume}
            onChange={(event) => setVolume(Number(event.target.value))}
            onPointerUp={() => action.mutate({ kind: "volume", value: volume })}
            onKeyUp={() => action.mutate({ kind: "volume", value: volume })}
          />
          <output>{volume}%</output>
        </div>
      </div>
    </article>
  );
}

export function ControlPage() {
  const { showToast } = useToast();
  const speakers = useQuery(speakersQuery);
  const positions = useQuery(positionsQuery);
  const config = useQuery(configQuery);
  const status = useQuery(statusQuery);
  const [target, setTarget] = useState<Speaker | null>(null);
  const [url, setUrl] = useState("");
  const play = useMutation({
    mutationFn: () => api.play(target?.did ?? "", url.trim()),
    onSuccess: (result) => {
      if (!result.success) throw new Error(result.error || "播放失败");
      showToast(`已投送到 ${target?.name || "音箱"}`, "success");
      setTarget(null); setUrl("");
    },
    onError: (error: Error) => showToast(error.message, "error"),
  });
  const enabledSpeakers = useMemo(() => speakers.data?.filter((speaker) => speaker.enabled) ?? [], [speakers.data]);

  return (
    <div className="page-view">
      <PageHeader
        eyebrow="Now playing"
        title="播放控制"
        description="管理局域网中的小米音箱，投送音频并查看实时播放状态。"
        action={
          <div className="hero-stat"><Radio size={18} /><span><strong>{enabledSpeakers.length}</strong> 台设备在线</span></div>
        }
      />

      <section className="summary-strip">
        <div><span>服务状态</span><strong className={status.data?.is_running ? "text-success" : ""}>{status.data?.is_running ? "运行中" : "连接中"}</strong></div>
        <div><span>服务地址</span><strong>{status.data ? `${status.data.hostname}:${status.data.dlna_port}` : "—"}</strong></div>
        <div><span>默认音量</span><strong>{config.data?.follow_device_volume ? "跟随设备" : `${config.data?.default_volume ?? 30}%`}</strong></div>
      </section>

      <section className="speaker-grid" aria-label="音箱列表">
        {speakers.isLoading && <LoadingState label="正在连接音箱" />}
        {speakers.isError && <ErrorState message={(speakers.error as Error).message} retry={() => void speakers.refetch()} />}
        {!speakers.isLoading && !speakers.isError && enabledSpeakers.length === 0 && (
          <EmptyState title="还没有可用音箱" description="前往设备管理，从小米云设备中选择至少一台音箱。" />
        )}
        {enabledSpeakers.map((speaker) => (
          <SpeakerCard key={speaker.did} speaker={speaker} position={positions.data?.positions[speaker.did]} defaultVolume={config.data?.default_volume ?? 30} openPlay={() => setTarget(speaker)} />
        ))}
      </section>

      <Modal open={Boolean(target)} title={`投送到 ${target?.name || "音箱"}`} description="输入可公开访问的音频地址，MiAirX 会将其交给音箱播放。" onClose={() => setTarget(null)}>
        <form onSubmit={(event) => { event.preventDefault(); if (url.trim()) play.mutate(); }}>
          <label className="field"><span>音频 URL</span><div className="input-with-icon"><Link2 size={18} /><input autoFocus type="url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://example.com/music.mp3" /></div></label>
          <div className="modal-actions"><button type="button" className="button secondary" onClick={() => setTarget(null)}>取消</button><button type="submit" className="button primary" disabled={play.isPending || !url.trim()}><Play size={17} fill="currentColor" />{play.isPending ? "正在投送" : "开始播放"}</button></div>
        </form>
      </Modal>
    </div>
  );
}
