/** User-safe API errors — never expose raw HTTP status text in the UI. */

export class ApiError extends Error {
  readonly userMessage: string;

  constructor(userMessage: string) {
    super(userMessage);
    this.name = 'ApiError';
    this.userMessage = userMessage;
  }
}

export const API_UNAVAILABLE =
  'Service temporarily unavailable. Showing cached demo data where available.';

export const CUSTOM_CHECKS_UNAVAILABLE =
  'Custom check service unavailable. Demo preview mode.';

export function calmApiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.userMessage;
  return fallback;
}
