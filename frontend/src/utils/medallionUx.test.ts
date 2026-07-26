import { describe, expect, it } from 'vitest';
import {
  canIngestBronzeSelection,
  initialBronzeSelection,
  toggleAllBronzeTables,
  toggleBronzeTable,
} from './bronzeSelection';
import {
  readRelationSelection,
  relationSelectionKey,
  withRelationSelectionQuery,
} from './relationSelection';

describe('Dataset relation selection propagation', () => {
  it('preserves schema and table independently in URL-backed state', () => {
    const path = withRelationSelectionQuery(
      '/projects/project-1/metadata?runId=run-1',
      { schema: 'source data', table: 'daily.orders' },
    );
    const params = new URLSearchParams(path.split('?')[1]);

    expect(path).toContain('runId=run-1');
    expect(readRelationSelection(params)).toEqual({
      schema: 'source data',
      table: 'daily.orders',
    });
  });

  it('does not collapse same-named or dotted relations into one identity', () => {
    expect(relationSelectionKey('source', 'orders')).not.toBe(
      relationSelectionKey('bronze', 'orders'),
    );
    expect(relationSelectionKey('a.b', 'c')).not.toBe(
      relationSelectionKey('a', 'b.c'),
    );
  });
});

describe('Bronze table selection safety', () => {
  it('starts with no discovered table selected', () => {
    expect(initialBronzeSelection()).toEqual([]);
    expect(canIngestBronzeSelection(initialBronzeSelection(), false, false)).toBe(
      false,
    );
  });

  it('enables ingestion only after an explicit individual selection', () => {
    const selected = toggleBronzeTable(initialBronzeSelection(), 'orders');

    expect(selected).toEqual(['orders']);
    expect(canIngestBronzeSelection(selected, false, false)).toBe(true);
  });

  it('keeps Select All and Deselect All as explicit actions', () => {
    const available = ['orders', 'customers'];
    const selected = toggleAllBronzeTables(initialBronzeSelection(), available);

    expect(selected).toEqual(available);
    expect(toggleAllBronzeTables(selected, available)).toEqual([]);
  });
});
