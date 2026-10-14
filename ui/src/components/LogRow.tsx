import { memo } from 'react';
import { formatTime } from '../logic/format';
import { isCrash, normalizeLevel } from '../logic/logs';
import type { LogLine } from '../types';

export const LOG_ROW_HEIGHT = 22;

interface Props {
  line: LogLine;
  selected?: boolean;
  linked?: boolean;
  compact?: boolean;
  onSelect?: (line: LogLine) => void;
  onOpen?: (line: LogLine) => void;
}

export const LogRow = memo(function LogRow({ line, selected, linked, compact, onSelect, onOpen }: Props) {
  const level = normalizeLevel(line.level);
  const fatal = isCrash(line);
  const err = level === 'E' || level === 'F';
  const cls = ['lrow'];
  if (compact) cls.push('compact');
  if (linked) cls.push('linked');
  if (err) cls.push('err');
  if (fatal) cls.push('fatal');
  if (selected) cls.push('sel');
  return (
    <div
      className={cls.join(' ')}
      style={{ height: LOG_ROW_HEIGHT }}
      role="option"
      aria-selected={!!selected}
      onClick={onSelect ? () => onSelect(line) : undefined}
      onDoubleClick={onOpen ? () => onOpen(line) : undefined}
    >
      <span className="t">{formatTime(line.ts)}</span>
      <span>{level ? <span className={`lv ${level}`}>{level}</span> : <span className="lv none">·</span>}</span>
      <span className="tg" title={line.tag ?? ''}>
        {line.tag ?? ''}
      </span>
      <span className="msg" title={line.message}>
        {line.message}
      </span>
      <span className="ln" title={line.request_id ? 'Linked to a request' : ''}>
        {line.request_id ? '↗' : ''}
      </span>
    </div>
  );
});
