import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fetchRuns, uploadDatasetCsv, CsvUploadError } from './aurumApi';
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
});
