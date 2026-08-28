import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import type { Components } from 'react-markdown';
import 'katex/dist/katex.min.css';

import { prepareMarkdown } from '@/shared/lib/markdown';

import type { JSX } from 'react';

type MarkdownDensity = 'comfortable' | 'compact';

interface MarkdownContentProps {
  readonly className?: string;
  readonly density?: MarkdownDensity;
  readonly markdown: string;
}

interface MarkdownStyles {
  blockquote: string;
  headingLarge: string;
  headingSmall: string;
  list: string;
  paragraph: string;
  pre: string;
  tableWrapper: string;
}

const STYLES: Record<MarkdownDensity, MarkdownStyles> = {
  comfortable: {
    blockquote:
      'mb-3 border-l-2 border-[var(--hairline)] pl-4 italic text-[var(--text-muted)] last:mb-0',
    headingLarge: 'font-display mb-2 text-lg italic',
    headingSmall: 'font-display mb-2 text-base italic',
    list: 'mb-3 space-y-1 pl-5 last:mb-0',
    paragraph: 'mb-3 whitespace-pre-wrap break-words leading-7 last:mb-0',
    pre: 'scrollbar-thin mb-3 overflow-x-auto rounded border border-[var(--hairline)] bg-[rgba(0,0,0,0.25)] p-3 text-xs last:mb-0',
    tableWrapper: 'mb-3 overflow-x-auto last:mb-0',
  },
  compact: {
    blockquote:
      'mb-2 border-l-2 border-[var(--hairline)] pl-3 italic text-[var(--text-muted)] last:mb-0',
    headingLarge: 'font-display mb-2 text-base italic text-[var(--text)]',
    headingSmall: 'font-display mb-2 text-sm italic text-[var(--text)]',
    list: 'mb-2 space-y-1 pl-5 last:mb-0',
    paragraph: 'mb-2 whitespace-pre-wrap break-words leading-6 last:mb-0',
    pre: 'scrollbar-thin mb-2 overflow-x-auto rounded border border-[var(--hairline)] bg-[rgba(0,0,0,0.25)] p-3 text-xs last:mb-0',
    tableWrapper: 'mb-2 overflow-x-auto last:mb-0',
  },
};

function createMarkdownComponents(density: MarkdownDensity): Components {
  const styles = STYLES[density];
  const Heading = density === 'compact' ? 'h4' : 'h3';

  return {
    p: ({ ...props }) => <p className={styles.paragraph} {...props} />,
    strong: ({ ...props }) => (
      <strong className="font-semibold text-(--text)" {...props} />
    ),
    em: ({ ...props }) => <em {...props} />,
    a: ({ children, ...props }) => (
      <a
        className="text-(--teal) underline decoration-[rgba(91,156,148,0.35)] underline-offset-4 hover:text-(--text)"
        rel="noopener noreferrer"
        target="_blank"
        {...props}
      >
        {children}
      </a>
    ),
    ul: ({ ...props }) => <ul className={`${styles.list} list-disc`} {...props} />,
    ol: ({ ...props }) => <ol className={`${styles.list} list-decimal`} {...props} />,
    li: ({ ...props }) => <li className="leading-6" {...props} />,
    blockquote: ({ ...props }) => (
      <blockquote className={styles.blockquote} {...props} />
    ),
    code: ({ className, children, ...props }) => {
      const isBlock = className?.includes('language-');

      return isBlock ? (
        <code
          className={`font-data block whitespace-pre-wrap wrap-break-word ${
            className ?? ''
          }`}
          {...props}
        >
          {children}
        </code>
      ) : (
        <code
          className="font-data rounded bg-[rgba(234,230,221,0.08)] px-1.5 py-0.5 text-[0.85em] text-(--gold)"
          {...props}
        >
          {children}
        </code>
      );
    },
    pre: ({ ...props }) => <pre className={styles.pre} {...props} />,
    h1: ({ children, ...props }) => (
      <Heading className={styles.headingLarge} {...props}>
        {children}
      </Heading>
    ),
    h2: ({ children, ...props }) => (
      <Heading className={styles.headingLarge} {...props}>
        {children}
      </Heading>
    ),
    h3: ({ children, ...props }) => (
      <Heading className={styles.headingSmall} {...props}>
        {children}
      </Heading>
    ),
    table: ({ children, ...props }) => (
      <div className={styles.tableWrapper}>
        <table className="font-data w-full border-collapse text-xs" {...props}>
          {children}
        </table>
      </div>
    ),
    th: ({ ...props }) => (
      <th
        {...props}
        className="border-b border-(--hairline) px-2 py-1.5 text-left text-(--text-faint)"
        scope="col"
      />
    ),
    td: ({ ...props }) => (
      <td className="border-b border-[rgba(234,230,221,0.05)] px-2 py-1.5" {...props} />
    ),
    hr: ({ ...props }) => (
      <hr className="my-3 border-0 border-t border-(--hairline)" {...props} />
    ),
    img: ({ alt = '', src, ...props }) => {
      if (!src) {
        return null;
      }

      return <img alt={alt} src={src} {...props} />;
    },
  };
}

const COMPONENTS: Record<MarkdownDensity, Components> = {
  comfortable: createMarkdownComponents('comfortable'),
  compact: createMarkdownComponents('compact'),
};

export function MarkdownContent({
  className,
  density = 'comfortable',
  markdown,
}: MarkdownContentProps): JSX.Element {
  const preparedMarkdown = prepareMarkdown(markdown);
  const classes = [
    className,
    '[&_.katex-display]:overflow-x-auto',
    '[&_.katex-display]:overflow-y-hidden',
    '[&_.katex-display]:py-2',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes}>
      <ReactMarkdown
        components={COMPONENTS[density]}
        rehypePlugins={[rehypeKatex]}
        remarkPlugins={[remarkGfm, remarkMath]}
      >
        {preparedMarkdown}
      </ReactMarkdown>
    </div>
  );
}
