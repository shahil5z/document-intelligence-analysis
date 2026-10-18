import { friendlyError } from "@/lib/errors";

export function ErrorAlert({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, message, requestId } = friendlyError(error);
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
      <p className="font-semibold">{title}</p>
      <p className="mt-1">{message}</p>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="font-medium text-red-800 underline underline-offset-2 hover:text-red-950"
          >
            Try again
          </button>
        ) : null}
        {requestId ? (
          <span className="text-xs text-red-700/80">
            Reference: <code className="font-mono">{requestId}</code>
          </span>
        ) : null}
      </div>
    </div>
  );
}
