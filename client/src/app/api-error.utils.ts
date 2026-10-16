export async function parseServiceError(
  response: Response,
  fallbackMessage: string,
): Promise<Error> {
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string; details?: string; error?: string; message?: string }
    | null;

  return new Error(
    payload?.detail
      || payload?.details
      || payload?.error
      || payload?.message
      || fallbackMessage,
  );
}

export function mapServiceFetchError(error: unknown, unavailableMessage: string): Error {
  if (error instanceof Error) {
    const normalizedMessage = error.message.trim().toLowerCase();
    if (
      normalizedMessage === 'failed to fetch'
      || normalizedMessage === 'load failed'
      || normalizedMessage.includes('networkerror')
      || normalizedMessage.includes('network request failed')
    ) {
      return new Error(unavailableMessage);
    }
    return error;
  }

  return new Error(unavailableMessage);
}