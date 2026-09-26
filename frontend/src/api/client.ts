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
  onStatusChange?: (connected: boolean) => void,
  onFallbackChange?: (isPolling: boolean) => void
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const wsUrl = `${protocol}//${host}/ws/trains/${encodeURIComponent(runId)}`;

  let ws: WebSocket | null = null;
  let isClosedIntentionally = false;
  let reconnectAttempts = 0;
  const maxReconnectAttempts = 3;
  let reconnectTimer: any = null;
  let recoveryTimer: any = null;
  let isPollingActive = false;

  function stopTimers() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (recoveryTimer) {
      clearInterval(recoveryTimer);
      recoveryTimer = null;
    }
  }

  function startRecoveryProbe() {
    if (recoveryTimer || isClosedIntentionally) return;
    // Check every 15s if the backend is reachable to restore WebSocket connection
    recoveryTimer = setInterval(async () => {
      if (isClosedIntentionally || !isPollingActive) {
        if (recoveryTimer) clearInterval(recoveryTimer);
        recoveryTimer = null;
        return;
      }

      console.log('[WebSocket] Polling active: probing backend health for WebSocket recovery...');
      try {
        const health = await fetchHealth();
        if (health && health.status === 'ok') {
          console.log('[WebSocket] Backend is healthy. Initiating clean WebSocket reconnect...');
          stopTimers();
          reconnectAttempts = 0;
          connect();
        }
      } catch {
        console.log('[WebSocket] Backend health check failed, remaining in REST polling fallback.');
      }
    }, 15000);
  }

  function connect() {
    if (isClosedIntentionally) return;
    stopTimers();

    try {
      console.log(`[WebSocket] Connecting to ${wsUrl} (Attempt ${reconnectAttempts + 1}/${maxReconnectAttempts})...`);
      ws = new WebSocket(wsUrl);

      ws.onopen = (event) => {
        console.log(`[WebSocket] Successfully opened connection to ${wsUrl}`, event);
        reconnectAttempts = 0;
        stopTimers();

        if (isPollingActive) {
          isPollingActive = false;
          console.log('[WebSocket] Exiting polling fallback mode: WebSocket reconnected.');
          if (onFallbackChange) onFallbackChange(false);
        }

        if (onStatusChange) onStatusChange(true);
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          console.log('[WebSocket] Message received on ' + wsUrl + ':', parsed);
          onMessage(parsed);
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e);
        }
      };

      ws.onclose = (event: CloseEvent) => {
        console.warn(
          `[WebSocket] Closed connection to ${wsUrl}: code=${event.code}, reason="${event.reason}", wasClean=${event.wasClean}`
        );

        if (isClosedIntentionally) {
          console.log('[WebSocket] Socket closed intentionally during cleanup.');
          return;
        }

        if (onStatusChange) onStatusChange(false);

        // If polling is already active, do not schedule rapid reconnect loops
        if (isPollingActive) {
          startRecoveryProbe();
          return;
        }

        // Attempt reconnection with exponential backoff
        if (reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts++;
          const backoffDelay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 5000);
          console.log(
            `[WebSocket] Reconnect attempt ${reconnectAttempts}/${maxReconnectAttempts} scheduled in ${backoffDelay}ms...`
          );
          reconnectTimer = setTimeout(connect, backoffDelay);
        } else {
          // Reconnect attempts exhausted -> Real failure confirmed!
          isPollingActive = true;
          console.warn(
            `[WebSocket] All ${maxReconnectAttempts} reconnect attempts failed. Triggering REST polling fallback.`
          );
          if (onFallbackChange) onFallbackChange(true);
          startRecoveryProbe();
        }
      };

      ws.onerror = (event) => {
        console.error(`[WebSocket] Error event on ${wsUrl}:`, event);
        // Do not call ws?.close() here; browser automatically triggers onclose following onerror.
      };
    } catch (e) {
      console.error('[WebSocket] Exception during connect initiation:', e);
      if (isClosedIntentionally) return;
      if (onStatusChange) onStatusChange(false);

      if (isPollingActive) {
        startRecoveryProbe();
        return;
      }

      if (reconnectAttempts < maxReconnectAttempts) {
        reconnectAttempts++;
        const backoffDelay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 5000);
        reconnectTimer = setTimeout(connect, backoffDelay);
      } else {
        isPollingActive = true;
        if (onFallbackChange) onFallbackChange(true);
        startRecoveryProbe();
      }
    }
  }

  connect();

  return () => {
    isClosedIntentionally = true;
    stopTimers();
    if (isPollingActive) {
      isPollingActive = false;
      if (onFallbackChange) onFallbackChange(false);
    }
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close();
      ws = null;
    }
  };
}
