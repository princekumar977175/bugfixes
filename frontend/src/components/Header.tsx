import React from 'react';

interface HeaderProps {
  activeView: 'control' | 'passenger';
  onViewChange: (view: 'control' | 'passenger') => void;
  wsConnected: boolean;
  simTime: string;
}

export const Header: React.FC<HeaderProps> = ({
  activeView,
  onViewChange,
  wsConnected,
  simTime,
}) => {
  const formattedSimTime = simTime
    ? new Date(simTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : '--:--:--';

  return (
    <header className="app-header">
      <div className="header-left">
        <div className="logo-container">
          <span className="logo-icon">🚆</span>
          <div>
            <h1 className="app-title">SIH26028 Dynamic Train ETA</h1>
            <p className="app-subtitle">Northern – NCR – ECR Corridor (NDLS ↔ MKA)</p>
          </div>
        </div>
        <span className="badge badge-warning simulated-badge">
          ⚠️ SIMULATED DATA
        </span>
      </div>

      <div className="header-center">
        <nav className="view-toggle">
          <button
            className={`toggle-btn ${activeView === 'control' ? 'active' : ''}`}
            onClick={() => onViewChange('control')}
          >
            🏢 Control-Room View
          </button>
          <button
            className={`toggle-btn ${activeView === 'passenger' ? 'active' : ''}`}
            onClick={() => onViewChange('passenger')}
          >
            👥 Passenger View
          </button>
        </nav>
      </div>

      <div className="header-right">
        <div className="sim-clock-card">
          <span className="clock-label">Corridor Clock</span>
          <span className="clock-time">{formattedSimTime}</span>
        </div>

        <div className="status-indicator">
          <span className={`status-dot ${wsConnected ? 'connected' : 'polling'}`} />
          <span className="status-text">
            {wsConnected ? 'Live WebSocket' : 'REST Polling'}
          </span>
        </div>
      </div>
    </header>
  );
};
