import React, { useEffect, useState, useCallback } from 'react';
import {
  DisruptionItem,
  ReplayStatus,
  StationItem,
  TrainETAResponse,
  TrainExplainResponse,
  TrainListItem,
  WebSocketETAUpdate,
} from './types';
import {
  connectWebSocket,
  fetchDisruptions,
  fetchReplayStatus,
  fetchStations,
  fetchTrainETA,
  fetchTrainExplain,
  fetchTrains,
  pauseReplay,
  setReplaySpeed,
  startReplay,
} from './api/client';
import { Header } from './components/Header';
import { ReplayControls } from './components/ReplayControls';
import { ControlRoomMap } from './components/ControlRoomMap';
import { TrainTable } from './components/TrainTable';
import { PassengerView } from './components/PassengerView';

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<'control' | 'passenger'>('control');
  const [stations, setStations] = useState<StationItem[]>([]);
  const [trains, setTrains] = useState<TrainListItem[]>([]);
  const [disruptions, setDisruptions] = useState<DisruptionItem[]>([]);
  const [selectedTrainId, setSelectedTrainId] = useState<string | null>(null);

  const [etaData, setEtaData] = useState<TrainETAResponse | null>(null);
  const [explainData, setExplainData] = useState<TrainExplainResponse | null>(null);

  const [replayStatus, setReplayStatus] = useState<ReplayStatus>({
    status: 'stopped',
    current_sim_time: '2026-01-20T06:00:00',
    speed: 1.0,
    active_run_id: null,
  });

  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Initial data loading
  useEffect(() => {
    async function initData() {
      try {
        const [stList, trList, disList, repStatus] = await Promise.all([
          fetchStations(),
          fetchTrains(),
          fetchDisruptions(),
          fetchReplayStatus(),
        ]);
        setStations(stList);
        setTrains(trList);
        setDisruptions(disList);
        setReplayStatus(repStatus);

        if (trList.length > 0) {
          setSelectedTrainId(trList[0].run_id);
        }
      } catch (err) {
        console.error('Failed to initialize app data:', err);
      }
    }
    initData();
  }, []);

  // Fetch ETA & Explanations when selected train changes
  useEffect(() => {
    if (!selectedTrainId) return;

    let isMounted = true;
    async function loadTrainDetails() {
      try {
        const [etaRes, expRes] = await Promise.all([
          fetchTrainETA(selectedTrainId!),
          fetchTrainExplain(selectedTrainId!),
        ]);
        if (isMounted) {
          setEtaData(etaRes);
          setExplainData(expRes);
        }
      } catch (e) {
        console.error(`Error loading details for train ${selectedTrainId}:`, e);
      }
    }

    loadTrainDetails();
    return () => {
      isMounted = false;
    };
  }, [selectedTrainId, replayStatus.current_sim_time]);

  // WebSocket Live Updates with Fallback Polling
  const handleWebSocketMessage = useCallback(
    (msg: WebSocketETAUpdate) => {
      if (msg.type === 'eta_update') {
        if (msg.sim_time) {
          setReplayStatus((prev) => ({
            ...prev,
            current_sim_time: msg.sim_time!,
          }));
        }

        // Update train position in fleet list
        if (msg.run_id) {
          setTrains((prev) =>
            prev.map((t) => {
              if (t.run_id === msg.run_id) {
                return {
                  ...t,
                  current_station: msg.current_station || t.current_station,
                  next_station: msg.next_station !== undefined ? msg.next_station : t.next_station,
                  current_delay_min: msg.current_delay_min ?? t.current_delay_min,
                };
              }
              return t;
            })
          );
        }

        // Update downstream prediction and explainability if this is the currently focused train
        if (msg.run_id === selectedTrainId) {
          if (msg.predictions) {
            setEtaData((prev) => {
              if (!prev) return null;
              return {
                ...prev,
                current_station: msg.current_station || prev.current_station,
                current_delay_min: msg.current_delay_min ?? prev.current_delay_min,
                downstream_stations: msg.predictions!,
              };
            });
          }

          if (msg.latest_explanation || msg.top_drivers) {
            setExplainData((prev) => {
              if (!prev) return null;
              return {
                ...prev,
                latest_explanation: msg.latest_explanation || prev.latest_explanation,
                top_drivers: msg.top_drivers || prev.top_drivers,
                delta_min: msg.delta_min ?? prev.delta_min,
              };
            });
          }
        }
      }
    },
    [selectedTrainId]
  );

  useEffect(() => {
    // Connect to corridor-wide stream
    const cleanupWs = connectWebSocket(
      selectedTrainId || 'all',
      handleWebSocketMessage,
      (connected) => setWsConnected(connected)
    );

    // Fallback polling if WebSocket is not connected
    const pollInterval = setInterval(async () => {
      if (!wsConnected) {
        try {
          const [updatedTrains, status] = await Promise.all([
            fetchTrains(),
            fetchReplayStatus(),
          ]);
          setTrains(updatedTrains);
          setReplayStatus(status);
        } catch (e) {
          console.warn('Fallback polling error:', e);
        }
      }
    }, 3000);

    return () => {
      cleanupWs();
      clearInterval(pollInterval);
    };
  }, [selectedTrainId, wsConnected, handleWebSocketMessage]);

  // Replay Handlers
  const handleStartReplay = async () => {
    setIsLoading(true);
    try {
      const res = await startReplay(undefined, selectedTrainId || undefined, replayStatus.speed);
      setReplayStatus(res);
    } catch (e) {
      console.error('Failed to start replay:', e);
    } finally {
      setIsLoading(false);
    }
  };

  const handlePauseReplay = async () => {
    setIsLoading(true);
    try {
      const res = await pauseReplay();
      setReplayStatus(res);
    } catch (e) {
      console.error('Failed to pause replay:', e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSpeedChange = async (newSpeed: number) => {
    try {
      const res = await setReplaySpeed(newSpeed);
      setReplayStatus(res);
    } catch (e) {
      console.error('Failed to change speed:', e);
    }
  };

  return (
    <div className="app-layout">
      <Header
        activeView={activeView}
        onViewChange={setActiveView}
        wsConnected={wsConnected}
        simTime={replayStatus.current_sim_time}
      />

      <main className="main-content">
        <ReplayControls
          replayStatus={replayStatus}
          onStart={handleStartReplay}
          onPause={handlePauseReplay}
          onSpeedChange={handleSpeedChange}
          isLoading={isLoading}
        />

        {activeView === 'control' ? (
          <div className="control-room-layout">
            <div className="control-left-col">
              <ControlRoomMap
                stations={stations}
                trains={trains}
                disruptions={disruptions}
                selectedTrainId={selectedTrainId}
                onSelectTrain={setSelectedTrainId}
                simTime={replayStatus.current_sim_time}
              />
            </div>
            <div className="control-right-col">
              <TrainTable
                trains={trains}
                selectedTrainId={selectedTrainId}
                onSelectTrain={setSelectedTrainId}
              />
            </div>
          </div>
        ) : (
          <PassengerView
            trains={trains}
            selectedTrainId={selectedTrainId}
            onSelectTrain={setSelectedTrainId}
            etaData={etaData}
            explainData={explainData}
            isLoading={isLoading}
          />
        )}
      </main>
    </div>
  );
};
