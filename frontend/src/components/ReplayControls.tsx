import React from 'react';
import { ReplayStatus } from '../types';

interface ReplayControlsProps {
  replayStatus: ReplayStatus;
  onStart: () => void;
  onPause: () => void;
  onSpeedChange: (speed: number) => void;
  isLoading?: boolean;
}

export const ReplayControls: React.FC<ReplayControlsProps> = ({
  replayStatus,
  onStart,
  onPause,
  onSpeedChange,
  isLoading = false,
}) => {
  const speeds = [5, 15, 30, 60, 120];
  const isRunning = replayStatus.status === 'running';

  return (
    <div className="replay-controls-card">
      <div className="replay-left">
        <span className="control-title">Replay Simulation</span>
        <span className={`status-pill pill-${replayStatus.status}`}>
          {replayStatus.status.toUpperCase()}
        </span>
      </div>

      <div className="replay-actions">
        {isRunning ? (
          <button
            className="btn btn-warning"
            onClick={onPause}
            disabled={isLoading}
          >
            ⏸ Pause Replay
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={onStart}
            disabled={isLoading}
          >
            ▶ {replayStatus.status === 'paused' ? 'Resume Replay' : 'Start Replay'}
          </button>
        )}

        <div className="speed-selector">
          <span className="speed-label">Speed:</span>
          {speeds.map((s) => (
            <button
              key={s}
              className={`speed-btn ${replayStatus.speed === s ? 'active' : ''}`}
              onClick={() => onSpeedChange(s)}
              disabled={isLoading}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>

      <div className="replay-right">
        <span className="replay-sim-date">
          Date: {replayStatus.current_sim_time ? replayStatus.current_sim_time.slice(0, 10) : '2026-01-20'}
        </span>
      </div>
    </div>
  );
};
