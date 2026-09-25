import React from 'react';
import { TrainListItem } from '../types';

interface TrainTableProps {
  trains: TrainListItem[];
  selectedTrainId: string | null;
  onSelectTrain: (runId: string) => void;
}

export const TrainTable: React.FC<TrainTableProps> = ({
  trains,
  selectedTrainId,
  onSelectTrain,
}) => {
  // Sort trains by delay descending
  const sortedTrains = [...trains].sort((a, b) => b.current_delay_min - a.current_delay_min);

  return (
    <div className="train-table-card">
      <div className="table-header-banner">
        <h3>Corridor Active Trains ({trains.length})</h3>
        <span className="table-hint">Click a train to track downstream ETA & drivers</span>
      </div>

      <div className="table-scroll-container">
        <table className="rail-table">
          <thead>
            <tr>
              <th>Train</th>
              <th>Category</th>
              <th>Current Station</th>
              <th>Next Station</th>
              <th>Delay</th>
              <th>Status</th>
              <th>Knock-on Risk</th>
            </tr>
          </thead>
          <tbody>
            {sortedTrains.map((t) => {
              const isSelected = selectedTrainId === t.run_id;
              const delay = t.current_delay_min;
              const delayClass =
                delay > 20 ? 'delay-high' : delay > 8 ? 'delay-medium' : 'delay-low';

              return (
                <tr
                  key={t.run_id}
                  className={`table-row ${isSelected ? 'row-selected' : ''}`}
                  onClick={() => onSelectTrain(t.run_id)}
                >
                  <td className="train-cell">
                    <span className="train-no">{t.train_number}</span>
                    <span className="train-nm">{t.train_name}</span>
                  </td>
                  <td>
                    <span className="type-badge">{t.train_type}</span>
                  </td>
                  <td>
                    <span className="station-code-pill">{t.current_station || '--'}</span>
                  </td>
                  <td>
                    <span className="station-code-pill next">{t.next_station || 'Terminus'}</span>
                  </td>
                  <td>
                    <span className={`delay-badge ${delayClass}`}>
                      {delay > 0 ? `+${delay.toFixed(1)}m` : 'On-Time'}
                    </span>
                  </td>
                  <td>
                    <span className={`status-tag status-${t.status}`}>
                      {t.status.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span className={`risk-tag risk-${t.knock_on_risk}`}>
                      {t.knock_on_risk.toUpperCase()}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
