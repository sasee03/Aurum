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
import { bronzeDiscoveryErrorMessage, withConnectorFlowQuery } from './connectorFlow';
import { ApiError } from './apiErrors';

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

  it('preserves connector session and selected relation across flow navigation', () => {
    const params = new URLSearchParams({
      connectionId: 'conn_abc',
      database: 'aurum',
      schema: 'source',
      table: 'online_retail_uci',
    });

    const path = withConnectorFlowQuery('/projects/demo/bronze', params);

    expect(path).toBe(
      '/projects/demo/bronze?connectionId=conn_abc&database=aurum&schema=source&table=online_retail_uci',
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

describe('Bronze discovery error states', () => {
  it('shows connector expiry as an error, not an empty schema state', () => {
    const message = bronzeDiscoveryErrorMessage(
      new ApiError(
        'Connection session expired or unknown. Re-test the connection (password is not persisted).',
        404,
        'connection_not_found',
      ),
      true,
    );

    expect(message).toContain('Connection session expired or unknown');
    expect(message).not.toContain('No tables found');
  });

  it('keeps default source discovery fallback for non-connector Bronze flows', () => {
    const message = bronzeDiscoveryErrorMessage(new Error('network'), false);

    expect(message).toBe('Failed to discover source tables from backend API.');
  });
});
