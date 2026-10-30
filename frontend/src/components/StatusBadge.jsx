/**
 * Small status indicator badge.
 *
 * @param {object}  props
 * @param {string}  props.label                         Badge text.
 * @param {'success'|'warning'|'danger'|'info'|'neutral'} [props.variant='neutral']
 * @param {boolean} [props.dot=true]                    Show leading dot indicator.
 */
function StatusBadge({ label, variant = 'neutral', dot = true }) {
  return (
    <span className={`status-badge status-badge--${variant}`}>
      {dot && <span className="status-badge__dot" />}
      {label}
    </span>
  );
}

export default StatusBadge;

