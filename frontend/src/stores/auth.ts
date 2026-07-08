import { reactive } from 'vue'
import { getMe } from '../api/auth'
import type { UserInfo } from '../types/auth'

export const authState = reactive<{ user: UserInfo | null; initialized: boolean }>({
  user: null,
  initialized: false,
})

export async function restoreSession() {
  try {
    const user = await getMe()
    authState.user = user
  } catch {
    authState.user = null
  } finally {
    authState.initialized = true
  }
}

export function setUser(user: UserInfo) {
  authState.user = user
}

export function clearUser() {
  authState.user = null
}
