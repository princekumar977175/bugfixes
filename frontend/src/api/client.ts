/**
 * API client for interacting with the FastAPI REST endpoints and WebSocket.
 */

import {
  DisruptionItem,
  ReplayStatus,
  StationItem,
  TrainETAResponse,
  TrainExplainResponse,
  TrainListItem,
  WebSocketETAUpdate,
} from '../types';

export const API_BASE = '';

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function fetchStations(): Promise<StationItem[]> {
  const res = await fetch(`${API_BASE}/stations`);
  if (!res.ok) throw new Error(`Failed to load stations: ${res.statusText}`);
  const data = await res.json();
  return data.stations || [];
}

export async function fetchTrains(date?: string, status?: string): Promise<TrainListItem[]> {
  const params = new URLSearchParams();
  if (date) params.append('date', date);
  if (status) params.append('status', status);

  const res = await fetch(`${API_BASE}/trains?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to load trains: ${res.statusText}`);
  const data = await res.json();
  return data.trains || [];
}

export async function fetchTrainETA(runId: string, timestamp?: string): Promise<TrainETAResponse> {
  const params = new URLSearchParams();
  if (timestamp) params.append('timestamp', timestamp);

  const res = await fetch(`${API_BASE}/trains/${encodeURIComponent(runId)}/eta?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch ETA for ${runId}: ${res.statusText}`);
  return res.json();
}

export async function fetchTrainExplain(runId: string, timestamp?: string): Promise<TrainExplainResponse> {
  const params = new URLSearchParams();
  if (timestamp) params.append('timestamp', timestamp);

  const res = await fetch(`${API_BASE}/trains/${encodeURIComponent(runId)}/explain?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch explainability for ${runId}: ${res.statusText}`);
  return res.json();
}

export async function fetchDisruptions(sectionId: string = 'all'): Promise<DisruptionItem[]> {
  const res = await fetch(`${API_BASE}/sections/${encodeURIComponent(sectionId)}/disruptions`);
  if (!res.ok) throw new Error(`Failed to load disruptions: ${res.statusText}`);
  const data = await res.json();
  return data.disruptions || [];
}

export async function fetchReplayStatus(): Promise<ReplayStatus> {
  const res = await fetch(`${API_BASE}/replay/status`);
  if (!res.ok) throw new Error(`Failed to load replay status: ${res.statusText}`);
  return res.json();
}

export async function startReplay(date?: string, runId?: string, speed: number = 1.0): Promise<ReplayStatus> {
  const res = await fetch(`${API_BASE}/replay/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date, run_id: runId, speed }),
  });
  if (!res.ok) throw new Error(`Failed to start replay: ${res.statusText}`);
  return res.json();
}

export async function pauseReplay(): Promise<ReplayStatus> {
  const res = await fetch(`${API_BASE}/replay/pause`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed to pause replay: ${res.statusText}`);
  return res.json();
}

export async function setReplaySpeed(speed: number): Promise<ReplayStatus> {
  const res = await fetch(`${API_BASE}/replay/speed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed }),
  });
  if (!res.ok) throw new Error(`Failed to set speed: ${res.statusText}`);
  return res.json();
}

/**
 * Connect to WebSocket with automatic fallback handling.
 */
export function connectWebSocket(
  runId: string,
  onMessage: (msg: WebSocketETAUpdate) => void,
  onStatusChange?: (connected: boolean) => void
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/ws/trains/${encodeURIComponent(runId)}`;

  let ws: WebSocket | null = null;
  let isClosedIntentionally = false;
  let retryTimer: any = null;

  function connect() {
    try {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (onStatusChange) onStatusChange(true);
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          onMessage(parsed);
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      ws.onclose = () => {
        if (onStatusChange) onStatusChange(false);
        if (!isClosedIntentionally) {
          retryTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        if (onStatusChange) onStatusChange(false);
        ws?.close();
      };
    } catch (e) {
      if (onStatusChange) onStatusChange(false);
      if (!isClosedIntentionally) {
        retryTimer = setTimeout(connect, 3000);
      }
    }
  }

  connect();

  return () => {
    isClosedIntentionally = true;
    if (retryTimer) clearTimeout(retryTimer);
    if (ws) ws.close();
  };
}
