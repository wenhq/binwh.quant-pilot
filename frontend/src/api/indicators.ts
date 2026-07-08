import api from './index'

export interface IndicatorData {
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  macd_dif: number | null
  macd_dea: number | null
  macd_hist: number | null
  rsi: number | null
  boll_upper: number | null
  boll_mid: number | null
  boll_lower: number | null
}

export interface AllIndicatorsResponse {
  code: string
  adjust_mode: string
  data: IndicatorData[]
}

export async function getAllIndicators(
  assetType: string,
  code: string,
  limit = 120,
  adjustMode = 'forward'
): Promise<AllIndicatorsResponse> {
  const { data } = await api.get(`/indicators/${assetType}/${code}/all`, {
    params: { limit, adjust_mode: adjustMode },
  })
  return data
}
