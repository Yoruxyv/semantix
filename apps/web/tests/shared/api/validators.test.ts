import { describe, expect, it } from 'vitest';

import {
  createEnumGuard,
  isIsoDate,
  isNonEmptyString,
  isNonNegativeNumber,
  isNullableIsoDate,
  isNullableNonNegativeNumber,
  isNumberInRange,
  isSha256Hex,
} from '@/shared/api/validators';

describe('shared API validators', () => {
  it('recognizes finite non-negative numbers', () => {
    expect(isNonNegativeNumber(0)).toBe(true);
    expect(isNonNegativeNumber(1.25)).toBe(true);
    expect(isNonNegativeNumber(-0.01)).toBe(false);
    expect(isNonNegativeNumber(Number.NaN)).toBe(false);
    expect(isNonNegativeNumber('1')).toBe(false);
  });

  it('recognizes nullable non-negative numbers', () => {
    expect(isNullableNonNegativeNumber(null)).toBe(true);
    expect(isNullableNonNegativeNumber(0)).toBe(true);
    expect(isNullableNonNegativeNumber(-1)).toBe(false);
    expect(isNullableNonNegativeNumber(undefined)).toBe(false);
  });

  it('checks inclusive numeric ranges', () => {
    expect(isNumberInRange(0, 0, 1)).toBe(true);
    expect(isNumberInRange(1, 0, 1)).toBe(true);
    expect(isNumberInRange(-0.01, 0, 1)).toBe(false);
    expect(isNumberInRange(1.01, 0, 1)).toBe(false);
    expect(isNumberInRange(Number.POSITIVE_INFINITY, 0, 1)).toBe(false);
  });

  it('rejects only empty or non-string content', () => {
    expect(isNonEmptyString('value')).toBe(true);
    expect(isNonEmptyString(' ')).toBe(true);
    expect(isNonEmptyString('')).toBe(false);
    expect(isNonEmptyString(null)).toBe(false);
  });

  it('recognizes ISO-compatible date strings from unknown values', () => {
    expect(isIsoDate('2026-07-17T10:00:00Z')).toBe(true);
    expect(isIsoDate('not-a-date')).toBe(false);
    expect(isIsoDate(123)).toBe(false);
    expect(isNullableIsoDate(null)).toBe(true);
    expect(isNullableIsoDate('2026-07-17T10:00:00Z')).toBe(true);
    expect(isNullableIsoDate(undefined)).toBe(false);
  });

  it('recognizes lowercase SHA-256 hexadecimal values', () => {
    expect(isSha256Hex('a'.repeat(64))).toBe(true);
    expect(isSha256Hex('A'.repeat(64))).toBe(false);
    expect(isSha256Hex('a'.repeat(63))).toBe(false);
    expect(isSha256Hex(64)).toBe(false);
  });

  it('creates literal-preserving enum guards', () => {
    const isTone = createEnumGuard(['gold', 'teal'] as const);
    const values: unknown[] = ['gold', 'coral'];
    const tones: Array<'gold' | 'teal'> = values.filter(isTone);

    expect(isTone(values[0])).toBe(true);
    expect(isTone('coral')).toBe(false);
    expect(isTone(null)).toBe(false);
    expect(tones).toEqual(['gold']);
  });
});
