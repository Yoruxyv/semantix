import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { MarkdownContent } from '@/shared/components/markdown/MarkdownContent';

describe('MarkdownContent URL safety', () => {
  afterEach(cleanup);

  it.each([
    ['HTTPS', 'https://example.com/reference'],
    ['email', 'mailto:team@example.com'],
    ['relative', '/docs/providers'],
    ['fragment', '#cache-policy'],
  ])('preserves an allowed %s link', (label, url) => {
    render(<MarkdownContent markdown={`[${label}](${url})`} />);

    expect(screen.getByRole('link', { name: label }).getAttribute('href')).toBe(url);
  });

  it.each([
    'javascript:alert%281%29',
    'JaVaScRiPt:alert%281%29',
    'data:text/html;base64,PHNjcmlwdD4=',
  ])('removes the unsafe link URL %s', (url) => {
    render(<MarkdownContent markdown={`[Unsafe link](${url})`} />);

    const renderedAnchor = screen.getByText('Unsafe link').closest('a');

    expect(renderedAnchor?.getAttribute('href')).toBe('');
    expect(screen.queryByRole('link', { name: 'Unsafe link' })).toBeNull();
  });

  it('removes data URLs from Markdown images', () => {
    render(
      <MarkdownContent markdown="![Unsafe image](data:image/svg+xml;base64,PHN2Zz4=)" />,
    );

    expect(screen.queryByRole('img', { name: 'Unsafe image' })).toBeNull();
  });

  it('does not interpret raw HTML as elements', () => {
    const { container } = render(
      <MarkdownContent markdown={'<script>alert("unsafe")</script>'} />,
    );

    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert("unsafe")</script>');
  });
});
