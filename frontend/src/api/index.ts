import axios from 'axios'

let refreshing = false
const refreshQueue: Array<() => void> = []

function waitRefresh() {
  return new Promise<void>((resolve) => {
    refreshQueue.push(resolve)
  })
}

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config
    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error)
    }

    original._retry = true

    if (!refreshing) {
      refreshing = true
      try {
        await api.post('/auth/refresh')
      } catch {
        window.location.href = '/#/login'
        return Promise.reject(error)
      } finally {
        refreshing = false
        const queue = refreshQueue.splice(0)
        queue.forEach((resolve) => resolve())
      }
    }

    await waitRefresh()
    return api(original)
  }
)

export default api
