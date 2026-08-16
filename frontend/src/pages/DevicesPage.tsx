import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Cloud, RefreshCw, Router, Save, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { configQuery, devicesQuery, queryKeys, speakersQuery } from "../api/queries";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/Ui";
import { useToast } from "../components/Toast";

function deviceDid(device: { miotDID?: string; did?: string }) { return device.miotDID || device.did || ""; }

export function DevicesPage() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const devices = useQuery(devicesQuery);
  const config = useQuery(configQuery);
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [discovering, setDiscovering] = useState(false);
  useEffect(() => {
    if (!selected && config.data) setSelected(new Set(config.data.mi_did.split(",").map((did) => did.trim()).filter(Boolean)));
  }, [config.data, selected]);
  const chosen = selected ?? new Set<string>();
  const apply = useMutation({
    mutationFn: () => api.saveConfig({ mi_did: [...chosen].join(",") }),
    onSuccess: async (result) => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.config }), queryClient.invalidateQueries({ queryKey: queryKeys.speakers })]);
      showToast(result.restart_required ? "设备选择已保存，重启后生效" : "设备选择已保存并自动生效", "success");
    },
    onError: (error: Error) => showToast(error.message, "error"),
  });
  const deviceList = devices.data ?? [];
  const selectedCount = useMemo(() => deviceList.filter((device) => chosen.has(deviceDid(device))).length, [deviceList, chosen]);
  const savedDids = useMemo(() => new Set((config.data?.mi_did ?? "").split(",").map((did) => did.trim()).filter(Boolean)), [config.data?.mi_did]);
  const hasChanges = chosen.size !== savedDids.size || [...chosen].some((did) => !savedDids.has(did));
  const toggle = (did: string) => {
    if (!did) return;
    setSelected((current) => {
      const next = new Set(current ?? []);
      if (next.has(did)) next.delete(did); else next.add(did);
      return next;
    });
  };
  const discover = async () => {
    setDiscovering(true);
    try {
      const found = await api.discoverSpeakers();
      if (found.length === 0) {
        showToast("未识别到音箱设备", "info");
        return;
      }
      setSelected(new Set(found.map((device) => deviceDid(device)).filter(Boolean)));
      showToast(`已自动识别 ${found.length} 台音箱，点击「应用所选设备」保存`, "success");
    } catch (error) {
      showToast((error as Error).message, "error");
    } finally {
      setDiscovering(false);
    }
  };

  return (
    <div className="page-view">
      <PageHeader eyebrow="Device cloud" title="设备管理" description="从当前小米账号的云端设备中选择要接入 MiAirX 的音箱。" action={<><button className="button secondary" onClick={() => void discover()} disabled={discovering}><Sparkles size={17} />{discovering ? "正在识别" : "自动发现音箱"}</button><button className="button secondary" onClick={() => void devices.refetch()} disabled={devices.isFetching}><RefreshCw className={devices.isFetching ? "spin" : ""} size={17} />刷新设备</button></>} />
      <section className="section-card">
        <div className="section-heading"><div><Cloud size={20} /><span><strong>小米云设备</strong><small>{deviceList.length ? `共 ${deviceList.length} 台，已选 ${selectedCount} 台` : "等待云端设备列表"}</small></span></div><span className="selection-count">{chosen.size} selected</span></div>
        {devices.isLoading && <LoadingState label="正在读取小米云设备" />}
        {devices.isError && <ErrorState message={(devices.error as Error).message} retry={() => void devices.refetch()} />}
        {!devices.isLoading && !devices.isError && deviceList.length === 0 && <EmptyState title="没有发现设备" description="请先在系统设置中确认小米账号、密码或 Cookie 是否正确。" />}
        {deviceList.length > 0 && (
          <div className="device-list">
            {deviceList.map((device, index) => {
              const did = deviceDid(device);
              const active = chosen.has(did);
              return (
                <button type="button" className={`device-row ${active ? "selected" : ""}`} onClick={() => toggle(did)} key={did || index} disabled={!did}>
                  <div className="device-symbol"><Router size={21} /></div>
                  <div className="device-copy"><strong>{device.name || "未命名设备"}</strong><span>{device.hardware || device.model || "未知型号"}<i />DID {did || "不可用"}</span></div>
                  <div className="device-check" aria-label={active ? "已选择" : "未选择"}>{active && <Check size={16} />}</div>
                </button>
              );
            })}
          </div>
        )}
        <div className="sticky-actions"><p>{chosen.size === 0 ? "至少选择一台音箱后才能应用。" : hasChanges ? "选择已改变，应用后请重启 MiAirX。" : "当前选择与已保存配置一致。"}</p><button className="button primary" disabled={chosen.size === 0 || !hasChanges || apply.isPending} onClick={() => apply.mutate()}><Save size={17} />{apply.isPending ? "正在应用" : hasChanges ? "应用所选设备" : "已是最新"}</button></div>
      </section>
    </div>
  );
}
