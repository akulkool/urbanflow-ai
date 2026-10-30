/**
 * Consistent page content wrapper.
 * Applies standard padding and max-width to page content.
 *
 * @param {object}        props
 * @param {React.ReactNode} props.children
 * @param {string}        [props.className]  Additional CSS class names.
 */
function PageContainer({ children, className = '' }) {
  return (
    <div className={`page-container ${className}`.trim()}>
      {children}
    </div>
  );
}

export default PageContainer;

