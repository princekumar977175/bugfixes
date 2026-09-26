import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import { DisruptionItem, StationItem, TrainListItem } from '../types';

interface ControlRoomMapProps {
  stations: StationItem[];
  trains: TrainListItem[];
  disruptions: DisruptionItem[];
  selectedTrainId: string | null;
  onSelectTrain: (runId: string) => void;
  simTime?: string;
}

interface TrainMarkerAnimState {
  marker: L.Marker;
  fromPos: [number, number];
  targetPos: [number, number];
  startTime: number;
  duration: number;
  trainNumber: string;
  delay: number;
  isSelected: boolean;
}

function createTrainIcon(trainNum: string, delay: number, color: string, selected: boolean): L.DivIcon {
  return L.divIcon({
    className: 'train-icon-container',
    html: `
      <div class="train-map-marker ${selected ? 'selected' : ''}" style="border-color: ${color}">
        <span class="train-number">${trainNum}</span>
        <span class="train-delay-pill" style="background-color: ${color}">
          ${delay > 0 ? `+${Math.round(delay)}m` : 'RT'}
        </span>
      </div>
    `,
    iconSize: [52, 28],
    iconAnchor: [26, 14],
  });
}

function getTooltipHtml(t: TrainListItem): string {
  const delay = t.current_delay_min;
  return `<b>${t.train_name} (${t.train_number})</b><br/>
     Route: ${t.source} → ${t.destination}<br/>
     Current: ${t.current_station || '-'} ${t.next_station ? `→ Next: ${t.next_station}` : ''}<br/>
     Delay: <b>+${delay.toFixed(1)} min</b><br/>
     Knock-on Risk: <span class="risk-badge risk-${t.knock_on_risk}">${t.knock_on_risk.toUpperCase()}</span>`;
}

function interpolateAlongCorridor(
  stations: StationItem[],
  fromCode: string,
  toCode: string,
  progress: number
): [number, number] | null {
  if (stations.length === 0) return null;
  const fromIdx = stations.findIndex((s) => s.code === fromCode);
  const toIdx = stations.findIndex((s) => s.code === toCode);
  if (fromIdx === -1 && toIdx === -1) return null;
  if (fromIdx === -1) return [stations[toIdx].lat, stations[toIdx].lon];
  if (toIdx === -1) return [stations[fromIdx].lat, stations[fromIdx].lon];
  if (fromIdx === toIdx) return [stations[fromIdx].lat, stations[fromIdx].lon];

  // Calculate cumulative distances along the station path
  const cumDist: number[] = [0];
  for (let i = 0; i < stations.length - 1; i++) {
    const d = Math.hypot(stations[i + 1].lat - stations[i].lat, stations[i + 1].lon - stations[i].lon);
    cumDist.push(cumDist[i] + d);
  }

  const p = Math.max(0, Math.min(1, progress));
  const startD = cumDist[fromIdx];
  const endD = cumDist[toIdx];
  const targetD = startD + p * (endD - startD);

  for (let i = 0; i < stations.length - 1; i++) {
    const minD = Math.min(cumDist[i], cumDist[i + 1]);
    const maxD = Math.max(cumDist[i], cumDist[i + 1]);
    if (minD <= targetD && targetD <= maxD) {
      const segLen = cumDist[i + 1] - cumDist[i];
      const u = segLen > 0 ? (targetD - cumDist[i]) / segLen : 0;
      const lat = stations[i].lat + u * (stations[i + 1].lat - stations[i].lat);
      const lon = stations[i].lon + u * (stations[i + 1].lon - stations[i].lon);
      return [lat, lon];
    }
  }

  return [stations[toIdx].lat, stations[toIdx].lon];
}

