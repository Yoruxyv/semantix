export const MAX_CACHE_NAMESPACE_LENGTH = 64;
export const CACHE_NAMESPACE_PATTERN_SOURCE = `[A-Za-z0-9][A-Za-z0-9._:-]{0,${MAX_CACHE_NAMESPACE_LENGTH - 1}}`;

const CACHE_NAMESPACE_PATTERN = new RegExp(`^${CACHE_NAMESPACE_PATTERN_SOURCE}$`);

export function isCacheNamespace(value: string): boolean {
  return CACHE_NAMESPACE_PATTERN.test(value);
}
