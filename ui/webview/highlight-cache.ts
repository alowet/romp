// Highlighted HTML for a fenced code block, cached by (language, source).
//
// hljs.highlightAuto over the ten registered grammars is the single largest cost of a chat tail that
// re-renders a fence (63% of a compact-mode tail in one deployment's profile), and every window rebuild on
// a tab switch or a scroll-back tokenizes the same fences again. The result is a pure function of the two
// strings, so the repeat work is the only thing this removes: an unlabeled fence still gets the full grammar
// set (a narrower subset is a product change, not an optimization), and a labeled one still goes to its
// grammar.
// Bounded: at most CAP entries and about BUDGET characters of output, oldest out first (a Map keeps
// insertion order; a hit is re-inserted so it counts as newest). Very large sources are not cached at all.
export interface Highlighter {
  getLanguage(name: string): unknown;
  highlight(raw: string, opts: { language: string }): { value: string };
  highlightAuto(raw: string): { value: string };
}

export const CAP = 256;               // entries
export const BUDGET = 4_000_000;      // characters of highlighted HTML held, all entries together
export const MAX_RAW = 64_000;        // a source longer than this is highlighted but never kept

export interface HighlightCache { map: Map<string, string>; chars: number }
export function newHighlightCache(): HighlightCache { return { map: new Map(), chars: 0 }; }
const shared = newHighlightCache();

/** The highlighted HTML for `raw` in `lang` (unknown or missing → auto-detected), tokenized at most once
 *  per distinct (lang, raw) while the entry is held. */
export function highlightHtml(hl: Highlighter, lang: string | undefined, raw: string, cache: HighlightCache = shared): string {
  const known = !!(lang && hl.getLanguage(lang));
  const key = (known ? lang : "") + " " + raw;
  const hit = cache.map.get(key);
  if (hit !== undefined) {
    cache.map.delete(key); cache.map.set(key, hit);   // newest again
    return hit;
  }
  const html = known ? hl.highlight(raw, { language: lang as string }).value : hl.highlightAuto(raw).value;
  if (raw.length <= MAX_RAW) {
    cache.map.set(key, html); cache.chars += html.length;
    while (cache.map.size > CAP || (cache.chars > BUDGET && cache.map.size > 1)) {
      const oldest = cache.map.keys().next().value as string;
      cache.chars -= (cache.map.get(oldest) as string).length;
      cache.map.delete(oldest);
    }
  }
  return html;
}
