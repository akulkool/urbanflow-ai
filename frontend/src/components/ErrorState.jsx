import { AlertCircle, RefreshCw } from 'lucide-react';

/**
 * Error state display with optional retry action.
 *
 * @param {object}   props
 * @param {string}   [props.title='Something went wrong']
 * @param {string}   [props.message]    Descriptive error text.
 * @param {function} [props.onRetry]    Retry callback; shows a button when provided.
 */
function ErrorState({
  title = 'Something went wrong',
  message = 'An unexpected error occurred. Please try again.',
  onRetry,
}) {
  return (
    <div className="error-state">
      <div className="error-state__icon">
        <AlertCircle size={28} />
      </div>
      <p className="error-state__title">{title}</p>
      <p className="error-state__message">{message}</p>
      {onRetry && (
        <button className="error-state__action" onClick={onRetry}>
          <RefreshCw size={14} />
          Try Again
        </button>
      )}
    </div>
  );
}

export default ErrorState;

