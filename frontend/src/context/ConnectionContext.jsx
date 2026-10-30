import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import healthService from '../services/healthService';

const ConnectionContext = createContext(null);

export function ConnectionProvider({ children }) {
  const [isConnected, setIsConnected] = useState(null); // null = checking, true = live, false = disconnected
  const [lastChecked, setLastChecked] = useState(null);
  const [isDemoMode, setIsDemoMode] = useState(true); // Default to true when backend is offline so demo works smoothly

  const checkConnection = useCallback(async () => {
    const result = await healthService.check();
    setIsConnected(result.isConnected);
    setLastChecked(new Date());
    if (result.isConnected) {
      setIsDemoMode(false);
    }
    return result;
  }, []);

  useEffect(() => {
    checkConnection();
    // Poll backend connection every 30 seconds
    const interval = setInterval(checkConnection, 30000);
    return () => clearInterval(interval);
  }, [checkConnection]);

  return (
    <ConnectionContext.Provider
      value={{
        isConnected,
        lastChecked,
        isDemoMode,
        setIsDemoMode,
        checkConnection,
      }}
    >
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection() {
  const context = useContext(ConnectionContext);
  if (!context) {
    throw new Error('useConnection must be used within a ConnectionProvider');
  }
  return context;
}

