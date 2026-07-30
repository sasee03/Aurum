/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { classifyTable, formatFriendlyName } from './datasetExplorerUtils';
import {
  isCurrentDatasetDiscovery,
  reconcileDatasetSelection,
} from './datasetExplorerState';

const pageSource = readFileSync(new URL('./DatasetExplorerPage.tsx', import.meta.url), 'utf8');

describe('Dataset Explorer product closure', () => {
  it('places source, pipeline, and internal relations in distinct categories', () => {
    expect(classifyTable('source', 'online_retail_uci', 'postgresql')).toBe('source');
    expect(classifyTable('silver', 'clean_orders', 'postgresql')).toBe('pipeline');
    expect(classifyTable('aurum_session_42', 'state', 'postgresql')).toBe('internal');
  });

  it('keeps the internal section collapsed until the Advanced control is used', () => {
    expect(pageSource).toContain("const [showInternal, setShowInternal] = useState(false);");
    expect(pageSource).toContain("{showInternal && internalTables.map");
    expect(pageSource).toContain('Show internal relations');
  });

  it('prevents internal and missing relations from remaining selected', () => {
    const selected = new Set(['source.orders', 'aurum_session_42.state', 'missing.table']);
    const reconciled = reconcileDatasetSelection(selected, [
      { id: 'source.orders', schema: 'source', name: 'orders', owner: 'postgresql' },
      { id: 'aurum_session_42.state', schema: 'aurum_session_42', name: 'state', owner: 'postgresql' },
    ]);

    expect([...reconciled]).toEqual(['source.orders']);
  });

  it('clears selection and preview before a connection or discovery refresh', () => {
    expect(pageSource).toContain('setSelectedIds(new Set());');
    expect(pageSource).toContain('setPreview(null);');
    expect(pageSource).toContain('setPreviewingTableId(null);');
  });

  it('rejects stale asynchronous discovery and preview responses', () => {
    expect(isCurrentDatasetDiscovery(4, 5)).toBe(false);
    expect(isCurrentDatasetDiscovery(5, 5)).toBe(true);
    expect(pageSource).toContain('isCurrentDatasetDiscovery(requestId, discoveryRequestRef.current)');
    expect(pageSource).toContain('isCurrentDatasetDiscovery(discoveryRequest, discoveryRequestRef.current)');
  });

  it('uses a friendly dataset name while preserving physical identity as secondary text', () => {
    expect(formatFriendlyName('online_retail_uci')).toBe('Online Retail UCI');
    expect(formatFriendlyName('bronze_orders')).toBe('Orders');
    expect(pageSource).toContain('Selected dataset');
    expect(pageSource).toContain('title={`${selectedRelation.schema}.${selectedRelation.name}`}');
  });

  it('keeps the normal CTA singular and independent of physical identifiers', () => {
    expect(pageSource).toContain('Use this dataset');
    expect(pageSource).not.toContain('Use selected datasets');
    expect(pageSource).not.toContain('selectedIds.size > 0 && (');
  });

  it('shows the required honest empty-source state without fabricating UCI', () => {
    expect(pageSource).toContain('No source datasets found');
    expect(pageSource).toContain('Aurum did not receive any eligible source relations for this connection.');
    expect(pageSource).toContain('Generated and internal relations are available under Advanced.');
    expect(pageSource).toContain('Back to Connect');
    expect(pageSource).not.toContain("'Online Retail UCI'");
  });

  it('never renders a placeholder dataset label', () => {
    expect(pageSource).not.toContain('???');
  });
});
