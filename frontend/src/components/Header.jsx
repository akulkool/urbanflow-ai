import { Bell, Menu, Settings } from 'lucide-react';

/**
 * Top header bar with page title, connection status, and user controls.
 *
 * @param {object}   props
 * @param {string}   props.pageTitle       Title of the current page.
 * @param {boolean}  props.isConnected     Backend connection status (null = unknown).
 * @param {function} props.onMenuClick     Callback to toggle mobile sidebar.
 */
function Header({ pageTitle, isConnected = null, onMenuClick }) {
  /* Derive status label */
  let statusLabel = 'Checking…';
  let dotClass = '';
  if (isConnected === true) {
    statusLabel = 'API Connected';
    dotClass = 'header__status-dot--connected';
  } else if (isConnected === false) {
    statusLabel = 'Disconnected';
    dotClass = 'header__status-dot--disconnected';
  }

  return (
    <header className="header">
      {/* Left side */}
      <div className="header__left">
        <button
          className="header__menu-btn"
          onClick={onMenuClick}
          aria-label="Toggle navigation"
        >
          <Menu size={20} />
        </button>
        <h1 className="header__page-title">{pageTitle}</h1>
      </div>

      {/* Right side */}
      <div className="header__right">
        {/* Connection status */}
        <div className="header__status">
          <span className={`header__status-dot ${dotClass}`} />
          <span>{statusLabel}</span>
        </div>

        {/* Notification bell */}
        <button className="header__icon-btn" aria-label="Notifications">
          <Bell size={19} />
          {/* Placeholder dot — will be driven by real notification state */}
        </button>

        {/* Settings */}
        <button className="header__icon-btn" aria-label="Settings">
          <Settings size={19} />
        </button>

        {/* Avatar */}
        <div className="header__avatar" title="User">
          UF
        </div>
      </div>
    </header>
  );
}

export default Header;

