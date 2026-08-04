const URL_SCHEME = /^[a-z][a-z\d+.-]*:/i;
const SAFE_LINK_SCHEMES = new Set(['http:', 'https:', 'mailto:']);
const URL_CONTROL_CHARACTERS = /[\u0000-\u0020]/g;

const cleanUrl = (url) => {
  if (typeof url !== 'string') {
    return null;
  }

  const value = url.trim();
  if (!value || value.startsWith('//') || value.startsWith('\\\\')) {
    return null;
  }

  return value;
};

export const sanitizeMarkdownLink = (url) => {
  const value = cleanUrl(url);
  if (!value) {
    return value;
  }

  const normalizedValue = value.replace(URL_CONTROL_CHARACTERS, '');
  if (normalizedValue.startsWith('//') || normalizedValue.startsWith('\\\\')) {
    return null;
  }
  if (!URL_SCHEME.test(normalizedValue)) {
    return value;
  }

  try {
    const parsedUrl = new URL(normalizedValue);
    return SAFE_LINK_SCHEMES.has(parsedUrl.protocol) ? normalizedValue : null;
  } catch {
    return null;
  }
};

export const sanitizeMarkdownImage = (url) => {
  const value = cleanUrl(url);
  const normalizedValue = value?.replace(URL_CONTROL_CHARACTERS, '');
  if (!value || URL_SCHEME.test(normalizedValue)) {
    return null;
  }

  return value;
};

export const isExternalMarkdownLink = (url) => /^https?:\/\//i.test(url || '');
