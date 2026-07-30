import { ApiError, calmApiMessage } from '@/utils/apiErrors';

export function goldWorkflowError(error: unknown, fallback: string): { message: string; detail?: string } {
  if (error instanceof ApiError) {
    const detail = error.userMessage;
    if (detail.toLowerCase().includes('permission denied for schema gold')) {
      return {
        message: 'Gold could not prepare the result because the application does not have access to the configured Gold schema.',
        detail,
      };
    }
    if (detail === 'GOLD_DATABASE_UNAVAILABLE') {
      return {
        message: 'Gold could not reach the configured PostgreSQL runtime.',
        detail,
      };
    }
    if (detail === 'GOLD_UNAVAILABLE') {
      return {
        message: 'Gold authority is not configured in the local backend runtime.',
        detail,
      };
    }
    if (detail === 'GOLD_AI_UNAVAILABLE') {
      return {
        message: 'Gold structured interpretation is unavailable in this local backend runtime.',
        detail,
      };
    }
    return { message: detail || fallback, detail };
  }
  return { message: calmApiMessage(error, fallback) };
}

export function goldGenerateButtonLabel(generating: boolean, phase: string | null): string {
  return generating ? phase ?? 'Understanding requirement...' : 'Generate and Review';
}

export function canSubmitGoldGenerate({
  generating,
  selectedSilverTable,
  targetTableName,
  businessRequirement,
}: {
  generating: boolean;
  selectedSilverTable: string;
  targetTableName: string;
  businessRequirement: string;
}): boolean {
  return Boolean(
    !generating &&
    selectedSilverTable &&
    targetTableName.trim() &&
    businessRequirement.trim()
  );
}
