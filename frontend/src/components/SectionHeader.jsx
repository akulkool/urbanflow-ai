/**
 * Section heading with optional icon and action area.
 *
 * @param {object}              props
 * @param {string}              props.title       Section title.
 * @param {string}              [props.subtitle]  Optional description.
 * @param {React.ElementType}   [props.icon]      Lucide icon component.
 * @param {React.ReactNode}     [props.actions]   Action buttons on the right.
 */
function SectionHeader({ title, subtitle, icon: Icon, actions }) {
  return (
    <div className="section-header">
      <div className="section-header__left">
        {Icon && (
          <div className="section-header__icon">
            <Icon size={18} />
          </div>
        )}
        <div className="section-header__text">
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="section-header__actions">{actions}</div>}
    </div>
  );
}

export default SectionHeader;

