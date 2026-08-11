import './Typography.css'

/**
 * Heading — serif display type.
 * level: 1–6 (semantic tag)
 * size:  optional visual override, '5xl' … 'lg'
 */
export function Heading({ level = 2, size, as, className = '', children, ...rest }) {
  const Tag = as || `h${level}`
  const classes = ['ui-heading', size ? `ui-heading--${size}` : '', className]
    .filter(Boolean)
    .join(' ')
  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}

/**
 * Text — sans-serif body copy and data.
 * size:    'sm' | 'base' | 'md' | 'lg' | 'xl'
 * tone:    'default' | 'muted' | 'subtle' | 'accent'
 * measure: constrain to a comfortable reading width
 */
export function Text({
  size = 'md',
  tone = 'default',
  measure = false,
  as: Tag = 'p',
  className = '',
  children,
  ...rest
}) {
  const classes = [
    'ui-text',
    `ui-text--${size}`,
    `ui-text--${tone}`,
    measure ? 'ui-text--measure' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}

/** Eyebrow — small, wide-tracked label that sits above a headline. */
export function Eyebrow({ as: Tag = 'p', className = '', children, ...rest }) {
  return (
    <Tag className={['ui-eyebrow', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </Tag>
  )
}
