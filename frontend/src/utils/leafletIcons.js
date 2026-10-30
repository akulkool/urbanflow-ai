import L from 'leaflet';

/**
 * Custom SVG-based DivIcons for Leaflet.
 * This completely avoids the Vite asset-path bug with Leaflet default png icons.
 */

// Junction marker
export const createJunctionIcon = (name, isSelected = false) => {
  return L.divIcon({
    className: 'custom-leaflet-marker',
    html: `
      <div style="
        width: 14px;
        height: 14px;
        background-color: ${isSelected ? '#00d4ff' : '#38bdf8'};
        border: 2px solid #060a13;
        border-radius: 50%;
        box-shadow: 0 0 8px ${isSelected ? '#00d4ff' : 'rgba(56, 189, 248, 0.6)'};
      "></div>
    `,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
    popupAnchor: [0, -10],
  });
};

// Hospital marker
export const createHospitalIcon = () => {
  return L.divIcon({
    className: 'custom-leaflet-marker',
    html: `
      <div style="
        width: 26px;
        height: 26px;
        background: #ef4444;
        border: 2px solid #ffffff;
        border-radius: 6px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 900;
        font-size: 14px;
        box-shadow: 0 2px 8px rgba(239, 68, 68, 0.7);
        line-height: 1;
      ">
        +
      </div>
    `,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -15],
  });
};

// Incident marker with severity styling
export const createIncidentIcon = (severity = 'high') => {
  const colors = {
    critical: { bg: '#ef4444', border: '#fee2e2', shadow: 'rgba(239, 68, 68, 0.9)' },
    high: { bg: '#f97316', border: '#ffedd5', shadow: 'rgba(249, 115, 22, 0.8)' },
    medium: { bg: '#f59e0b', border: '#fef3c7', shadow: 'rgba(245, 158, 11, 0.7)' },
    low: { bg: '#3b82f6', border: '#dbeafe', shadow: 'rgba(59, 130, 246, 0.6)' },
  };

  const style = colors[severity.toLowerCase()] || colors.high;

  return L.divIcon({
    className: 'custom-leaflet-marker',
    html: `
      <div style="
        width: 28px;
        height: 28px;
        background: ${style.bg};
        border: 2px solid ${style.border};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #ffffff;
        font-size: 13px;
        box-shadow: 0 0 12px ${style.shadow};
        animation: pulse-marker 2s infinite ease-in-out;
      ">
        ⚠️
      </div>
    `,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16],
  });
};

