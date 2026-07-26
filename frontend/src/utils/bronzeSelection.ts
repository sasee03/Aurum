export function initialBronzeSelection(): string[] {
  return [];
}

export function toggleBronzeTable(
  selectedTables: string[],
  tableName: string,
): string[] {
  return selectedTables.includes(tableName)
    ? selectedTables.filter((table) => table !== tableName)
    : [...selectedTables, tableName];
}

export function toggleAllBronzeTables(
  selectedTables: string[],
  availableTables: string[],
): string[] {
  return selectedTables.length === availableTables.length
    ? []
    : [...availableTables];
}

export function canIngestBronzeSelection(
  selectedTables: string[],
  isBusy: boolean,
  isLoading: boolean,
): boolean {
  return selectedTables.length > 0 && !isBusy && !isLoading;
}
