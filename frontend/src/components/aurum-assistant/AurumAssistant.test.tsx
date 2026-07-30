/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AurumAssistantDrawer } from './AurumAssistantDrawer';
import { AurumAssistantMessage } from './AurumAssistantMessage';
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
        answer: 'This dataset is currently represented by source.live_e2e_customers.',
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
      answer: 'Gold status is PROMOTED.',
      grounded: true,
      status: 'answered',
      evidence: [{ path: 'gold.status', value: 'PROMOTED' }],
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('Gold status is PROMOTED');
    expect(markup).toContain('Evidence');
    expect(markup).not.toContain('Verified Aurum facts');
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
    expect(markup).toContain('I do not have enough information in the current Aurum context to answer that.');
    expect(markup).not.toContain('Assistant temporarily unavailable');
    expect(markup).not.toContain('Retry');
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
      answer: 'This dataset is currently represented by source.live_e2e_customers.',
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

  it('9. no run_id shows contextual guidance', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantDrawer
        open
        onClose={() => {}}
        page="bronze"
        layer="bronze"
      />,
    );

    expect(markup).toContain('No Bronze run selected');
    expect(markup).toContain('No Bronze run is selected yet. Complete Bronze ingestion or open an existing run to ask grounded questions.');
  });

  it('10. no run_id does not show Assistant unavailable or run-specific suggested questions', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantDrawer
        open
        onClose={() => {}}
        page="bronze"
        layer="bronze"
      />,
    );

    expect(markup).not.toContain('Assistant temporarily unavailable');
    expect(markup).not.toContain('Aurum Assistant is unavailable');
    expect(markup).not.toContain('What is the status of Bronze ingestion?');
    expect(markup).not.toContain('Suggested Questions');
  });

  it('11. genuine 503 renders service-unavailable state with Retry', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantMessage
        role="assistant"
        error="Assistant provider unavailable or not configured."
        canRetry
        onRetry={() => {}}
      />,
    );

    expect(markup).toContain('Assistant temporarily unavailable');
    expect(markup).toContain('Assistant provider unavailable or not configured.');
    expect(markup).toContain('Retry');
    expect(markup).not.toContain('Aurum Assistant is unavailable');
  });

  it('12. Retry appears only for genuine service failure', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantMessage
        role="assistant"
        error="Assistant could not answer with the current context."
      />,
    );

    expect(markup).toContain('Assistant could not answer');
    expect(markup).not.toContain('Retry');
    expect(markup).not.toContain('Assistant temporarily unavailable');
  });

  it('13. exact valid run context is displayed with friendly name and technical run ID', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantDrawer
        open
        onClose={() => {}}
        page="bronze"
        layer="bronze"
        runId="run_abcd1234"
        selectedTable="online_retail_uci"
      />,
    );

    expect(markup).toContain('Bronze run selected');
    expect(markup).toContain('Online Retail UCI');
    expect(markup).not.toContain('online_retail_uci');
    expect(markup).toContain('run_abcd1234');
    expect(markup).not.toContain('Bronze / Bronze / No Run Context');
  });

  it('14. no latest-run substitution is offered from the no-run UI state', () => {
    const markup = renderToStaticMarkup(
      <AurumAssistantDrawer
        open
        onClose={() => {}}
        page="bronze"
        layer="bronze"
      />,
    );

    expect(markup).toContain('Select a run to ask grounded questions');
    expect(markup).toContain('disabled=""');
    expect(markup).not.toContain('run_b720f22b3804');
  });

  it('15. empty Evidence panel is not rendered', () => {
    const response: AssistantResponse = {
      answer: 'Bronze run is selected.',
      grounded: true,
      status: 'answered',
      evidence: [],
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('Bronze run is selected.');
    expect(markup).not.toContain('Evidence');
  });

  it('renders the approved insufficient-information fallback for an exact run', () => {
    const response: AssistantResponse = {
      answer: '',
      grounded: false,
      status: 'insufficient_information',
    };

    const markup = renderToStaticMarkup(<AurumAssistantResponseRenderer response={response} />);

    expect(markup).toContain('I do not have enough information in the selected Aurum run to answer that.');
  });

  it('16. Assistant 503 responses retain status for service-failure mapping', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: 'ASSISTANT_GEMINI_UNAVAILABLE' }),
    });

    await expect(askAurumAssistant({
      message: 'What is the status of Bronze ingestion?',
      run_id: 'run_abcd1234',
    })).rejects.toMatchObject({
      httpStatus: 503,
      userMessage: 'ASSISTANT_GEMINI_UNAVAILABLE',
    });
  });

  it('17. Assistant launcher uses a shared bottom safe-zone offset', () => {
    const css = readFileSync(new URL('./aurum-assistant.css', import.meta.url), 'utf8');
    const pageAssistant = readFileSync(new URL('../common/PageAssistant.tsx', import.meta.url), 'utf8');

    expect(pageAssistant).toContain('[data-assistant-safe-zone="bottom-action"]');
    expect(css).toContain('bottom: calc(var(--aa-safe-bottom, 0px) + 24px);');
  });

  it('18. Assistant drawer avoids covering workflow CTAs while open', () => {
    const css = readFileSync(new URL('./aurum-assistant.css', import.meta.url), 'utf8');

    expect(css).toContain('height: calc(100% - var(--aa-safe-bottom, 0px));');
    expect(css).toContain('margin-bottom: var(--aa-safe-bottom, 0px);');
    expect(css).toContain('pointer-events: none;');
    expect(css).toContain('pointer-events: auto;');
  });

  it('19. Bronze, Silver, and Gold workflow footers reserve Assistant safe space', () => {
    const bronze = readFileSync(new URL('../../pages/BronzeValidation/BronzeValidationPage.tsx', import.meta.url), 'utf8');
    const silver = readFileSync(new URL('../../pages/SilverValidation/SilverValidationPage.tsx', import.meta.url), 'utf8');
    const gold = readFileSync(new URL('../../pages/GoldValidation/GoldValidationPage.tsx', import.meta.url), 'utf8');

    expect(bronze).toContain('data-assistant-safe-zone="bottom-action"');
    expect(silver).toContain('data-assistant-safe-zone="bottom-action"');
    expect(gold).toContain('data-assistant-safe-zone="bottom-action"');
  });
});
