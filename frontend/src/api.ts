export type User = { id: string; display_name: string; permissions: string[] }

function csrfToken(): string {
  const value = document.cookie.split('; ').find((item) => item.startsWith('csrf_token='))
  return value ? decodeURIComponent(value.split('=')[1]) : ''
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
    headers.set('X-CSRF-Token', csrfToken())
  }
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? body.code ?? `HTTP ${response.status}`)
  }
  return (await response.json()) as T
}
