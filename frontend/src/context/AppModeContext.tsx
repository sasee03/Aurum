import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { healthCheck } from '@/lib/aurumApi';
import type { AppModeState } from '@/types/appMode';

const LOADING_STATE: AppModeState = {
  mode: 'loading',
  backendReachable: false,
  databaseOk: false,
  reason: 'Checking backend health…',
  canRunValidation: false,
  displayMode: 'loading',
  isResolved: false,
};

const AppModeContext = createContext<AppModeState>(LOADING_STATE);

async function probeAppMode(): Promise<Omit<AppModeState, 'isResolved'>> {
  try {
    const health = await healthCheck();
    const databaseOk = health.database === 'ok';
    const backendReachable = true;
    const canRunValidation = databaseOk;
    const mode = canRunValidation ? 'live' : 'verified_snapshot';
    return {
      mode,
      backendReachable,
      databaseOk,
      canRunValidation,
      displayMode: canRunValidation ? 'live' : 'verified_snapshot',
      databaseTarget: health.database_target,
      reason: databaseOk
        ? 'Backend and database are healthy — live validation is available.'
        : 'Database is unreachable — using verified snapshot mode. Live validation is disabled.',
    };
  } catch {
    return {
      mode: 'verified_snapshot',
      backendReachable: false,
      databaseOk: false,
      canRunValidation: false,
      displayMode: 'verified_snapshot',
      reason:
        'Backend is unreachable — using verified snapshot mode. Live validation is disabled.',
    };
  }
}

export function AppModeProvider({ children }: { children: ReactNode }) {
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['aurum', 'app-mode'],
    queryFn: probeAppMode,
    staleTime: 10_000,
    refetchInterval: 30_000,
    retry: 1,
  });

  const value = useMemo<AppModeState>(() => {
    if (isLoading && !data) {
      return LOADING_STATE;
    }
    if (!data) {
      return {
        ...LOADING_STATE,
        mode: 'verified_snapshot',
        displayMode: 'verified_snapshot',
        reason: 'Could not determine backend health — defaulting to verified snapshot mode.',
        isResolved: true,
      };
    }
    return { ...data, isResolved: !isFetching || !isLoading };
  }, [data, isLoading, isFetching]);

  return <AppModeContext.Provider value={value}>{children}</AppModeContext.Provider>;
}

export function useAppMode(): AppModeState {
  return useContext(AppModeContext);
}

/** Processing/onboarding pages that are preview-only until wired. */
export function usePlannedMode(reason?: string): AppModeState {
  const base = useAppMode();
  return useMemo(
    () => ({
      ...base,
      mode: 'planned' as const,
      displayMode: 'planned' as const,
      canRunValidation: false,
      reason: reason ?? 'This feature is planned and not wired to live processing yet.',
    }),
    [base, reason],
  );
}
