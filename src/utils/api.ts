let inMemoryCsrfToken = '';
let onUnauthorizedHandler: (() => void) | null = null;

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export function setCsrfToken(token: string) {
  inMemoryCsrfToken = token;
}

export function getCsrfTokenFromCookie(): string {
  if (typeof document === 'undefined') return '';
  const match = /(?:^|;\s*)hb_csrf=([^;]+)/.exec(document.cookie);
  return match ? decodeURIComponent(match[1]) : '';
}

export function getActiveCsrfToken(): string {
  return inMemoryCsrfToken || getCsrfTokenFromCookie();
}

export function registerUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorizedHandler = fn;
}

export async function ensurePreAuthCsrf(signal?: AbortSignal, force = false): Promise<string> {
  if (!force) {
    const existing = getActiveCsrfToken();
    if (existing) return existing;
  }
  const res = await fetch('/api/v1/auth/csrf', {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });
  const ct = res.headers.get('content-type') || '';
  if (!res.ok || !ct.includes('application/json')) {
    throw new ApiError(res.status, 'امکان دریافت توکن امنیتی نشست وجود ندارد.');
  }
  const data = (await res.json()) as { csrf_token: string };
  inMemoryCsrfToken = data.csrf_token;
  return data.csrf_token;
}

export interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  skipUnauthorizedRedirect?: boolean;
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { body, headers: customHeaders, skipUnauthorizedRedirect, method = 'GET', ...rest } = options;
  const upperMethod = method.toUpperCase();
  const isMutating = !['GET', 'HEAD', 'OPTIONS'].includes(upperMethod);

  if (isMutating && !getActiveCsrfToken()) {
    await ensurePreAuthCsrf(rest.signal ?? undefined);
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(customHeaders as Record<string, string> | undefined),
  };

  let serializedBody: BodyInit | undefined;
  if (body !== undefined) {
    if (body instanceof FormData || typeof body === 'string') {
      serializedBody = body;
    } else {
      headers['Content-Type'] = 'application/json';
      serializedBody = JSON.stringify(body);
    }
  }

  if (isMutating) {
    const csrf = getActiveCsrfToken();
    if (csrf) {
      headers['X-CSRF-Token'] = csrf;
    }
  }

  const response = await fetch(path, {
    method: upperMethod,
    credentials: 'include',
    headers,
    body: serializedBody,
    ...rest,
  });

  if (response.status === 401 && !skipUnauthorizedRedirect && onUnauthorizedHandler) {
    inMemoryCsrfToken = '';
    onUnauthorizedHandler();
  }

  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');

  if (!response.ok) {
    let message =
      response.status === 502 || response.status === 503 || response.status === 504
        ? 'سرور در حال آماده‌سازی است؛ لحظاتی بعد دوباره تلاش کنید.'
        : 'خطا در برقراری ارتباط با سرور';
    let detail: unknown = null;
    if (isJson) {
      try {
        const errBody = (await response.json()) as {
          detail?: unknown;
          message?: string;
          errors?: Array<{ message?: string }>;
        };
        detail = errBody;
        if (typeof errBody.detail === 'string') {
          message = errBody.detail;
        } else if (Array.isArray(errBody.errors) && typeof errBody.errors[0]?.message === 'string') {
          message = errBody.errors[0].message;
        } else if (typeof errBody.message === 'string') {
          message = errBody.message;
        }
      } catch {
        // Ignore parse failure
      }
    }
    throw new ApiError(response.status, message, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  if (isJson) {
    return (await response.json()) as T;
  }

  return (await response.text()) as unknown as T;
}

export async function downloadAuthenticatedFile(path: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(path, {
    method: 'GET',
    credentials: 'include',
  });

  if (response.status === 401 && onUnauthorizedHandler) {
    onUnauthorizedHandler();
    throw new ApiError(401, 'نشست کاربری منقضی شده است.');
  }

  if (!response.ok) {
    let message = 'خطا در دریافت فایل خروجی';
    try {
      const errBody = (await response.json()) as { detail?: string };
      if (errBody?.detail) message = errBody.detail;
    } catch {
      // Ignore
    }
    throw new ApiError(response.status, message);
  }

  const disp = response.headers.get('content-disposition') || '';
  const match = /filename="?([^"]+)"?/i.exec(disp);
  const filename = match ? match[1] : fallbackFilename;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
