import { BENGALURU_ROADS, BENGALURU_JUNCTIONS, BENGALURU_HOSPITALS, BENGALURU_INCIDENTS } from './mockTrafficData';

/**
 * Client-Side Graph Routing Engine (Dijkstra Implementation)
 * 
 * Used for emergency route optimization and what-if simulation
 * when the backend NetworkX routing service is offline.
 */

// Build an adjacency list from the road network
function buildAdjacencyList(roads, options = {}) {
  const {
    closedRoadId = null,
    avoidIncidents = true,
    activeIncidents = BENGALURU_INCIDENTS,
    roadStatusOverrides = {},
  } = options;

  const adj = {};
  BENGALURU_JUNCTIONS.forEach((j) => {
    adj[j.id] = [];
  });

  roads.forEach((road) => {
    // Check if road is explicitly blocked
    const overrideStatus = roadStatusOverrides[road.id];
    const currentStatus = overrideStatus || road.status;

    if (road.id === closedRoadId || currentStatus === 'closed') {
      return; // Edge is closed, do not add to graph
    }

    // Check if incident is active on road
    const hasActiveIncident =
      avoidIncidents &&
      activeIncidents.some(
        (inc) =>
          inc.roadId === road.id &&
          (inc.status === 'active' || inc.status === 'investigating') &&
          (inc.severity === 'critical' || inc.severity === 'high')
      );

    if (hasActiveIncident) {
      return; // Avoid critical/high incident roads
    }

    // Calculate traversal weight
    let weight = road.distanceKm;
    if (currentStatus === 'congested') {
      weight *= 2.5; // Congestion penalty
    }

    // Add bidirectional edge
    if (adj[road.startJunctionId] && adj[road.endJunctionId]) {
      adj[road.startJunctionId].push({
        to: road.endJunctionId,
        road,
        weight,
        distanceKm: road.distanceKm,
      });
      adj[road.endJunctionId].push({
        to: road.startJunctionId,
        road,
        weight,
        distanceKm: road.distanceKm,
      });
    }
  });

  return adj;
}

/**
 * Run Dijkstra algorithm on adjacency list
 */
function dijkstra(adj, startNode, endNode, penalizedRoadIds = []) {
  const distances = {};
  const prev = {};
  const prevRoad = {};
  const visited = new Set();
  const queue = new Set(Object.keys(adj));

  Object.keys(adj).forEach((node) => {
    distances[node] = Infinity;
    prev[node] = null;
    prevRoad[node] = null;
  });

  distances[startNode] = 0;

  while (queue.size > 0) {
    // Find node with minimum distance
    let minNode = null;
    let minDistance = Infinity;

    queue.forEach((node) => {
      if (distances[node] < minDistance) {
        minDistance = distances[node];
        minNode = node;
      }
    });

    if (minNode === null || minDistance === Infinity) {
      break;
    }

    if (minNode === endNode) {
      break;
    }

    queue.delete(minNode);
    visited.add(minNode);

    const neighbors = adj[minNode] || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor.to)) {
        let edgeWeight = neighbor.weight;
        // Apply penalty if this edge is in the penalized list (for computing alternative routes)
        if (penalizedRoadIds.includes(neighbor.road.id)) {
          edgeWeight *= 4.0;
        }

        const alt = distances[minNode] + edgeWeight;
        if (alt < distances[neighbor.to]) {
          distances[neighbor.to] = alt;
          prev[neighbor.to] = minNode;
          prevRoad[neighbor.to] = neighbor.road;
        }
      }
    }
  }

  // Reconstruct path
  if (distances[endNode] === Infinity) {
    return null; // No path found
  }

  const path = [];
  const roadSegments = [];
  let curr = endNode;

  while (curr) {
    path.unshift(curr);
    if (prevRoad[curr]) {
      roadSegments.unshift(prevRoad[curr]);
    }
    curr = prev[curr];
  }

  return {
    path,
    roadSegments,
    modeledCost: distances[endNode],
  };
}

/**
 * Calculate optimal smart route between junctions or to a hospital
 */
