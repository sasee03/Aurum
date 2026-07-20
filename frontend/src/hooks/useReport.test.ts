import { describe, it, expect } from 'vitest';
import { isUploadRunId, isConnectorRunId, isPersistedUserRunId } from './useReport';

describe('useReport source-label helpers', () => {
  it('identifies CSV upload runs correctly', () => {
    expect(isUploadRunId('upload_12345')).toBe(true);
    expect(isUploadRunId('connector_12345')).toBe(false);
    expect(isUploadRunId('demo_run')).toBe(false);
  });

  it('identifies connector runs correctly', () => {
    expect(isConnectorRunId('connector_12345')).toBe(true);
    expect(isConnectorRunId('upload_12345')).toBe(false);
    expect(isConnectorRunId('demo_run')).toBe(false);
  });

  it('identifies persisted user runs correctly', () => {
    expect(isPersistedUserRunId('upload_12345')).toBe(true);
    expect(isPersistedUserRunId('connector_12345')).toBe(true);
    expect(isPersistedUserRunId('demo_run')).toBe(false);
    expect(isPersistedUserRunId(null)).toBe(false);
    expect(isPersistedUserRunId(undefined)).toBe(false);
  });
});
