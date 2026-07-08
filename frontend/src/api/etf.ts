import api from './index'
import type { Kline } from '../types/market'

export async function getEtfList() {
  const { data } = await api.get('/data/etfs')
  return data
}

export async function getEtfKlines(etfCode: string, limit = 120) {
  const { data } = await api.get(`/data/etf/${etfCode}/daily`, { params: { limit } })
  return data
}
