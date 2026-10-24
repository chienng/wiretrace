/**
 * JSON Text (spec 028, slice B): the body re-indented by 2 spaces, every literal copied as sent.
 * `JSON.stringify(JSON.parse(text))` would rewrite large numbers, `1.50` and string escapes.
 * Only called on text `tryParseJson` accepted, so the input is valid JSON.
 */
const INDENT = '  ';

const isSpace = (c: string) => c === ' ' || c === '\t' || c === '\n' || c === '\r';
const isDelimiter = (c: string) => isSpace(c) || c === ',' || c === ':' || c === '{' || c === '}' || c === '[' || c === ']' || c === '"';

export function formatJsonText(text: string): string {
  const src = text.trim();
  const out: string[] = [];
  let depth = 0;
  let i = 0;
  const newline = () => '\n' + INDENT.repeat(depth);

  while (i < src.length) {
    const c = src[i] as string;
    if (c === '"') {
      let j = i + 1;
      while (j < src.length && src[j] !== '"') j += src[j] === '\\' ? 2 : 1;
      out.push(src.slice(i, j + 1));
      i = j + 1;
    } else if (isSpace(c)) {
      i++;
    } else if (c === '{' || c === '[') {
      const close = c === '{' ? '}' : ']';
      let j = i + 1;
      while (j < src.length && isSpace(src[j] as string)) j++;
      if (src[j] === close) {
        out.push(c + close);
        i = j + 1;
      } else {
        depth++;
        out.push(c + newline());
        i++;
      }
    } else if (c === '}' || c === ']') {
      depth--;
      out.push(newline() + c);
      i++;
    } else if (c === ',') {
      out.push(',' + newline());
      i++;
    } else if (c === ':') {
      out.push(': ');
      i++;
    } else {
      let j = i + 1;
      while (j < src.length && !isDelimiter(src[j] as string)) j++;
      out.push(src.slice(i, j));
      i = j;
    }
  }
  return out.join('');
}
