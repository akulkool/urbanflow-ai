import { Routes, Route } from 'react-router-dom';
import { ConnectionProvider } from './context';
import { MainLayout } from './layouts';
import {
  OverviewPage,
  InteractiveMapPage,
  AITrafficMonitoringPage,
  IncidentManagementPage,
  SmartRoutingPage,
  WhatIfSimulatorPage,
  AnalyticsDashboardPage,
  ScenarioComparisonPage,
} from './pages';

/**
 * Root application component.
 * All module routes are nested inside the MainLayout.
 */
function App() {
  return (
    <ConnectionProvider>
      <Routes>
        <Route element={<MainLayout />}>
          <Route index              element={<OverviewPage />} />
          <Route path="map"         element={<InteractiveMapPage />} />
          <Route path="monitoring"  element={<AITrafficMonitoringPage />} />
          <Route path="incidents"   element={<IncidentManagementPage />} />
          <Route path="routing"     element={<SmartRoutingPage />} />
          <Route path="simulator"   element={<WhatIfSimulatorPage />} />
          <Route path="analytics"   element={<AnalyticsDashboardPage />} />
          <Route path="comparison"  element={<ScenarioComparisonPage />} />
        </Route>
      </Routes>
    </ConnectionProvider>
  );
}

export default App;
