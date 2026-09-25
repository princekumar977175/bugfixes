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
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  // Initialize Leaflet map
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    // Centered along Kanpur/Prayagraj corridor
    const map = L.map(mapContainerRef.current, {
      center: [26.5, 81.5],
      zoom: 7,
      minZoom: 6,
      maxZoom: 14,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(map);

    const layerGroup = L.layerGroup().addTo(map);
    mapInstanceRef.current = map;
    layerGroupRef.current = layerGroup;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Render tracks, stations, disruptions, and trains
  useEffect(() => {
    const map = mapInstanceRef.current;
    const layerGroup = layerGroupRef.current;
    if (!map || !layerGroup || stations.length === 0) return;

    layerGroup.clearLayers();

    // Filter disruptions that are active at simTime (or all if simTime not specified)
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

      layerGroup.addLayer(polyline);
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

      layerGroup.addLayer(marker);
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
          layerGroup.addLayer(marker);
        }
      }
    });

    // 4. Draw Train Markers
    trains.forEach((t) => {
      const curSt = stationLookup.get(t.current_station || '');
      if (!curSt) return;

      const nextSt = stationLookup.get(t.next_station || '');
      let markerLat = curSt.lat;
      let markerLon = curSt.lon;

      if (nextSt && t.status === 'running') {
        markerLat = curSt.lat * 0.65 + nextSt.lat * 0.35;
        markerLon = curSt.lon * 0.65 + nextSt.lon * 0.35;
      }

      const isSelected = selectedTrainId === t.run_id;
      const delay = t.current_delay_min;
      const delayColor = delay > 20 ? '#ef4444' : delay > 8 ? '#f59e0b' : '#10b981';

      // Train marker HTML
      const trainIcon = L.divIcon({
        className: 'train-icon-container',
        html: `
          <div class="train-map-marker ${isSelected ? 'selected' : ''}" style="border-color: ${delayColor}">
            <span class="train-number">${t.train_number}</span>
            <span class="train-delay-pill" style="background-color: ${delayColor}">
              ${delay > 0 ? `+${Math.round(delay)}m` : 'RT'}
            </span>
          </div>
        `,
        iconSize: [52, 28],
        iconAnchor: [26, 14],
      });

      const marker = L.marker([markerLat, markerLon], { icon: trainIcon, zIndexOffset: isSelected ? 1000 : 500 });

      marker.on('click', () => {
        onSelectTrain(t.run_id);
      });

      marker.bindTooltip(
        `<b>${t.train_name} (${t.train_number})</b><br/>
         Route: ${t.source} → ${t.destination}<br/>
         Current: ${t.current_station} ${t.next_station ? `→ Next: ${t.next_station}` : ''}<br/>
         Delay: <b>+${delay.toFixed(1)} min</b><br/>
         Knock-on Risk: <span class="risk-badge risk-${t.knock_on_risk}">${t.knock_on_risk.toUpperCase()}</span>`,
        { direction: 'top' }
      );

      layerGroup.addLayer(marker);
    });
  }, [stations, trains, disruptions, selectedTrainId, onSelectTrain, simTime]);

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
