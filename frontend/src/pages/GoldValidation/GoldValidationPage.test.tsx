import { describe, expect, it, vi, beforeEach } from 'vitest';
import { ApiError } from '@/utils/apiErrors';
import {
  approveGoldSql,
  executeGoldSql,
  generateGoldSql,
  promoteGoldSql,
} from '@/lib/aurumApi';
import {
  canSubmitGoldGenerate,
  goldGenerateButtonLabel,
  goldWorkflowError,
} from './goldValidationUx';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

describe('GoldValidationPage interaction helpers', () => {
  beforeEach(() => {
    fetchMock.mockClear();
  });

  it('shows explicit Generate and Review loading copy', () => {
    expect(goldGenerateButtonLabel(true, null)).toBe('Understanding requirement...');
    expect(goldGenerateButtonLabel(true, 'Preparing review...')).toBe('Preparing review...');
    expect(goldGenerateButtonLabel(false, null)).toBe('Generate and Review');
  });

  it('prevents duplicate Gold Generate submission while generating', () => {
    expect(canSubmitGoldGenerate({
      generating: true,
      selectedSilverTable: 'online_retail_uci',
      targetTableName: 'gold_summary',
      businessRequirement: 'Count rows by country.',
    })).toBe(false);

    expect(canSubmitGoldGenerate({
      generating: false,
      selectedSilverTable: 'online_retail_uci',
      targetTableName: 'gold_summary',
      businessRequirement: 'Count rows by country.',
    })).toBe(true);
  });

  it('maps Gold schema permission errors to product-readable copy', () => {
    const described = goldWorkflowError(
      new ApiError('Failed to check table existence: permission denied for schema gold', 500),
      'Failed to generate and review the controlled Gold proposal.',
    );

    expect(described.message).toBe(
      'Gold could not prepare the result because the application does not have access to the configured Gold schema.',
    );
    expect(described.detail).toContain('permission denied for schema gold');
  });

  it('keeps GOLD_UNAVAILABLE visible without hiding technical detail', () => {
    const described = goldWorkflowError(
      new ApiError('GOLD_UNAVAILABLE', 503),
      'Failed to generate and review the controlled Gold proposal.',
    );

    expect(described.message).toBe('Gold authority is not configured in the local backend runtime.');
    expect(described.detail).toBe('GOLD_UNAVAILABLE');
  });

  it('keeps the existing Gold generate API contract unchanged', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        run_id: 'run_1',
        table_name: 'gold_summary',
        sql_text: 'select 1',
        planned_changes: {},
        status: 'PENDING',
        review_revision: 'abc',
        generator_provenance: 'manual_controlled_gold_v1',
      }),
    });

    await generateGoldSql({
      target_table_name: 'gold_summary',
      silver_table_names: ['online_retail_uci'],
      business_requirement: 'Count rows by country.',
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/gold/generate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      target_table_name: 'gold_summary',
      silver_table_names: ['online_retail_uci'],
      business_requirement: 'Count rows by country.',
    });
  });

  it('keeps Gold lifecycle actions on separate endpoints', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'approved',
          run_id: 'run_1',
          review_revision: 'a'.repeat(64),
          approved_revision: 'b'.repeat(64),
          approved_at: '2026-07-30T00:00:00Z',
          overwrite_authorized: false,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'PROMOTING',
          run_id: 'run_1',
          execution_claim_id: 'exec_1',
          candidate: { schema: 'gold_candidates', table: 'candidate_1' },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          status: 'PROMOTED',
          run_id: 'run_1',
          promotion_claim_id: 'promote_1',
          promotion_committed_at: '2026-07-30T00:00:01Z',
          target: { schema: 'gold', table: 'gold_summary' },
        }),
      });

    await approveGoldSql('run_1', { review_revision: 'a'.repeat(64), overwrite: false });
    await executeGoldSql('run_1', { overwrite: false });
    await promoteGoldSql('run_1');

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/gold/approve/run_1',
      '/api/v1/gold/execute/run_1',
      '/api/v1/gold/promote/run_1',
    ]);
  });
});
