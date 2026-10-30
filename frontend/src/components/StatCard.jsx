import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

/**
 * Stat display card for KPI metrics.
 *
 * @param {object}              props
 * @param {string}              props.label      Metric label.
 * @param {string|number}       props.value      Metric value.
 * @param {React.ElementType}   [props.icon]     Lucide icon component.
 * @param {'accent'|'success'|'warning'|'danger'|'info'} [props.variant='accent']
 * @param {string}              [props.trend]    Trend text, e.g. "+12%".
 * @param {'up'|'down'|'neutral'} [props.trendDirection='neutral']
 */
function StatCard({
  label,
  value,
  description,
  icon: Icon,
  variant = 'accent',
  trend,
  trendDirection = 'neutral',
}) {
  const TrendIcon =
    trendDirection === 'up'
      ? TrendingUp
      : trendDirection === 'down'
        ? TrendingDown
        : Minus;

  return (
    <div className="stat-card">
      <div className="stat-card__header">
        {Icon && (
          <div className={`stat-card__icon stat-card__icon--${variant}`}>
            <Icon size={20} />
          </div>
        )}
        {trend && (
          <span className={`stat-card__trend stat-card__trend--${trendDirection}`}>
            <TrendIcon size={14} />
            {trend}
          </span>
        )}
      </div>
      <div className="stat-card__value">{value}</div>
      <div className="stat-card__label">{label}</div>
      {description && <div className="stat-card__desc">{description}</div>}
    </div>
  );
}

export default StatCard;

