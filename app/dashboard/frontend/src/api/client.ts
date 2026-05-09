import axios from 'axios'

/**
 * Axios instance configured for the Dashboard API.
 *
 * The Bearer token is read from localStorage so it persists across page
 * refreshes. Call `setApiToken(token)` once after the user enters it.
 */
const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

const TOKEN_KEY = 'dashboard_api_token'

export function setApiToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getApiToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function clearApiToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// Attach Bearer token to every request
apiClient.interceptors.request.use((config) => {
  const token = getApiToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Centralised error handling: 401 → show notification (handled by caller)
apiClient.interceptors.response.use(
  (res) => res,
  (err) => {
    // Re-throw so callers can handle individually
    return Promise.reject(err)
  },
)

export default apiClient
