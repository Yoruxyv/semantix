# Accessibility verification

Semantix keeps chart data available as semantic tables and checks the shared
small-text color tokens against the WCAG AA 4.5:1 contrast requirement.

## Contrast matrix

The ratios below use the composited token colors from `apps/web/src/index.css`.

| Foreground | Background | Ratio | Normal text |
| --- | --- | ---: | --- |
| `--text-muted` | `--ink` | 6.79:1 | Pass |
| `--text-muted` | `--surface` | 6.58:1 | Pass |
| `--text-faint` | `--ink` | 5.18:1 | Pass |
| `--text-faint` | `--surface` | 5.05:1 | Pass |
| `--coral-text` | `--ink` | 5.85:1 | Pass |
| `--coral-text` | `--surface` | 5.48:1 | Pass |
| `--ink` | `--coral-text` | 5.85:1 | Pass |

The darker `--coral` token remains available for borders, plot marks, and
decorative accents. Small coral text uses `--coral-text`.

## Workspace navigation and request context

Evaluation subviews use native links with `aria-current` and URL state:
`/evaluations?view=runs`, `?view=datasets`, `?view=history`, and
`?view=reuse-quality`. Refresh, sharing, and browser history preserve the view;
unknown values display Runs. The `/benchmarks` redirect preserves search and hash.

Monitor namespace controls remain outside Advanced cache policy. A required
missing or invalid selection has visible guidance associated with the disabled
submit button and the namespace input. Selection never silently chooses a tenant.
The surrounding workspace remounts when principal permissions change.
Namespace selection labels show the built-in `default` as “Default”; editable
identifiers, request payloads, cache metadata, and diagnostics retain `default`.
Other namespace labels are unchanged.

Advanced cache policy stays visible beside the namespace controls. Request cache
mode uses a feature-owned button and listbox with the existing form-control style.
Enter or Space opens it; arrows and Home/End move focus without selecting. Enter
or clicking an option selects it. Escape cancels, Tab closes and continues normal
focus order, and outside interaction dismisses it without stealing focus. Selected
state, expanded state, visible focus, and the selected helper text remain available
to assistive technology; private-mode trace behavior retains its emphasis.

The similarity plot fits its container without a horizontal scrollbar. Its full
−1.00 to 1.00 scale, reference bands, points, and threshold markers retain the same
geometry. A wrapping band legend, fixed-size axis labels, compact ticks on one baseline,
and edge-constrained marker captions stay readable at narrow widths.

Reuse quality names its static evidence scope before loading and failure states,
links to its methodology, and exposes the threshold table as a keyboard-scrollable
region. Metrics retain their denominators and come from the reviewed receipt.
Observability retains the timestamp of the last successful process observation
when a refresh fails.

## Manual visual review

Check the following at desktop and mobile widths:

- muted labels and faint explanatory copy remain readable on both primary
  backgrounds;
- coral errors, destructive actions, and MISS labels are readable without
  appearing brighter than primary content;
- focus outlines remain visible when navigating with the keyboard;
- evaluation line charts and similarity histograms retain their visible
  presentation while exposing the same values in a screen-reader table;
- measured threshold points use outlined circles, projected points use filled
  squares, and every chart table names the value kind without relying on color;
- benchmark controls use no more than two columns at 744, 768, 820, and 834 px
  portrait widths, preserve 44 px interaction targets, and have no page-level
  horizontal overflow at 320, 1024, or 1280 px;
- the built-in/custom source choice, native JSON file control, validation
  errors, normalized preview, provider disclosure, and Run action remain in a
  one-column reading order at 744, 768, 820, and 834 px portrait widths;
- the file input has a visible label, accepted-format and size instructions,
  validation status is announced, structured issues include textual pointers,
  and removal returns focus to the file input;
- the advanced sweep disclosure works with Enter and Space, reports
  `aria-expanded`, and announces validation and run status without moving
  focus;
- every confusion-matrix cell is a native button with its outcome, count, and
  selected state exposed to assistive technology;
- the confusion matrix uses a readable 2 × 2 layout at 744, 768, 820, and
  834 px portrait widths rather than four compressed columns;
- false-positive and false-negative quick filters, bounded case search, and the
  “All cases” reset announce the visible result count without relying on color;
- mobile and tablet users receive a compact case list with the same detail
  action as the wide desktop table;
- inline case details preserve a logical heading and definition-list order,
  wrap long prompt and key evidence, do not steal focus when opened, and return
  focus to the invoking case control when closed;
- isolated evaluation keys are text evidence only and are not exposed as live
  Cache links;
- live Cache entry details use one readable column below 1024 px, wrap keys,
  namespaces, prompts, and previews without page-level overflow, expose copy
  feedback through a polite status, and keep Back to Cache as a real link;
- cache-entry deletion is shown only to Admin-capable users, and its exact-scope
  confirmation names an abbreviated key and namespace before activation;
- malformed, missing, expired, deleted, and unauthorized live-entry links use
  a neutral announced state without disclosing foreign-key existence;
- empty histogram bins have no visible bar.
- Monitor Advanced cache policy stays visible and uses a button/listbox with
  the selected mode's explanation; its namespace, policy, summary, and Submit flow
  remains one column at 744, 768, 820, and 834 px portrait widths;
- private-mode trace behavior is described by the field's helper text, effective
  namespace and policy are announced with results, and the live-hit link has
  the descriptive name “Open matched live cache entry”;
- Viewer query denial and scoped-admin threshold preview state are explained in
  text, while eligible Operator and wildcard-Admin actions remain keyboard
  operable with visible focus;

Navigation verification also covers:

- a compact menu from 320 through 834 CSS pixels and expanded navigation from
  1024 CSS pixels;
- native Enter and Space activation, Escape closure, conditional focus return,
  and route-change closure;
- portrait and landscape tablet widths, 200% zoom-equivalent layouts,
  increased text size, and long navigation labels;
- no horizontal overflow at any checked viewport.

Evaluation workspace review additionally covers long dataset and case names,
malicious-looking plain text, visible table-scroll affordances, case details at
320 px and 200% zoom, keyboard-only filtering/detail use, visible focus, and
the provider warning in normal reading order. Import review also covers local
malformed-JSON feedback, long file/dataset names, safe HTML-looking text,
warnings, removal, reload/auth cleanup, and zero horizontal overflow.

Persistent-catalog review additionally covers:

- the Runs/Datasets subview controls and source labels remain keyboard
  operable and do not add a fifth top-level navigation item;
- cards keep namespace, retention, expiry, size, Save, and Delete evidence in
  normal reading order at 744, 768, 820, and 834 px portrait widths;
- full digest and timestamp values remain available through accessible labels
  or titles when their visible forms are abbreviated;
- multi-namespace selection is explicitly labeled, wildcard namespace entry is
  validated, and Viewer/Operator/Admin controls match server capability;
- save/delete status uses polite live regions, errors use alerts, and the
  inline destructive confirmation names the exact dataset, namespace, case
  count, and consequence;
- untrusted names, descriptions, prompts, categories, and notes render as
  escaped wrapping text with no page-level overflow at 320, 1024, or 1280 px
  and at 200% zoom.

Run the automated token check with:

```powershell
cd apps/web
npm run test -- tests/shared/accessibility/contrast.test.ts
```

Routine polling and background revalidation retain the last successful data without skeletons, busy indicators, or dimming. Only initial loads without usable data show loading placeholders. Explicit Refresh actions keep their pending feedback; failed refreshes retain safe prior observations with a restrained stale/error message. Namespace or principal changes never reuse data from another scope.
