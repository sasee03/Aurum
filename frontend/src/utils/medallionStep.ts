export function medallionStepForPathname(pathname: string): string {
  if (pathname.includes('/connect')) return '/connect';
  if (pathname.includes('/select') || pathname.includes('/metadata')) return '/select';
  if (pathname.includes('/bronze')) return '/bronze';
  if (pathname.includes('/silver')) return '/silver';
  if (pathname.includes('/gold')) return '/gold';
  return '';
}
