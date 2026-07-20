/** User-safe API errors — never expose raw HTTP status text in the UI. */

export class ApiError extends Error {
  readonly userMessage: string;
  readonly httpStatus?: number;
  readonly errorCode?: string;

  constructor(userMessage: string, httpStatus?: number, errorCode?: string) {
    super(userMessage);
    this.name = 'ApiError';
    this.userMessage = userMessage;
    this.httpStatus = httpStatus;
    this.errorCode = errorCode;
  }
}

export const API_UNAVAILABLE =
  'Could not reach the server. Please check your connection or try again later.';

export const CUSTOM_CHECKS_UNAVAILABLE =
  'Custom check service unavailable. Demo preview mode.';

export function calmApiMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.userMessage;
  return fallback;
}
