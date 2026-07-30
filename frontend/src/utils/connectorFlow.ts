import { ApiError, calmApiMessage } from './apiErrors';

const CONNECTOR_FLOW_KEYS = [
  'projectId',
  'connectionId',
  'database',
  'schema',
  'table',
  'run_id',
  'runId',
] as const;

export function withConnectorFlowQuery(path: string, searchParams: URLSearchParams): string {
  const [basePath, rawQuery = ''] = path.split('?');
  const next = new URLSearchParams(rawQuery);

  for (const key of CONNECTOR_FLOW_KEYS) {
    const value = searchParams.get(key);
    if (value && !next.has(key)) {
      next.set(key, value);
    }
  }

  const query = next.toString();
  return query ? `${basePath}?${query}` : basePath;
}

export function bronzeDiscoveryErrorMessage(error: unknown, connectorMode: boolean): string {
  if (
    connectorMode &&
    error instanceof ApiError &&
    error.httpStatus === 404 &&
    error.errorCode === 'connection_not_found'
  ) {
    return error.userMessage;
  }

  return calmApiMessage(
    error,
    connectorMode
      ? 'Failed to discover tables from this PostgreSQL connection. Re-test the connection and try again.'
      : 'Failed to discover source tables from backend API.',
  );
}
