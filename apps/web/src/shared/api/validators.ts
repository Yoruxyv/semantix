/** Shared shape guards; feature decoders own required fields and invariants. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function isNonNegativeNumber(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0;
}

export function isNullableNonNegativeNumber(value: unknown): value is number | null {
  return value === null || isNonNegativeNumber(value);
}

export function isNumberInRange(
  value: unknown,
  minimum: number,
  maximum: number,
): value is number {
  return isFiniteNumber(value) && value >= minimum && value <= maximum;
}

/** Check length without trimming; whitespace-only strings pass. */
export function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

export function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string';
}

export function isNonNegativeInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value) && value >= 0;
}

/** Accept strings understood by Date.parse, without enforcing strict ISO syntax. */
export function isIsoDate(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}

export function isNullableIsoDate(value: unknown): value is string | null {
  return value === null || isIsoDate(value);
}

/** Validate lowercase digest syntax only, without verifying content or ownership. */
export function isSha256Hex(value: unknown): value is string {
  return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
}

/** Check provider-name syntax; registration and availability belong to the server. */
export function isProviderName(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,49}$/.test(value);
}

/** Snapshot allowed literals in a Set while preserving their union type. */
export function createEnumGuard<const TValue extends string>(
  values: readonly TValue[],
): (value: unknown) => value is TValue {
  const allowedValues = new Set<string>(values);

  return (value: unknown): value is TValue =>
    typeof value === 'string' && allowedValues.has(value);
}
