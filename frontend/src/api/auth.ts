import api from './index'
import type { UserInfo } from '../types/auth'

export async function login(username: string, password: string) {
  const { data } = await api.post('/auth/login', { username, password })
  return data
}

export async function register(username: string, password: string) {
  const { data } = await api.post('/auth/register', { username, password })
  return data
}

export async function getMe(): Promise<UserInfo> {
  const { data } = await api.get('/auth/me')
  return data
}

export async function logout() {
  await api.post('/auth/logout')
}