export const ControlRoomMap: React.FC<ControlRoomMapProps> = ({
  stations,
  trains,
  disruptions,
  selectedTrainId,
  onSelectTrain,
  simTime,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const baseLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const trainsLayerGroupRef = useRef<L.LayerGroup | null>(null);
  const trainMarkersRef = useRef<Map<string, TrainMarkerAnimState>>(new Map());

  // Stable callback reference
  const onSelectTrainRef = useRef(onSelectTrain);
  useEffect(() => {
    onSelectTrainRef.current = onSelectTrain;
  }, [onSelectTrain]);

  // Initialize Leaflet map and layer groups
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    // Centered along Kanpur/Prayagraj corridor
    const map = L.map(mapContainerRef.current, {
      center: [26.5, 81.5],
      zoom: 7,
      minZoom: 6,
      maxZoom: 14,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map);

    const baseLayerGroup = L.layerGroup().addTo(map);
    const trainsLayerGroup = L.layerGroup().addTo(map);

    mapInstanceRef.current = map;
    baseLayerGroupRef.current = baseLayerGroup;
    trainsLayerGroupRef.current = trainsLayerGroup;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
      baseLayerGroupRef.current = null;
      trainsLayerGroupRef.current = null;
      trainMarkersRef.current.clear();
    };
  }, []);

  // 60 FPS requestAnimationFrame loop for continuous, smooth marker interpolation
  useEffect(() => {
    let animFrameId: number;

    const animate = (timestamp: number) => {
      trainMarkersRef.current.forEach((anim) => {
        const { marker, fromPos, targetPos, startTime, duration } = anim;
        const elapsed = timestamp - startTime;
        const t = duration > 0 ? Math.min(1.0, Math.max(0.0, elapsed / duration)) : 1.0;

        // Steady linear interpolation between waypoint updates
        const lat = fromPos[0] + (targetPos[0] - fromPos[0]) * t;
        const lon = fromPos[1] + (targetPos[1] - fromPos[1]) * t;

        marker.setLatLng([lat, lon]);
      });

      animFrameId = requestAnimationFrame(animate);
    };

    animFrameId = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(animFrameId);
    };
  }, []);

  // Render tracks, stations, and disruptions on baseLayerGroup
  useEffect(() => {
    const baseGroup = baseLayerGroupRef.current;
    if (!baseGroup || stations.length === 0) return;

    baseGroup.clearLayers();

    // Filter disruptions active at simTime
    const simTimeMs = simTime ? new Date(simTime).getTime() : null;
    const activeDisruptions = disruptions.filter((d) => {
      if (!simTimeMs) return true;
      const start = new Date(d.start_time).getTime();
      const end = new Date(d.end_time).getTime();
      return start <= simTimeMs && end >= simTimeMs;
    });

    // Map stations by code for quick lookup
    const stationLookup = new Map<string, StationItem>();
    stations.forEach((st) => stationLookup.set(st.code, st));

    // 1. Draw track sections with delay heatmap coloring
    for (let i = 0; i < stations.length - 1; i++) {
      const st1 = stations[i];
      const st2 = stations[i + 1];
      const secIdDn = `${st1.code}-${st2.code}-DN`;
      const secIdUp = `${st2.code}-${st1.code}-UP`;

      // Check if any disruption or train delay affects this section
      const secDisruptions = activeDisruptions.filter(
        (d) => d.section_id === secIdDn || d.section_id === secIdUp
      );

      const sectionTrains = trains.filter(
        (t) =>
          (t.current_station === st1.code && t.next_station === st2.code) ||
          (t.current_station === st2.code && t.next_station === st1.code)
      );

      const maxDelay = sectionTrains.reduce((max, t) => Math.max(max, t.current_delay_min), 0);

      let trackColor = '#10b981'; // Green (On-time)
      let trackWeight = 4;
      let opacity = 0.8;

      if (secDisruptions.length > 0 || maxDelay >= 25) {
        trackColor = '#ef4444'; // Red (Severe delay / disruption)
        trackWeight = 6;
      } else if (maxDelay >= 10 || secDisruptions.some((d) => d.type === 'TSR')) {
        trackColor = '#f59e0b'; // Amber (Moderate delay)
        trackWeight = 5;
      }

      const polyline = L.polyline(
        [
          [st1.lat, st1.lon],
          [st2.lat, st2.lon],
        ],
        {
          color: trackColor,
          weight: trackWeight,
          opacity: opacity,
        }
      );

      polyline.bindTooltip(
        `<b>Section:</b> ${st1.name} ↔ ${st2.name}<br/>
         <b>Status:</b> ${secDisruptions.length ? `${secDisruptions[0].type} active` : 'Normal flow'}<br/>
         <b>Active Trains:</b> ${sectionTrains.length}`,
        { sticky: true }
      );

      baseGroup.addLayer(polyline);
    }

    // 2. Draw Stations
    stations.forEach((st) => {
      const isJunction = st.is_junction;
      const marker = L.circleMarker([st.lat, st.lon], {
        radius: isJunction ? 7 : 4,
        fillColor: isJunction ? '#38bdf8' : '#94a3b8',
        color: '#ffffff',
        weight: 1.5,
        fillOpacity: 0.9,
      });

      marker.bindTooltip(
        `<b>${st.name} (${st.code})</b><br/>Zone: ${st.zone}${isJunction ? ' (Major Junction)' : ''}`,
        { permanent: isJunction, direction: 'top', className: 'station-map-label' }
      );

      baseGroup.addLayer(marker);
    });

    // 3. Draw Disruption markers (only active at simTime)
    activeDisruptions.forEach((d) => {
      const parts = d.section_id.split('-');
      if (parts.length >= 2) {
        const fromSt = stationLookup.get(parts[0]);
        const toSt = stationLookup.get(parts[1]);
        if (fromSt && toSt) {
          const midLat = (fromSt.lat + toSt.lat) / 2;
          const midLon = (fromSt.lon + toSt.lon) / 2;

          const disruptionIcon = L.divIcon({
            className: 'disruption-icon-wrapper',
            html: `<div class="disruption-map-badge">${
              d.type === 'TSR' ? '⚠️' : d.type === 'congestion' ? '🛑' : '🌫️'
            }</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
          });

          const marker = L.marker([midLat, midLon], { icon: disruptionIcon });
          marker.bindTooltip(
            `<b>⚠️ ${d.type.toUpperCase()} Disruption</b><br/>
             Section: ${d.section_id}<br/>
             Severity: ${(d.severity * 100).toFixed(0)}% speed reduction`,
            { direction: 'right' }
          );
          baseGroup.addLayer(marker);
        }
      }
    });
  }, [stations, disruptions, trains, simTime]);

  // Train Markers management and animation target updates on trainsLayerGroup
  useEffect(() => {
    const trainsGroup = trainsLayerGroupRef.current;
    if (!trainsGroup || stations.length === 0) return;

    const stationLookup = new Map<string, StationItem>();
    stations.forEach((st) => stationLookup.set(st.code, st));

    const now = performance.now();
    const activeRunIds = new Set<string>();

    trains.forEach((t) => {
      activeRunIds.add(t.run_id);

      // Determine precise target coordinates
      let targetLat: number | null = null;
      let targetLon: number | null = null;

      if (typeof t.current_lat === 'number' && typeof t.current_lon === 'number') {
        targetLat = t.current_lat;
        targetLon = t.current_lon;
      } else {
        const curSt = stationLookup.get(t.current_station || '');
        const nextSt = stationLookup.get(t.next_station || '');

        if (curSt && nextSt && t.status === 'running') {
          const p = typeof t.progress === 'number' ? t.progress : 0.35;
          const pos = interpolateAlongCorridor(stations, curSt.code, nextSt.code, p);
          if (pos) {
            targetLat = pos[0];
            targetLon = pos[1];
          } else {
            targetLat = curSt.lat;
            targetLon = curSt.lon;
          }
        } else if (curSt) {
          targetLat = curSt.lat;
          targetLon = curSt.lon;
        }
      }

      if (targetLat === null || targetLon === null) return;

      const isSelected = selectedTrainId === t.run_id;
      const delay = t.current_delay_min;
      const delayColor = delay > 20 ? '#ef4444' : delay > 8 ? '#f59e0b' : '#10b981';

      if (trainMarkersRef.current.has(t.run_id)) {
        // Marker already exists: smoothly glide from its current live position to the new target
        const anim = trainMarkersRef.current.get(t.run_id)!;
        const liveLatLng = anim.marker.getLatLng();
        const livePos: [number, number] = [liveLatLng.lat, liveLatLng.lng];

        // If large jump (e.g. date scrub or reset), snap immediately without gliding
        const dist = Math.hypot(targetLat - livePos[0], targetLon - livePos[1]);
        if (dist > 0.5) {
          anim.fromPos = [targetLat, targetLon];
          anim.marker.setLatLng([targetLat, targetLon]);
        } else {
          anim.fromPos = livePos;
        }

        anim.targetPos = [targetLat, targetLon];
        anim.startTime = now;
        anim.duration = 1000; // 1.0s window matching steady backend push cadence

        // Update icon and z-index if delay or selection changed
        if (anim.delay !== delay || anim.isSelected !== isSelected) {
          anim.marker.setIcon(createTrainIcon(t.train_number, delay, delayColor, isSelected));
          anim.marker.setZIndexOffset(isSelected ? 1000 : 500);
          anim.delay = delay;
          anim.isSelected = isSelected;
        }

        // Update tooltip content
        anim.marker.setTooltipContent(getTooltipHtml(t));
      } else {
        // New train marker: create, register, and add to map
        const marker = L.marker([targetLat, targetLon], {
          icon: createTrainIcon(t.train_number, delay, delayColor, isSelected),
          zIndexOffset: isSelected ? 1000 : 500,
        });

        marker.on('click', () => {
          onSelectTrainRef.current(t.run_id);
        });

        marker.bindTooltip(getTooltipHtml(t), { direction: 'top' });
        trainsGroup.addLayer(marker);

        trainMarkersRef.current.set(t.run_id, {
          marker,
          fromPos: [targetLat, targetLon],
          targetPos: [targetLat, targetLon],
          startTime: now,
          duration: 1000,
          trainNumber: t.train_number,
          delay,
          isSelected,
        });
      }
    });

    // Clean up markers for trains no longer in the active list
    trainMarkersRef.current.forEach((anim, runId) => {
      if (!activeRunIds.has(runId)) {
        trainsGroup.removeLayer(anim.marker);
        trainMarkersRef.current.delete(runId);
      }
    });
  }, [trains, stations, selectedTrainId]);

  return (
    <div className="map-wrapper">
      <div className="map-legend">
        <div className="legend-item"><span className="legend-dot green"></span> On-Time / Free Flow</div>
        <div className="legend-item"><span className="legend-dot amber"></span> Moderate Delay (5-20m)</div>
        <div className="legend-item"><span className="legend-dot red"></span> High Delay / Disruption</div>
        <div className="legend-item"><span className="legend-dot blue"></span> Junction</div>
      </div>
      <div ref={mapContainerRef} className="leaflet-map-element" />
    </div>
  );
};
