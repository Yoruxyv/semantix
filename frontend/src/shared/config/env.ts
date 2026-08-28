function readApiBaseUrl(value: string | undefined): string {
  if (value === undefined || value.trim() === '') {
    return '';
  }

  let normalizedValue = value.trim();
  while (normalizedValue.endsWith('/')) {
    normalizedValue = normalizedValue.slice(0, -1);
  }

  const parsedUrl = new URL(normalizedValue);
  if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
    throw new Error('VITE_API_BASE_URL must use HTTP or HTTPS');
  }
  return normalizedValue;
}

export const API_BASE_URL = readApiBaseUrl(import.meta.env.VITE_API_BASE_URL);
