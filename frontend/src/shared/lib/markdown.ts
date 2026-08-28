const CODE_SEGMENT = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g;
const DISPLAY_MATH = /\\\[([\s\S]*?)\\\]/g;
const INLINE_MATH = /\\\(([\s\S]*?)\\\)/g;

/**
 * LLMs sometimes wrap an entire markdown-formatted answer in an outer
 * ```markdown fence (e.g. when asked to demonstrate markdown syntax).
 * Since code fences don't nest, react-markdown parses that outer fence
 * as one literal code block, so headings/bold/links inside never render.
 *
 * This strips a leading ```markdown / ```md fence (and matching trailing
 * fence, if present) so nested code blocks and formatting render normally.
 * Only triggers on that specific language tag, so a response that's
 * genuinely "here's a markdown code snippet" for any other language is
 * left untouched.
 */
export function unwrapOuterMarkdownFence(text: string): string {
  const trimmed = text.trim();
  const openFence = /^```(?:markdown|md)[ \t]*\r?\n/i.exec(trimmed);
  if (!openFence) return text;

  let inner = trimmed.slice(openFence[0].length);
  // Only strip a trailing fence if it's on its own line at the very end —
  // response may also be truncated mid-stream with no closing fence at all.
  inner = inner.replace(/\r?\n```[ \t]*$/, '');
  return inner;
}

function replaceDisplayMath(_match: string, expression: string): string {
  return `\n\n$$\n${expression.trim()}\n$$\n\n`;
}

function replaceInlineMath(_match: string, expression: string): string {
  return `$${expression.trim()}$`;
}

export function normalizeMathDelimiters(markdown: string): string {
  return markdown
    .split(CODE_SEGMENT)
    .map((segment) => {
      if (
        segment.startsWith('```') ||
        segment.startsWith('~~~') ||
        segment.startsWith('`')
      ) {
        return segment;
      }

      return segment
        .replace(DISPLAY_MATH, replaceDisplayMath)
        .replace(INLINE_MATH, replaceInlineMath);
    })
    .join('');
}

export function prepareMarkdown(markdown: string): string {
  return normalizeMathDelimiters(unwrapOuterMarkdownFence(markdown));
}
