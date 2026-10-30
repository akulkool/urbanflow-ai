import { useState, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar, Header } from '../components';
import { useConnection } from '../context';

/**
 * Map route pathnames to page titles for the header.
 */
const PAGE_TITLES = {
  '/':            'Overview',
  '/map':         'Interactive Map',
  '/monitoring':  'AI Traffic Monitoring',
  '/incidents':   'Incident Management',
  '/routing':     'Smart Routing',
  '/simulator':   'What-If Simulator',
  '/analytics':   'Analytics Dashboard',
  '/comparison':  'Scenario Comparison',
};

/**
 * Main application layout.
 * Renders the sidebar, header, and a content area populated via <Outlet />.
 */
function MainLayout() {
  const location = useLocation();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pageTitle = PAGE_TITLES[location.pathname] || 'UrbanFlow AI';

  const handleToggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => !prev);
  }, []);

  const handleMobileOpen = useCallback(() => {
    setMobileOpen(true);
  }, []);

  const handleMobileClose = useCallback(() => {
    setMobileOpen(false);
  }, []);

  const { isConnected } = useConnection();

  return (
    <div
      className={`layout ${sidebarCollapsed ? 'layout--sidebar-collapsed' : ''}`}
    >
      {/* Mobile overlay */}
      <div
        className={`sidebar__overlay ${mobileOpen ? 'sidebar__overlay--visible' : ''}`}
        onClick={handleMobileClose}
      />

      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={handleToggleSidebar}
        onMobileClose={handleMobileClose}
        className={mobileOpen ? 'sidebar--mobile-open' : ''}
      />

      {/* Header */}
      <Header
        pageTitle={pageTitle}
        isConnected={isConnected}
        onMenuClick={handleMobileOpen}
      />

      {/* Page content */}
      <main className="layout__content">
        <Outlet />
      </main>
    </div>
  );
}

export default MainLayout;

