import './Button.css'

/**
 * Button — soft, pill-shaped, terracotta by default.
 *
 * variant: 'primary' | 'secondary' | 'ghost'
 * size:    'sm' | 'md' | 'lg'
 * as:      render as a different element, e.g. as="a" href="/start"
 */
export default function Button({
  variant = 'primary',
  size = 'md',
  as: Tag = 'button',
  className = '',
  children,
  ...rest
}) {
  const classes = [
    'ui-button',
    `ui-button--${variant}`,
    `ui-button--${size}`,
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <Tag className={classes} {...rest}>
      <span className="ui-button__label">{children}</span>
    </Tag>
  )
}
