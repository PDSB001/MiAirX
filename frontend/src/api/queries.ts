import { queryOptions } from "@tanstack/react-query";
import { api } from "./client";

export const queryKeys = {
  status: ["status"] as const,
  config: ["config"] as const,
  speakers: ["speakers"] as const,
  devices: ["devices"] as const,
  positions: ["positions"] as const,
  auth: ["auth"] as const,
  health: ["health"] as const,
};

export const statusQuery = queryOptions({ queryKey: queryKeys.status, queryFn: api.status, refetchInterval: 15_000 });
export const healthQuery = queryOptions({ queryKey: queryKeys.health, queryFn: api.health, refetchInterval: 15_000 });
export const configQuery = queryOptions({ queryKey: queryKeys.config, queryFn: api.config });
export const speakersQuery = queryOptions({ queryKey: queryKeys.speakers, queryFn: api.speakers, refetchInterval: 15_000 });
export const devicesQuery = queryOptions({ queryKey: queryKeys.devices, queryFn: api.devices, refetchInterval: 30_000 });
export const positionsQuery = queryOptions({ queryKey: queryKeys.positions, queryFn: api.positions, refetchInterval: 1_000 });
