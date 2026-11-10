export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  const timeout = AbortSignal.timeout(10000);
  const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try { response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options, signal }); }
  catch (error) { if ((error as Error).name === 'AbortError') throw error; throw new ApiError(0, 'The API is unavailable. Showing the last loaded records.'); }
  if (!response.ok) {
    const message = response.status === 401 ? 'Your session ended. Sign in again.'
      : response.status === 403 ? 'Your role does not permit this action.'
      : response.status === 429 ? 'Too many sign-in attempts. Try again in a minute.'
      : response.status === 404 ? 'That record could not be found.'
      : 'The service could not complete this request. Try again.';
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
