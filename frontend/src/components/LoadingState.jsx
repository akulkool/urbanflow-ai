/**
 * Full-area loading spinner.
 *
 * @param {object} props
 * @param {string} [props.message='Loading…']  Text shown under the spinner.
 */
function LoadingState({ message = 'Loading…' }) {
  return (
    <div className="loading-state">
      <div className="loading-state__spinner" />
      <p className="loading-state__text">{message}</p>
    </div>
  );
}

export default LoadingState;

