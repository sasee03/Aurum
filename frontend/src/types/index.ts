export type ProjectStatus = 'PASS' | 'WARNING' | 'FAILED';
export type Environment = 'Development' | 'QA' | 'Production';
export type ConnectorType = 'csv' | 'postgresql';

export interface Project {
  id: string;
  name: string;
  businessDomain: string;
  description: string;
  environment: Environment;
  lastOpened: string;
  datasetCount: number;
  status: ProjectStatus;
}

export interface Connector {
  id: string;
  type: ConnectorType;
  name: string;
  icon: string;
  description: string;
}

export interface CsvConfig {
  datasetName: string;
  delimiter: string;
  hasHeaderRow: boolean;
  encoding: string;
}

export interface PostgresConfig {
  host: string;
  port: number;
  database: string;
  schema: string;
  username: string;
  password: string;
  ssl: boolean;
}

export interface DbTable {
  id: string;
  schema: string;
  name: string;
  owner: string;
  rows: string;
  columns: number;
  size: string;
  lastUpdated: string;
}

export interface SchemaTree {
  name: string;
  tables: DbTable[];
}

export interface NewProjectFormValues {
  name: string;
  businessDomain: string;
  description: string;
  environment: Environment;
}

export interface ColumnMetadata {
  name: string;
  completeness: number;
}

export interface DatasetMetadata {
  tableId: string;
  totalRows: string;
  columns: number;
  primaryKeys: number;
  pkColumns: string[];
  foreignKeys: number;
  missingValuesPct: number;
  duplicatePct: number;
  nullPct: number;
  uniquePct: number;
  outliers: number;
  freshness: string;
  columnsQuality: ColumnMetadata[];
  nullDensityPattern: number[][]; // for the heatmap
}

export interface PipelineRule {
  id: string;
  type: string;
  category: 'Bronze' | 'Silver' | 'Gold';
  code: string;
}

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: 'INFO' | 'PASS' | 'WARN' | 'FAIL' | 'RUN';
  message: string;
}

export interface ValidationMetric {
  id: string;
  title: string;
  description: string;
  status: 'PASS' | 'WARNING' | 'FAIL';
  details: {
    passedChecks?: string;
    threshold?: string;
    measuredValue?: string;
    expectedValue?: string;
    timestamp?: string;
    rootCause?: {
      explanation: string;
      affectedRecords: string;
      suggestedFix: string;
    };
  };
}

export interface PipelineStageEvent {
  stage: 'Bronze' | 'Silver' | 'Gold';
  status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED';
}
