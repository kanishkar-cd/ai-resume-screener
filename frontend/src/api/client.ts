import type { ApiDataEnvelope, ApiErrorBody } from './types'

const DEFAULT_BASE_URL = 'http://localhost:8000/api/v1'

export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL as string | undefined
  return (raw?.replace(/\/$/, '') || DEFAULT_BASE_URL)
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>
  readonly correlationId?: string

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    correlationId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.correlationId = correlationId
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  /** JSON-serializable object, FormData, or other BodyInit. */
  body?: BodyInit | object | null
  /** When true, skip JSON Content-Type (e.g. FormData). */
  isMultipart?: boolean
  /** When true, return raw Response (no JSON parse / envelope unwrap). */
  raw?: boolean
}

function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined | null>): string {
  const base = getApiBaseUrl()
  const url = new URL(path.startsWith('http') ? path : `${base}${path.startsWith('/') ? path : `/${path}`}`)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody
    if (body?.error) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        body.error.details ?? {},
        body.error.correlation_id,
      )
    }
  } catch {
    // fall through
  }
  return new ApiError(
    response.status,
    'HTTP_ERROR',
    response.statusText || `Request failed with status ${response.status}`,
  )
}

/**
 * Low-level fetch wrapper. Unwraps `{ data: T }` envelopes by default.
 */
export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
  query?: Record<string, string | number | boolean | undefined | null>,
): Promise<T> {
  const { body, isMultipart, raw, headers: initHeaders, ...rest } = options
  const headers = new Headers(initHeaders)

  let resolvedBody: BodyInit | undefined
  if (body != null) {
    if (isMultipart || body instanceof FormData) {
      resolvedBody = body as BodyInit
    } else if (typeof body === 'string' || body instanceof Blob || body instanceof ArrayBuffer) {
      resolvedBody = body as BodyInit
      if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    } else {
      resolvedBody = JSON.stringify(body)
      if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    }
  }

  const response = await fetch(buildUrl(path, query), {
    ...rest,
    headers,
    body: resolvedBody,
  })

  if (!response.ok) {
    throw await parseError(response)
  }

  // 207 Multi-Status is success for batch resume upload (partial failures live in body).
  if (raw) {
    return response as unknown as T
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  if (!text) {
    return undefined as T
  }

  const json = JSON.parse(text) as ApiDataEnvelope<T> | T
  if (json && typeof json === 'object' && 'data' in json) {
    return (json as ApiDataEnvelope<T>).data
  }
  return json as T
}