export function calculateSmartRoute({
  originJunctionId,
  destinationJunctionId,
  hospitalId = null,
  avoidIncidents = true,
  transportMode = 'emergency',
  activeIncidents = BENGALURU_INCIDENTS,
  closedRoadId = null,
  roadStatusOverrides = {},
}) {
  const startTime = performance.now();

  // Validate inputs
  if (!originJunctionId) {
    return {
      success: false,
      error: 'Please select a valid origin junction.',
    };
  }

  // If hospital destination is chosen, resolve target junction
  let targetJunctionId = destinationJunctionId;
  let targetHospital = null;

  if (hospitalId) {
    targetHospital = BENGALURU_HOSPITALS.find((h) => h.id === hospitalId);
    if (targetHospital) {
      targetJunctionId = targetHospital.nearestJunctionId;
    }
  }

  if (!targetJunctionId) {
    return {
      success: false,
      error: 'Please select a destination junction or emergency hospital.',
    };
  }

  if (originJunctionId === targetJunctionId) {
    return {
      success: false,
      error: 'Origin and destination junctions cannot be identical. Please select different nodes.',
    };
  }

  const adj = buildAdjacencyList(BENGALURU_ROADS, {
    closedRoadId,
    avoidIncidents,
    activeIncidents,
    roadStatusOverrides,
  });

  // Calculate Primary Route
  const primaryResult = dijkstra(adj, originJunctionId, targetJunctionId);

  if (!primaryResult || primaryResult.roadSegments.length === 0) {
    return {
      success: false,
      error: 'No non-obstructed route could be computed between the selected locations. Critical arterial roads may be closed.',
    };
  }

  // Calculate Alternative Route (penalizing primary road segments)
  const primaryRoadIds = primaryResult.roadSegments.map((r) => r.id);
  const altResult = dijkstra(adj, originJunctionId, targetJunctionId, primaryRoadIds);

  const endTime = performance.now();
  const computationTimeMs = (endTime - startTime).toFixed(1);

  // Helper to compile route details
  const formatRoute = (result, isAlt = false) => {
    const totalDistanceKm = result.roadSegments.reduce((sum, r) => sum + r.distanceKm, 0);
    // Estimated time based on speed or transport mode
    const speedMultiplier = transportMode === 'emergency' ? 1.25 : 1.0;
    const avgSpeed = (totalDistanceKm / result.roadSegments.length) * 8 * speedMultiplier;
    const effectiveSpeed = Math.max(22, Math.min(65, avgSpeed));
    const estimatedTimeMinutes = ((totalDistanceKm / effectiveSpeed) * 60).toFixed(1);

    // Aggregate coordinates for polyline rendering
    const coordinates = [];
    result.roadSegments.forEach((road, i) => {
      if (i === 0) {
        coordinates.push(...road.coordinates);
      } else {
        coordinates.push(...road.coordinates.slice(1));
      }
    });

    return {
      path: result.path,
      roadSegments: result.roadSegments,
      totalDistanceKm: Number(totalDistanceKm.toFixed(1)),
      estimatedTimeMinutes: Number(estimatedTimeMinutes),
      modeledCost: Number(result.modeledCost.toFixed(2)),
      coordinates,
      isAlternative: isAlt,
    };
  };

  const primary = formatRoute(primaryResult, false);
  const alternative = altResult && altResult.roadSegments.length > 0 ? formatRoute(altResult, true) : null;

  // Origin and destination objects
  const originJunction = BENGALURU_JUNCTIONS.find((j) => j.id === originJunctionId);
  const destinationJunction = BENGALURU_JUNCTIONS.find((j) => j.id === targetJunctionId);

  // Generate automated explanation
  let explanation = `Optimal ${transportMode} route synthesized from ${originJunction?.name || originJunctionId} to ${
    targetHospital ? targetHospital.name : destinationJunction?.name || targetJunctionId
  } spanning ${primary.totalDistanceKm} km across ${primary.roadSegments.length} road corridors.`;

  if (avoidIncidents) {
    explanation += ' Routing algorithm successfully bypassed active critical bottlenecks on the network.';
  }

  return {
    success: true,
    originJunction,
    destinationJunction,
    targetHospital,
    primaryRoute: primary,
    alternativeRoute: alternative,
    computationTimeMs,
    validity: 'Certified Non-Obstructed',
    explanation,
  };
}

