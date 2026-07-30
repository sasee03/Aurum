/// <reference types="node" />

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { ApiError } from '@/utils/apiErrors';
import {
  approveGoldSql,
  executeGoldSql,
  generateGoldSql,
  promoteGoldSql,
  type ReviewGoldResponse,
} from '@/lib/aurumApi';
import {
  canSubmitGoldGenerate,
  formattedGoldCell,
  goldChartRows,
  goldExpressionLabel,
  goldGenerateButtonLabel,
  goldResultSummary,
  goldWorkflowError,
  previewMatchesPromotedRelation,
  promotedRelationFrom,
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

  it('maps temporary Gold AI runtime failure to a focused product message', () => {
    const described = goldWorkflowError(
      new ApiError('GOLD_AI_UNAVAILABLE', 503),
      'Failed to generate and review the controlled Gold proposal.',
    );

    expect(described.message).toBe('Gold interpretation is temporarily unavailable in the connected runtime.');
    expect(described.detail).toBe('GOLD_AI_UNAVAILABLE');
  });

  it('calls the final structured AI Gold generate route', async () => {
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
      source: { schema: 'silver', table: 'online_retail_uci' },
      target_table_name: 'gold_summary',
      business_requirement: 'Count rows by country.',
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/gold/ai/generate');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      source: { schema: 'silver', table: 'online_retail_uci' },
      target_table_name: 'gold_summary',
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

  it('clears Gold preview state when a new requirement starts', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(source).toContain('function resetGeneratedState()');
    expect(source).toContain('setGoldPreview(null);');
    expect(source).toContain('setBusinessRequirement(event.target.value);');
    expect(source).toContain('resetGeneratedState();');
  });

  it('does not load a Gold result table before promotion', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(source).toContain('disabled={!promotion || loadingLiveData}');
    expect(source).toContain('Publish the Gold result to view business-ready data.');
    expect(source).toContain('await loadLiveGoldData(response, workflowRevision);');
  });

  it('accepts preview only when it matches the exact promoted relation', () => {
    const promoted = promotedRelationFrom({
      target: { schema: 'gold', table: 'country_sales' },
    });

    expect(promoted).toEqual({ schema: 'gold', table: 'country_sales' });
    expect(previewMatchesPromotedRelation(
      { schema: 'gold', table: 'country_sales' },
      promoted!,
    )).toBe(true);
    expect(previewMatchesPromotedRelation(
      { schema: 'silver', table: 'online_retail_uci' },
      promoted!,
    )).toBe(false);
  });

  it('renders an aggregated two-column result summary generically', () => {
    const review = {
      run_id: 'run_structured',
      table_name: 'country_sales',
      planned_changes: {
        dimension: 'country',
        metric: {
          aggregation: 'sum',
          expression: {
            type: 'binary',
            operator: 'multiply',
            left_column: 'quantity',
            right_column: 'unit_price',
          },
          alias: 'total_sales',
        },
      },
      sql_text: '',
      review_revision: 'a'.repeat(64),
      approved_revision: null,
      executed: false,
      executable: true,
      status: 'PENDING',
      generator_provenance: 'structured_deterministic_gold_v1',
      message: '',
    } satisfies ReviewGoldResponse;

    expect(goldResultSummary(review)).toEqual({
      title: 'Total Sales by Country',
      metric: 'total_sales',
      groupedBy: 'country',
      calculation: 'quantity * unit_price',
      aggregation: 'SUM',
    });
    expect(goldExpressionLabel(review.planned_changes.metric.expression)).toBe('quantity * unit_price');
  });

  it('formats returned Gold preview rows without fabricating currency semantics', () => {
    expect(formattedGoldCell(12345.67891)).toBe('12,345.6789');
    expect(formattedGoldCell(null)).toBe('NULL');
    expect(formattedGoldCell('United Kingdom')).toBe('United Kingdom');
  });

  it('derives chart rows only from actual Gold preview rows', () => {
    const chart = goldChartRows({
      schema: 'gold',
      table: 'country_sales',
      row_count: 2,
      column_count: 2,
      columns: [
        { name: 'country', data_type: 'text', nullable: false },
        { name: 'total_sales', data_type: 'numeric', nullable: true },
      ],
      rows: [
        { country: 'United Kingdom', total_sales: 100 },
        { country: 'France', total_sales: 25 },
      ],
    }, 'total_sales');

    expect(chart).toEqual([
      { label: 'United Kingdom', value: 100, widthPct: 100 },
      { label: 'France', value: 25, widthPct: 25 },
    ]);
    expect(goldChartRows(null, 'total_sales')).toEqual([]);
  });

  it('does not hardcode raw invoice columns as a filter', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(source).not.toContain('invoice_no');
    expect(source).not.toContain('stock_code');
    expect(source).not.toContain('unit_price');
    expect(source).not.toContain('customer_id');
  });

  it('cannot display a previous successful result after failed generation starts', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');
    const generateStart = source.indexOf('async function handleGenerate()');
    const resetCall = source.indexOf('resetGeneratedState();', generateStart);
    const firstAwait = source.indexOf('await checkGoldName', generateStart);

    expect(resetCall).toBeGreaterThan(generateStart);
    expect(resetCall).toBeLessThan(firstAwait);
  });

  it('invalidates an in-flight workflow when the source, requirement, or route context changes', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(source).toContain('workflowRevisionRef.current += 1;');
    expect(source).toContain('if (workflowRevisionRef.current !== workflowRevision) return;');
    expect(source).toContain('workflowContextKey');
  });

  it('keeps Gold provenance and revisions in secondary technical details', () => {
    const source = readFileSync(new URL('./GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(source).toContain('Review Revision');
    expect(source).toContain('Approval Revision');
    expect(source).toContain('Generator / Model');
    expect(source).toContain('Provenance');
  });
});
