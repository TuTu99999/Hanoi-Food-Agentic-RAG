export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

const ensureApiPath = (path) => {
  if (typeof path !== 'string' || !/^\/api(?:\/|$)/.test(path)) {
    throw new Error(`API path phải là đường dẫn cùng origin bắt đầu bằng /api: ${path}`);
  }

  return path;
};

const parseResponseBody = async (response) => {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

const getErrorMessage = (data, fallback) => {
  if (typeof data === 'string' && data.trim()) return data;
  if (typeof data?.detail === 'string') return data.detail;
  if (typeof data?.message === 'string') return data.message;

  if (Array.isArray(data?.detail)) {
    return data.detail
      .map((item) => item?.msg)
      .filter(Boolean)
      .join(', ') || fallback;
  }

  return fallback;
};

export const apiFetch = (path, options = {}) => {
  const headers = new Headers(options.headers);
  const hasBody = options.body !== undefined && options.body !== null;
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;

  if (hasBody && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  return fetch(ensureApiPath(path), {
    ...options,
    headers,
    credentials: 'include',
  });
};

export const toApiError = async (response, fallbackMessage = 'Yêu cầu tới máy chủ thất bại.') => {
  const data = await parseResponseBody(response);
  return new ApiError(
    getErrorMessage(data, `${fallbackMessage} (${response.status})`),
    response.status,
    data,
  );
};

export const apiJson = async (path, options = {}) => {
  const response = await apiFetch(path, options);

  if (!response.ok) {
    throw await toApiError(response);
  }

  return parseResponseBody(response);
};
