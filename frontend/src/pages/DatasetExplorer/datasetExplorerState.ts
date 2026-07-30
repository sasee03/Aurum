import { classifyTable } from './datasetExplorerUtils';

export interface DatasetExplorerRelation {
  id: string;
  schema: string;
  name: string;
  owner: string;
}

/** Selection must never survive a discovery result where it is missing or internal. */
export function reconcileDatasetSelection(
  selectedIds: ReadonlySet<string>,
  relations: DatasetExplorerRelation[],
): Set<string> {
  const eligibleIds = new Set(
    relations
      .filter((relation) => classifyTable(relation.schema, relation.name, relation.owner) !== 'internal')
      .map((relation) => relation.id),
  );

  return new Set([...selectedIds].filter((id) => eligibleIds.has(id)));
}

/** A response can only update the view that initiated its matching request. */
export function isCurrentDatasetDiscovery(
  responseRequest: number,
  currentRequest: number,
): boolean {
  return responseRequest === currentRequest;
}
