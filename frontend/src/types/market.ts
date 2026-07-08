export interface RegimeState {
  trade_date: string
  state_label: number
  state_prob: number
}

export interface RegimeResponse {
  market: string
  run_id: number
  trained_at: string
  algorithm: string
  metrics: Record<string, any>
  states: RegimeState[]
}

export interface Kline {
  trade_date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount?: number
}

export interface KlineResponse {
  index_code: string
  name: string
  data: Kline[]
}
