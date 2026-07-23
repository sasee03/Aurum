import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchRuns, uploadDatasetCsv, CsvUploadError, normalizeApiUrl } from './aurumApi';
import { ApiError, API_UNAVAILABLE } from '../utils/apiErrors';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

describe('aurumApi error parsing', () => {
  beforeEach(() => {
    fetchMock.mockClear();
  });

  it('parses a 404 with structured message', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Run not found.' })
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Run not found.');
      expect(e.httpStatus).toBe(404);
      expect(e.errorCode).toBeUndefined();
    }
  });

  it('parses a 422 with structured detail.message', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: { message: 'No dataset_config retained for this run.' } })
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('No dataset_config retained for this run.');
      expect(e.httpStatus).toBe(422);
    }
  });

  it('parses a 500 with error and message fields', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: 'INTERNAL_ERROR', message: 'Database disconnected' })
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Database disconnected');
      expect(e.httpStatus).toBe(500);
      expect(e.errorCode).toBe('INTERNAL_ERROR');
    }
  });

  it('parses a 500 with nested detail.error', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: { error: 'NESTED_ERROR', message: 'Nested failure' } })
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Nested failure');
      expect(e.httpStatus).toBe(500);
      expect(e.errorCode).toBe('NESTED_ERROR');
    }
  });

  it('handles a network-unreachable / CORS style failure or plain text gracefully (rejection)', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe(API_UNAVAILABLE);
      expect(e.httpStatus).toBeUndefined();
    }
  });

  it('handles a resolved non-2xx response with unparseable body with status-aware wording', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => { throw new Error('Not JSON'); }
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Request failed (HTTP 502)');
      expect(e.httpStatus).toBe(502);
    }
  });

  it('handles a malformed JSON error body safely', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ random: 'stuff' })
    });

    try {
      await fetchRuns();
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Request failed (HTTP 400)');
      expect(e.httpStatus).toBe(400);
    }
  });

  it('uploadDatasetCsv handles non-JSON response securely', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 413,
      json: async () => { throw new Error('Payload Too Large HTML'); }
    });

    try {
      await uploadDatasetCsv(new File([], 'test.csv'));
      expect.fail('Should have thrown ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.userMessage).toBe('Request failed (HTTP 413)');
      expect(e.httpStatus).toBe(413);
    }
  });

  it('preserves CsvUploadError behavior for schema_match: false', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        schema_match: false,
        error: 'Schema mismatch',
        expected_columns: ['id'],
        missing_columns: ['id']
      })
    });

    try {
      await uploadDatasetCsv(new File([], 'test.csv'));
      expect.fail('Should have thrown CsvUploadError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(CsvUploadError);
      expect(e.mismatch.schema_match).toBe(false);
      expect(e.mismatch.error).toBe('Schema mismatch');
    }
  });

  it('sourceConnect handles successful response', async () => {
    const { sourceConnect } = await import('./aurumApi');
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ connected: true, message: 'Connected' }),
    });

    const res = await sourceConnect({
      host: 'localhost',
      port: 5432,
      database: 'aurum',
      user: 'postgres',
      password: 'secretpassword',
    });
    expect(res.connected).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/source/connect',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          host: 'localhost',
          port: 5432,
          database: 'aurum',
          user: 'postgres',
          password: 'secretpassword',
        }),
      }),
    );
  });

  it('sourceConnect throws status-aware ApiError on 401, 404, 503, and 500', async () => {
    const { sourceConnect } = await import('./aurumApi');

    // 401 Auth Failed
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ error: 'AUTHENTICATION_FAILED', message: "Authentication failed for user 'postgres'" }),
    });
    try {
      await sourceConnect({ host: 'localhost', port: 5432, database: 'aurum', user: 'postgres', password: 'bad' });
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(401);
      expect(e.userMessage).toBe("Authentication failed for user 'postgres'");
    }

    // 404 Database Not Found
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ error: 'DATABASE_NOT_FOUND', message: "Database 'testdb' does not exist on server" }),
    });
    try {
      await sourceConnect({ host: 'localhost', port: 5432, database: 'testdb', user: 'postgres', password: 'secret' });
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(404);
      expect(e.userMessage).toBe("Database 'testdb' does not exist on server");
    }

    // 503 Host Unreachable
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ error: 'HOST_UNREACHABLE', message: "Host/port unreachable at 'badhost:5432'" }),
    });
    try {
      await sourceConnect({ host: 'badhost', port: 5432, database: 'aurum', user: 'postgres', password: 'secret' });
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(503);
      expect(e.userMessage).toBe("Host/port unreachable at 'badhost:5432'");
    }

    // 500 Internal Exception
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: 'INTERNAL_ERROR', message: 'psycopg2.OperationalError: raw db crash' }),
    });
    try {
      await sourceConnect({ host: 'localhost', port: 5432, database: 'aurum', user: 'postgres', password: 'bad' });
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(500);
      expect(e.userMessage).toBe('psycopg2.OperationalError: raw db crash');
    }
  });

  it('transformSaveRules encodes identifiers, sends POST with body, and parses errors', async () => {
    const { transformSaveRules } = await import('./aurumApi');

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ status: 'success', message: 'Rules saved successfully' }),
    });

    const saveRes = await transformSaveRules('orders/table 1', ['Rule 1', 'Rule 2']);
    expect(saveRes.status).toBe('success');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/transform/rules',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ table_name: 'orders/table 1', rules: ['Rule 1', 'Rule 2'] }),
      }),
    );

    // Handles 400 validation error
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'Duplicate rules are not allowed.' }),
    });

    try {
      await transformSaveRules('orders', ['Rule 1', 'Rule 1']);
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(400);
      expect(e.userMessage).toBe('Duplicate rules are not allowed.');
    }
  });

  it('transformGetRules encodes table identifier in URL and handles errors', async () => {
    const { transformGetRules } = await import('./aurumApi');

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ table_name: 'orders/special', rules: ['Filter nulls'] }),
    });

    const res = await transformGetRules('orders/special');
    expect(res.table_name).toBe('orders/special');
    expect(res.rules).toEqual(['Filter nulls']);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/transform/rules/orders%2Fspecial',
      expect.objectContaining({
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }),
    );
  });

  it('transformGenerate handles 503 generator unavailable cleanly', async () => {
    const { transformGenerate } = await import('./aurumApi');

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'SQL generator is currently unavailable (LLM integration pending).' }),
    });

    try {
      await transformGenerate('orders');
      expect.fail('Should throw 503 ApiError');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(503);
      expect(e.userMessage).toBe('SQL generator is currently unavailable (LLM integration pending).');
    }
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/transform/generate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ table_name: 'orders' }),
      }),
    );
  });

  it('buildUrl normalizes base URL and path correctly', async () => {
    const { buildUrl } = await import('./aurumApi');
    expect(buildUrl('/api/v1/health')).toBe('/api/v1/health');
    expect(buildUrl('api/v1/health')).toBe('/api/v1/health');
  });

  it('transformReview encodes runId in URL and parses executable and executed state correctly', async () => {
    const { transformReview } = await import('./aurumApi');

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        run_id: 'run/12345',
        table_name: 'orders',
        planned_changes: { summary: 'Planned 1 step', rules: ['Step 1: Rule 1'], cte_steps_detected: 1, attribution_safe: true },
        sql_text: 'SELECT 1;',
        executed: false,
        executable: false,
        status: 'PENDING',
        generator_provenance: 'untrusted_legacy',
        message: 'SQL review is untrusted or non-executable.',
      }),
    });

    const revRes = await transformReview('run/12345');
    expect(revRes.run_id).toBe('run/12345');
    expect(revRes.executed).toBe(false);
    expect(revRes.executable).toBe(false);
    expect(revRes.generator_provenance).toBe('untrusted_legacy');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/transform/review/run%2F12345',
      expect.objectContaining({
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      }),
    );
  });

  it('transformExecute encodes runId and handles attribution_available state', async () => {
    const { transformExecute } = await import('./aurumApi');

    // Handles 409 conflict
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'Execution already in progress for this run.' }),
    });

    try {
      await transformExecute('run_12345');
      expect.fail('Should throw');
    } catch (e: any) {
      expect(e).toBeInstanceOf(ApiError);
      expect(e.httpStatus).toBe(409);
      expect(e.userMessage).toBe('Execution already in progress for this run.');
    }
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/transform/execute/run_12345',
      expect.objectContaining({ method: 'POST' }),
    );

    // Handles success retry response with attribution_available: true
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        status: 'success',
        run_id: 'run_12345',
        table_name: 'orders',
        attribution_log: ['Initial Bronze Rows: 100'],
        attribution_available: true,
        message: "Transformation for 'orders' was already executed and promoted.",
      }),
    });

    const retryRes = await transformExecute('run_12345');
    expect(retryRes.status).toBe('success');
    expect(retryRes.attribution_available).toBe(true);
    expect(retryRes.attribution_log).toEqual(['Initial Bronze Rows: 100']);

    // Handles legacy response with attribution_available: false
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        status: 'success',
        run_id: 'run_legacy_1',
        table_name: 'orders',
        attribution_log: null,
        attribution_available: false,
        message: "Transformation for 'orders' was already executed and promoted.",
      }),
    });

    const legacyRes = await transformExecute('run_legacy_1');
    expect(legacyRes.status).toBe('success');
    expect(legacyRes.attribution_available).toBe(false);
    expect(legacyRes.attribution_log).toBeNull();
  });
});

describe('normalizeApiUrl', () => {
  it('handles empty or unset base URL', () => {
    expect(normalizeApiUrl('', '/api/v1/transform/rules')).toBe('/api/v1/transform/rules');
    expect(normalizeApiUrl('   ', 'api/v1/transform/rules')).toBe('/api/v1/transform/rules');
  });

  it('normalizes base URL with or without trailing slash', () => {
    expect(normalizeApiUrl('http://localhost:8000', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
    expect(normalizeApiUrl('http://localhost:8000/', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
  });

  it('prevents double /api when base URL ends with /api', () => {
    expect(normalizeApiUrl('http://localhost:8000/api', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
    expect(normalizeApiUrl('http://localhost:8000/api/', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
  });

  it('prevents double /api/v1 when base URL ends with /api/v1', () => {
    expect(normalizeApiUrl('http://localhost:8000/api/v1', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
    expect(normalizeApiUrl('http://localhost:8000/api/v1/', '/api/v1/transform/rules')).toBe('http://localhost:8000/api/v1/transform/rules');
  });
});
