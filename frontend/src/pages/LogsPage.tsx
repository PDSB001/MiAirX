import { Download, FileArchive, Pause, Play, ScrollText, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { PageHeader } from "../components/Ui";
import { useToast } from "../components/Toast";

interface LogRecord {
  time: string;
  level: string;
  name: string;
  message: string;
}

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "debug",
  INFO: "info",
  WARNING: "warn",
  WARN: "warn",
  ERROR: "error",
  CRITICAL: "error",
};

const MAX_LOGS = 500;

export function LogsPage() {
  const { showToast } = useToast();
  const [logs, setLogs] = useState<LogRecord[]>([]);
  const [paused, setPaused] = useState(false);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const source = new EventSource("/api/logs/stream");
    sourceRef.current = source;
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      try {
        const record = JSON.parse(event.data) as LogRecord;
        if (pausedRef.current) return;
        setLogs((current) => [...current.slice(-(MAX_LOGS - 1)), record]);
      } catch {
        // Ignore malformed lines.
      }
    };
    return () => source.close();
  }, []);

  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    if (!paused) logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, paused]);

  const downloadDiagnostics = () => {
    window.location.assign("/api/diagnostics");
    showToast("诊断包已开始下载", "success");
  };

  return (
    <div className="page-view">
      <PageHeader
        eyebrow="Diagnostics"
        title="日志与诊断"
        description="实时查看服务日志，或打包下载配置与日志用于排障。"
        action={
          <button className="button secondary" onClick={downloadDiagnostics}>
            <FileArchive size={17} />下载诊断包
          </button>
        }
      />

      <section className="section-card logs-card">
        <div className="section-heading">
          <div>
            <ScrollText size={20} />
            <span>
              <strong>实时日志</strong>
              <small>
                {connected ? "已连接，实时接收日志" : "连接中断，正在重试…"} · 最多保留 {MAX_LOGS} 条
              </small>
            </span>
          </div>
          <div className="logs-actions">
            <button className="button ghost small" onClick={() => setPaused((p) => !p)}>
              {paused ? <Play size={15} /> : <Pause size={15} />}
              {paused ? "继续" : "暂停"}
            </button>
            <button className="button ghost small" onClick={() => setLogs([])}>
              <Trash2 size={15} />清空
            </button>
          </div>
        </div>

        <div className="log-view" role="log" aria-live="polite">
          {logs.length === 0 && (
            <div className="log-empty">
              <Download size={22} />
              <p>暂无日志。服务启动或发生操作后，日志会实时出现在这里。</p>
            </div>
          )}
          {logs.map((record, index) => (
            <div className="log-line" key={index}>
              <span className="log-time">{record.time}</span>
              <span className={`log-level ${LEVEL_COLORS[record.level] ?? "info"}`}>{record.level}</span>
              <span className="log-name">{record.name}</span>
              <span className="log-message">{record.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </section>
    </div>
  );
}


