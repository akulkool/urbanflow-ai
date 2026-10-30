import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Map,
  BrainCircuit,
  AlertTriangle,
  Route,
  FlaskConical,
  BarChart3,
  GitCompareArrows,
  ChevronLeft,
  ChevronRight,
  Activity,
} from 'lucide-react';

/**
 * Navigation items for the sidebar.
 * Each entry maps to a page route.
 */
const NAV_ITEMS = [
  {
    section: 'Main',
    links: [
      { to: '/',               label: 'Overview',             icon: LayoutDashboard },
      { to: '/map',            label: 'Interactive Map',      icon: Map },
    ],
  },
  {
    section: 'Traffic Intelligence',
    links: [
      { to: '/monitoring',     label: 'AI Traffic Monitoring', icon: BrainCircuit },
      { to: '/incidents',      label: 'Incident Management',   icon: AlertTriangle },
      { to: '/routing',        label: 'Smart Routing',         icon: Route },
    ],
  },
  {
    section: 'Analysis',
    links: [
      { to: '/simulator',      label: 'What-If Simulator',     icon: FlaskConical },
      { to: '/analytics',      label: 'Analytics Dashboard',   icon: BarChart3 },
      { to: '/comparison',     label: 'Scenario Comparison',   icon: GitCompareArrows },
    ],
  },
];

/**
 * Sidebar navigation component.
 *
 * @param {object}   props
 * @param {boolean}  props.collapsed      Whether the sidebar is collapsed.
 * @param {function} props.onToggle       Callback to toggle collapsed state.
 * @param {function} props.onMobileClose  Callback to close sidebar on mobile after nav.
 */
function Sidebar({ collapsed, onToggle, onMobileClose, className = '' }) {
  const handleNavClick = () => {
    /* On mobile, close sidebar when a link is tapped */
    if (window.innerWidth <= 1024 && onMobileClose) {
      onMobileClose();
    }
  };

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''} ${className}`.trim()}>
      {/* Brand */}
      <div className="sidebar__brand">
        <div className="sidebar__logo">
          <Activity size={18} className="sidebar__logo-icon" />
        </div>
        <div className="sidebar__title">
          Urban<span>Flow</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar__nav">
        {NAV_ITEMS.map((section) => (
          <div key={section.section}>
            <div className="sidebar__section-label">{section.section}</div>
            {section.links.map((link) => {
              const Icon = link.icon;
              return (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.to === '/'}
                  onClick={handleNavClick}
                  className={({ isActive }) =>
                    `sidebar__link ${isActive ? 'sidebar__link--active' : ''}`
                  }
                >
                  <Icon size={20} className="sidebar__link-icon" />
                  <span className="sidebar__link-label">{link.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Collapse toggle */}
      <div className="sidebar__footer">
        <button
          className="sidebar__toggle"
          onClick={onToggle}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
