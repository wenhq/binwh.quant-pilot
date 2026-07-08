import api from './index'
import type { RegimeResponse, KlineResponse } from '../types/market'

export async function getRegimeStates(market: string): Promise<RegimeResponse> {
  const { data } = await api.get(`/market_regime/states/${market}`)
  return data
}

export async function getIndexKlines(indexCode: string, limit = 120): Promise<KlineResponse> {
  const { data } = await api.get(`/data/index/${indexCode}/daily`, { params: { limit } })
  return data
}
