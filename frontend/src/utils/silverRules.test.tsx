import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  formatSilverRule,
  parseSilverRuleInput,
} from './silverRules';

describe('Silver deterministic rule presentation', () => {
  it('renders the backend not_null object through the production formatter', () => {
    const markup = renderToStaticMarkup(
      <span>{formatSilverRule({ type: 'not_null', column: 'cid' })}</span>,
    );

    expect(markup).toBe('<span>cid is not null</span>');
  });

  it('intentionally formats every supported deterministic rule kind', () => {
    expect(formatSilverRule({ type: 'distinct' })).toBe(
      'Remove exact duplicate rows',
    );
    expect(
      formatSilverRule({
        type: 'compare',
        column: 'amount',
        operator: '>=',
        value: 100,
      }),
    ).toBe('amount >= 100');
    expect(
      formatSilverRule({
        type: 'compare',
        column: 'status',
        operator: '=',
        value: 'active',
      }),
    ).toBe('status = "active"');
  });

  it('uses a bounded readable fallback for an unexpected structured object', () => {
    const formatted = formatSilverRule({
      type: 'future_rule',
      detail: 'x'.repeat(500),
    });

    expect(formatted).toMatch(/^Unsupported rule: \{/);
    expect(formatted).not.toContain('[object Object]');
    expect(formatted.length).toBeLessThanOrEqual(178);
  });

  it('round-trips editable supported rule labels to deterministic objects', () => {
    expect(parseSilverRuleInput('cid is not null')).toEqual({
      type: 'not_null',
      column: 'cid',
    });
    expect(parseSilverRuleInput('Remove exact duplicate rows')).toEqual({
      type: 'distinct',
    });
    expect(parseSilverRuleInput('amount >= 100')).toEqual({
      type: 'compare',
      column: 'amount',
      operator: '>=',
      value: 100,
    });
    expect(parseSilverRuleInput('status = "active"')).toEqual({
      type: 'compare',
      column: 'status',
      operator: '=',
      value: 'active',
    });
  });
});
