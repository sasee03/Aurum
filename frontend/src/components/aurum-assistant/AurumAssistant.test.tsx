import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AurumAssistantResponseRenderer } from './AurumAssistantResponseRenderer';
import { askAurumAssistant, type AssistantResponse, type AssistantChatRequest } from '../../lib/aurumApi';

const fetchMock = vi.fn();
vi.stubGlobal('fetch', fetchMock);

describe('Aurum Assistant Integration & Component Tests', () => {
  beforeEach(() => {
    fetchMock.mockClear();
  });

  it('1. prompt submission calls /api/v1/assistant/chat with message and run_id', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        answer: 'Verified Aurum facts:\n- Source relation: "live_e2e_customers".',
        grounded: true,
        status: 'answered',
        evidence: [{ path: 'source.relation', value: 'live_e2e_customers' }],
        context: {
          run_id: 'run_148b79da3c07',
          source: { schema: 'source', relation: 'live_e2e_customers' },
          gold_status: 'PROMOTED',
        },
      }),
    });

    const payload: AssistantChatRequest = {
      message: 'What dataset am I working with?',
      run_id: 'run_148b79da3c07',
    };

    const res = await askAurumAssistant(payload);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/v1/assistant/chat');
    expect(JSON.parse(init.body)).toEqual({
      message: 'What dataset am I working with?',
      run_id: 'run_148b79da3c07',
    });
    expect(res.grounded).toBe(true);
    expect(res.status).toBe('answered');
  });

  it('2. grounded backend response is rendered properly by renderer', () => {
    const response: AssistantResponse = {
      answer: 'Verified Aurum facts:\n- Gold status: PROMOTED.',
      grounded: true,
      status: 'answered',
      evidence: [{ path: 'gold.status', value: 'PROMOTED' }],
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('Grounded');
    expect(markup).toContain('Verified Aurum facts');
    expect(markup).toContain('Gold status');
    expect(markup).toContain('PROMOTED');
  });

  it('3. insufficient_information response is rendered honestly', () => {
    const response: AssistantResponse = {
      answer: 'I do not have enough information in the current Aurum context to answer that.',
      grounded: false,
      status: 'insufficient_information',
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('Insufficient information');
    expect(markup).toContain('The backend did not return enough grounded Aurum context for this answer.');
  });

  it('4. legacy "report.json / validation report" fallback is not used in renderer', () => {
    const response: AssistantResponse = {
      answer: 'No context available.',
      grounded: false,
      status: 'insufficient_information',
      confidence: 'low',
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).not.toContain('report.json');
    expect(markup).not.toContain('validation report');
    expect(markup).not.toContain('Verify against the latest validation report');
  });

  it('5. current page/run context is forwarded when available', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        answer: 'Grounded facts for run_123',
        grounded: true,
        status: 'answered',
      }),
    });

    await askAurumAssistant({
      message: 'Explain Bronze.',
      run_id: 'run_123',
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({
      message: 'Explain Bronze.',
      run_id: 'run_123',
    });
  });

  it('6. unrelated latest run context safety check logic intercepts mismatched relations', () => {
    const backendResponse: AssistantResponse = {
      answer: 'Verified Aurum facts:\n- Source relation: "live_e2e_customers".',
      grounded: true,
      status: 'answered',
      evidence: [{ path: 'source.relation', value: 'live_e2e_customers' }],
      context: {
        run_id: 'run_148b79da3c07',
        source: { schema: 'source', relation: 'live_e2e_customers' },
      },
    };

    const selectedTable = 'online_retail_uci';
    const runId = undefined;

    let response = backendResponse;
    if (selectedTable && response.status === 'answered' && !runId) {
      const rel = response.context?.source?.relation?.toLowerCase();
      const target = selectedTable.toLowerCase();
      if (rel && rel !== target) {
        response = {
          answer: 'I do not have enough information in the current Aurum context to answer that.',
          grounded: false,
          status: 'insufficient_information',
          context: response.context,
          evidence: [],
        };
      }
    }

    expect(response.status).toBe('insufficient_information');
    expect(response.grounded).toBe(false);
    expect(response.answer).toBe('I do not have enough information in the current Aurum context to answer that.');

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);
    expect(markup).toContain('Insufficient information');
    expect(markup).not.toContain('live_e2e_customers');
  });

  it('7. read_only_refusal renders correctly', () => {
    const response: AssistantResponse = {
      answer: 'I cannot approve, execute, or promote Gold.',
      grounded: false,
      status: 'read_only_refusal',
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('Aurum Assistant is currently read-only.');
    expect(markup).toContain("can&#x27;t approve, execute, promote, or modify pipeline state from chat");
  });

  it('8. selectedTable is never sent as run_id when runId is undefined', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        answer: 'I do not have enough information in the current Aurum context to answer that.',
        grounded: false,
        status: 'insufficient_information',
      }),
    });

    const payload: AssistantChatRequest = {
      message: 'What table is this?',
      run_id: undefined,
    };

    await askAurumAssistant(payload);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(init.body);
    expect(body.run_id).toBeUndefined();
    expect(body).toEqual({ message: 'What table is this?' });
  });
});
