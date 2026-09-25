import React, { useState } from 'react';
import { TrainETAResponse, TrainExplainResponse, TrainListItem } from '../types';

interface PassengerViewProps {
  trains: TrainListItem[];
  selectedTrainId: string | null;
  onSelectTrain: (runId: string) => void;
  etaData: TrainETAResponse | null;
  explainData: TrainExplainResponse | null;
  isLoading: boolean;
}

export const PassengerView: React.FC<PassengerViewProps> = ({
  trains,
  selectedTrainId,
  onSelectTrain,
  etaData,
  explainData,
  isLoading,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [alertEnabled, setAlertEnabled] = useState(false);
  const [alertMessage, setAlertMessage] = useState<string | null>(null);

  const filteredTrains = trains.filter(
    (t) =>
      t.train_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.train_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const selectedTrain = trains.find((t) => t.run_id === selectedTrainId) || trains[0];

  const handleToggleAlert = () => {
    const newState = !alertEnabled;
    setAlertEnabled(newState);
    setAlertMessage(
      newState
        ? `🔔 SMS & Push Alert enabled for Train ${selectedTrain?.train_number} arrival!`
        : `🔕 Arrival alert disabled.`
    );
    setTimeout(() => setAlertMessage(null), 4000);
  };

  const nextStop = etaData?.downstream_stations[0];

  return (
    <div className="passenger-view-container">
      {/* Search and Train Selector */}
      <div className="passenger-search-bar">
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="train-search-input"
            placeholder="Search train by number (e.g. 12002) or name..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="train-quick-chips">
          {filteredTrains.slice(0, 6).map((t) => (
            <button
              key={t.run_id}
              className={`chip-btn ${selectedTrain?.run_id === t.run_id ? 'active' : ''}`}
              onClick={() => onSelectTrain(t.run_id)}
            >
              {t.train_number} - {t.train_name}
            </button>
          ))}
        </div>
      </div>

      {alertMessage && (
        <div className="alert-toast">
          {alertMessage}
        </div>
      )}

      {selectedTrain ? (
        <div className="passenger-dashboard-grid">
          {/* Hero ETA Card */}
          <div className="card eta-hero-card">
            <div className="card-header-flex">
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <span className="hero-train-type">{selectedTrain.train_type}</span>
                  <span className="simulated-badge" style={{ fontSize: '10px', padding: '2px 6px' }}>⚠️ SIMULATED DATA</span>
                </div>
                <h2 className="hero-train-title">
                  {selectedTrain.train_number} — {selectedTrain.train_name}
                </h2>
                <p className="hero-route">
                  {selectedTrain.source} → {selectedTrain.destination}
                </p>
              </div>

              <button
                className={`btn alert-toggle-btn ${alertEnabled ? 'alert-on' : 'alert-off'}`}
                onClick={handleToggleAlert}
              >
                {alertEnabled ? '🔔 Alert Enabled' : '🔕 Alert Me Before Arrival'}
              </button>
            </div>

            {nextStop ? (
              <div className="eta-highlight-box">
                <div className="eta-main-stat">
                  <span className="eta-label">Upcoming Station ({nextStop.station_code})</span>
                  <h3 className="eta-station-name">{nextStop.station_name}</h3>
                  <div className="eta-time-row">
                    <span className="eta-time-median">
                      {new Date(nextStop.eta_median).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <span className={`eta-delay-chip ${nextStop.predicted_median_delay_min > 15 ? 'late' : 'ontime'}`}>
                      {nextStop.predicted_median_delay_min > 0
                        ? `+${Math.round(nextStop.predicted_median_delay_min)} min delay`
                        : 'On-Time'}
                    </span>
                  </div>
                </div>

                <div className="eta-bounds-grid">
                  <div className="bound-box">
                    <span className="bound-label">10th Percentile (Best)</span>
                    <span className="bound-val">
                      {new Date(nextStop.eta_lower).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <div className="bound-box median">
                    <span className="bound-label">50th Percentile (Median)</span>
                    <span className="bound-val">
                      {new Date(nextStop.eta_median).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <div className="bound-box">
                    <span className="bound-label">90th Percentile (Worst)</span>
                    <span className="bound-val">
                      {new Date(nextStop.eta_upper).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <div className="bound-box">
                    <span className="bound-label">Prediction Interval</span>
                    <span className="bound-val">±{Math.round(nextStop.interval_width_min / 2)} min</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="empty-state">Train has completed its scheduled route.</div>
            )}
          </div>

          {/* "Why did this change?" Explanation Card */}
          <div className="card explain-card">
            <div className="explain-header">
              <span className="explain-icon">💡</span>
              <div>
                <h3>Why Did This ETA Change?</h3>
                <span className="sub-hint">Real-time Shapley attribution & infrastructure telemetry</span>
              </div>
            </div>

            <div className="explain-reason-bubble">
              <p className="reason-text">
                {explainData?.latest_explanation || nextStop?.reasons || 'Operations running as scheduled on timetable.'}
              </p>
            </div>

            <div className="drivers-container">
              <span className="drivers-heading">Primary Delay Contributors:</span>
              <div className="drivers-list">
                {explainData?.top_drivers && explainData.top_drivers.length > 0 ? (
                  explainData.top_drivers.map((d, idx) => (
                    <div key={idx} className="driver-pill">
                      <span className="driver-icon">
                        {d.category === 'infrastructure' ? '🚧' : d.category === 'weather' ? '🌫️' : '⏱️'}
                      </span>
                      <span className="driver-name">{d.label}</span>
                      <span className="driver-shap">{d.shap_value > 0 ? `+${d.shap_value.toFixed(1)}m` : `${d.shap_value.toFixed(1)}m`}</span>
                    </div>
                  ))
                ) : (
                  <span className="no-drivers">No abnormal friction detected on current route section.</span>
                )}
              </div>
            </div>
          </div>

          {/* Downstream Stations Timeline */}
          <div className="card timeline-card full-width">
            <h3>Upcoming Station Stops & Forecast Progression</h3>
            <div className="timeline-container">
              {etaData?.downstream_stations && etaData.downstream_stations.length > 0 ? (
                <div className="timeline-steps">
                  {etaData.downstream_stations.map((st, i) => (
                    <div key={st.station_code} className="timeline-item">
                      <div className="timeline-marker">
                        <span className="marker-dot">{i + 1}</span>
                        {i < etaData.downstream_stations.length - 1 && <div className="marker-line" />}
                      </div>
                      <div className="timeline-content">
                        <div className="timeline-row">
                          <span className="timeline-st-code">{st.station_code}</span>
                          <span className="timeline-st-name">{st.station_name}</span>
                          <span className={`timeline-delay ${st.predicted_median_delay_min > 10 ? 'delay-late' : 'delay-ok'}`}>
                            {st.predicted_median_delay_min > 0 ? `+${Math.round(st.predicted_median_delay_min)} min` : 'On Time'}
                          </span>
                        </div>
                        <div className="timeline-times">
                          <span>Scheduled: <b>{new Date(st.sched_arr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b></span>
                          <span>Baseline A: <b>{new Date(st.baseline_a_eta).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b></span>
                          <span>Predicted ETA: <b className="highlight-eta">{new Date(st.eta_median).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</b> ({new Date(st.eta_lower).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – {new Date(st.eta_upper).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })})</span>
                        </div>
                        <div className="timeline-reason-snippet">
                          ℹ️ {st.reasons}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-state">No remaining downstream stops for this train.</div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="card empty-state">No train selected.</div>
      )}
    </div>
  );
};
