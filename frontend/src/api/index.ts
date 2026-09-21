import axios from 'axios'

// 并发的 401 只触发一次 refresh,其余请求 await 同一个 Promise
let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  try {
    await api.post('/auth/refresh')
    return true
  } catch {
    return false
  }
}

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    // 非 401 / 已重试过 / refresh 接口自身的 401(未登录)直接抛出。
    // 最后一个条件是关键:否则 refresh 的 401 会再次进入本拦截器并等待
    // 外层 finally,形成互相等待的死锁,页面 spinner 永不消失。
    if (error.response?.status !== 401 || original._retry || original.url === '/auth/refresh') {
      return Promise.reject(error)
    }

    original._retry = true

    if (!refreshing) {
      refreshing = tryRefresh().finally(() => {
        refreshing = null
      })
    }
    const ok = await refreshing

    if (!ok) {
      // hash 路由下用 location.hash,避免 location.href 拼出 '/#/##/login'
      window.location.hash = '#/login'
      return Promise.reject(error)
    }
    return api(original)
  }
)

export default api
