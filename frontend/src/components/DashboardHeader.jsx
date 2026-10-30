import { RefreshCw, Radio, AlertCircle, Wifi, WifiOff } from 'lucide-react';

/**
 * Dashboard Header component with title, subtitle, refresh button,
 * last updated timestamp, and backend connection status.
 */
function DashboardHeader({
  title = 'Traffic Intelligence Overview',
  subtitle = 'Real-time traffic monitoring and urban mobility insights.',
  lastUpdated,
  isRefreshing,
  onRefresh,
  isConnected,
  isDemoMode,
  onRetryConnection,
}) {
  const formattedTime = lastUpdated
    ? new Intl.DateTimeFormat('en-US', {
        hour: 'numeric',
        minute: 'numeric',
        second: 'numeric',
        hour12: true,
      }).format(lastUpdated)
    : 'Just now';

  return (
    <div className="dashboard-header-container">
      <div className="dashboard-header">
        <div className="dashboard-header__info">
          <div className="dashboard-header__title-row">
            <h1 className="dashboard-header__title">{title}</h1>
            <div className="dashboard-header__badge-wrap">
              {isConnected ? (
                <span className="live-status-pill live-status-pill--active">
                  <Radio size={13} className="live-status-pill__icon" />
                  Live API Telemetry
                </span>
              ) : (
                <span className="live-status-pill live-status-pill--demo">
                  <span className="status-dot status-dot--demo" />
                  Bengaluru Simulated Network
                </span>
              )}
            </div>
          </div>
          <p className="dashboard-header__subtitle">{subtitle}</p>
        </div>

        <div className="dashboard-header__actions">
          <div className="dashboard-header__timestamp">
            <span className="timestamp-label">Updated:</span>
            <span className="timestamp-value">{formattedTime}</span>
          </div>

          <button
            className={`dashboard-btn dashboard-btn--refresh ${isRefreshing ? 'dashboard-btn--spinning' : ''}`}
            onClick={onRefresh}
            disabled={isRefreshing}
            title="Refresh traffic intelligence metrics"
          >
            <RefreshCw size={15} />
            <span>{isRefreshing ? 'Refreshing…' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {!isConnected && (
        <div className="demo-notice-banner">
          <div className="demo-notice-banner__left">
            <AlertCircle size={18} className="demo-notice-banner__icon" />
            <div className="demo-notice-banner__content">
              <strong>Demonstration Mode Active:</strong> Live backend API is unreachable at{' '}
              <code>http://localhost:8000/api</code>. Displaying calibrated Bengaluru-inspired simulated
              traffic telemetry. Real API integration endpoints are active and ready.
            </div>
          </div>
          {onRetryConnection && (
            <button className="demo-notice-banner__btn" onClick={onRetryConnection}>
              <Wifi size={14} />
              Probe Backend
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default DashboardHeader;

