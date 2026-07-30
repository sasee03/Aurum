import { describe, it, expect } from 'vitest';
import { classifyTable, formatFriendlyName } from './datasetExplorerUtils';

describe('datasetExplorerUtils', () => {
  describe('classifyTable', () => {
    it('classifies aurum_session_* schemas as internal', () => {
      expect(classifyTable('aurum_session_123', 'raw_orders', 'postgresql')).toBe('internal');
    });

    it('classifies source schemas as source', () => {
      expect(classifyTable('source', 'online_retail_uci', 'postgresql')).toBe('source');
      expect(classifyTable('public', 'users', 'postgresql')).toBe('source');
    });

    it('classifies bronze, silver, gold layers as pipeline', () => {
      expect(classifyTable('public', 'bronze_orders', 'postgresql')).toBe('pipeline');
      expect(classifyTable('bronze_schema', 'orders', 'postgresql')).toBe('pipeline');
      expect(classifyTable('public', 'my_table', 'silver')).toBe('pipeline');
      expect(classifyTable('public', 'my_table', 'gold_candidates')).toBe('pipeline');
    });
  });

  describe('formatFriendlyName', () => {
    it('formats friendly names correctly', () => {
      expect(formatFriendlyName('online_retail_uci')).toBe('Online Retail UCI');
      expect(formatFriendlyName('src_products')).toBe('Products');
      expect(formatFriendlyName('src_customers')).toBe('Customers');
      expect(formatFriendlyName('gold_country_revenue')).toBe('Country Revenue — Gold');
      expect(formatFriendlyName('bronze_orders')).toBe('Orders — Bronze');
    });

    it('preserves acronyms', () => {
      expect(formatFriendlyName('raw_user_id')).toBe('Raw User ID');
      expect(formatFriendlyName('product_sku_list')).toBe('Product SKU List');
      expect(formatFriendlyName('kpi_metrics')).toBe('KPI Metrics');
      expect(formatFriendlyName('sql_queries')).toBe('SQL Queries');
    });
  });
});
