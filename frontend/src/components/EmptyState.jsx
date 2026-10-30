import { Inbox } from 'lucide-react';

/**
 * Empty / no-data state display.
 *
 * @param {object}            props
 * @param {string}            [props.title='No data yet']
 * @param {string}            [props.message]
 * @param {React.ElementType} [props.icon]    Custom Lucide icon; defaults to Inbox.
 */
function EmptyState({
  title = 'No data yet',
  message = 'Data will appear here once available.',
  icon: Icon = Inbox,
}) {
  return (
    <div className="empty-state">
      <div className="empty-state__icon">
        <Icon size={28} />
      </div>
      <p className="empty-state__title">{title}</p>
      <p className="empty-state__message">{message}</p>
    </div>
  );
}

export default EmptyState;

