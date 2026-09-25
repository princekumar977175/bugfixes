/**
 * TypeScript type definitions matching backend FastAPI schemas.
 */

export interface StationItem {
  code: string;
  name: string;
  lat: number;
  lon: number;
  zone: string;
  is_junction: boolean;
}

export type StringOrNull = string | null;

export interface TrainListItem {
  run_id: string;
  train_number: string;
  train_name: string;
  train_type: string;
  priority_class: number;
  source: string;
  destination: string;
  run_date: string;
  current_station: string | null;
  next_station: string | null;
  current_delay_min: number;
  status: 'running' | 'scheduled' | 'completed';
  knock_on_risk: 'low' | 'medium' | 'high';
}

export interface StationETAForecast {
  station_code: string;
  station_name: string;
  seq: number;
  stations_ahead: number;
  sched_arr: string;
  actual_arr: string | null;
  baseline_a_eta: string;
  eta_lower: string;
  eta_median: string;
  eta_upper: string;
  interval_width_min: number;
  predicted_median_delay_min: number;
  reasons: string;
}

export interface TrainETAResponse {
  run_id: string;
  train_number: string;
  train_name: string;
  as_of_timestamp: string;
  current_station: string;
  current_delay_min: number;
  downstream_stations: StationETAForecast[];
}

export interface DriverAttribution {
  feature: string;
  label: string;
  shap_value: number;
  importance: number;
  feature_val: any;
  category: string;
}

export interface ETAChangeLogItem {
  id: number;
  station_code: string;
  timestamp: string;
  old_eta: string | null;
  new_eta: string;
  delta_min: number;
  reasons: string;
}

export interface TrainExplainResponse {
  run_id: string;
  train_number: string;
  train_name: string;
  as_of_timestamp: string;
  latest_explanation: string;
  delta_min: number;
  top_drivers: DriverAttribution[];
  change_history: ETAChangeLogItem[];
}

export interface DisruptionItem {
  id: string;
  section_id: string;
  type: string;
  start_time: string;
  end_time: string;
  severity: number;
}

export interface ReplayStatus {
  status: 'stopped' | 'running' | 'paused';
  current_sim_time: string;
  speed: number;
  active_run_id: string | null;
}

export interface WebSocketETAUpdate {
  type: 'eta_update' | 'connected' | 'pong';
  run_id?: string;
  sim_time?: string;
  current_station?: string;
  next_station?: string | null;
  current_delay_min?: number;
  predictions?: StationETAForecast[];
  latest_explanation?: string;
  top_drivers?: DriverAttribution[];
  delta_min?: number;
  message?: string;
}
