export interface RelationSelection {
  schema: string;
  table: string;
}

export function relationSelectionKey(
  schema: string,
  table: string,
): string {
  return JSON.stringify([schema, table]);
}

export function readRelationSelection(
  searchParams: Pick<URLSearchParams, 'get'>,
): RelationSelection | null {
  const schema = searchParams.get('schema');
  const table = searchParams.get('table');
  if (!schema || !table) return null;
  return { schema, table };
}

export function withRelationSelectionQuery(
  path: string,
  relation: RelationSelection,
): string {
  const hashIndex = path.indexOf('#');
  const hash = hashIndex >= 0 ? path.slice(hashIndex) : '';
  const pathWithoutHash = hashIndex >= 0 ? path.slice(0, hashIndex) : path;
  const queryIndex = pathWithoutHash.indexOf('?');
  const pathname =
    queryIndex >= 0 ? pathWithoutHash.slice(0, queryIndex) : pathWithoutHash;
  const query = queryIndex >= 0 ? pathWithoutHash.slice(queryIndex + 1) : '';
  const params = new URLSearchParams(query);

  params.set('schema', relation.schema);
  params.set('table', relation.table);

  return `${pathname}?${params.toString()}${hash}`;
}
