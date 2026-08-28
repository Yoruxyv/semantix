import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

interface Color {
  alpha: number;
  blue: number;
  green: number;
  red: number;
}

const styles = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');

function token(name: string): string {
  const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(styles);
  if (match?.[1] === undefined) {
    throw new Error(`Missing CSS color token --${name}`);
  }
  return match[1].trim();
}

function parseHex(value: string): Color {
  const match = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(value);
  if (match?.[1] === undefined || match[2] === undefined || match[3] === undefined) {
    throw new Error(`Unsupported hex color: ${value}`);
  }
  return {
    alpha: 1,
    red: Number.parseInt(match[1], 16),
    green: Number.parseInt(match[2], 16),
    blue: Number.parseInt(match[3], 16),
  };
}

function parseRgba(value: string): Color {
  const match = /^rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)$/.exec(value);
  if (
    match?.[1] === undefined ||
    match[2] === undefined ||
    match[3] === undefined ||
    match[4] === undefined
  ) {
    throw new Error(`Unsupported rgba color: ${value}`);
  }
  return {
    alpha: Number.parseFloat(match[4]),
    red: Number.parseInt(match[1], 10),
    green: Number.parseInt(match[2], 10),
    blue: Number.parseInt(match[3], 10),
  };
}

function parseColor(value: string): Color {
  return value.startsWith('#') ? parseHex(value) : parseRgba(value);
}

function composite(foreground: Color, background: Color): Color {
  const mix = (front: number, back: number): number =>
    front * foreground.alpha + back * (1 - foreground.alpha);
  return {
    alpha: 1,
    red: mix(foreground.red, background.red),
    green: mix(foreground.green, background.green),
    blue: mix(foreground.blue, background.blue),
  };
}

function luminance(color: Color): number {
  const linearize = (channel: number): number => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * linearize(color.red) +
    0.7152 * linearize(color.green) +
    0.0722 * linearize(color.blue)
  );
}

function contrast(foreground: string, background: string): number {
  const backgroundColor = parseColor(token(background));
  const foregroundColor = composite(parseColor(token(foreground)), backgroundColor);
  const lighter = Math.max(luminance(foregroundColor), luminance(backgroundColor));
  const darker = Math.min(luminance(foregroundColor), luminance(backgroundColor));
  return (lighter + 0.05) / (darker + 0.05);
}

describe('small-text color contrast', () => {
  it.each([
    ['text-muted', 'ink'],
    ['text-muted', 'surface'],
    ['text-faint', 'ink'],
    ['text-faint', 'surface'],
    ['coral-text', 'ink'],
    ['coral-text', 'surface'],
    ['ink', 'coral-text'],
  ])('%s meets WCAG AA against %s', (foreground, background) => {
    expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
  });
});
