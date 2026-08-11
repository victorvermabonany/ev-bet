import './Layout.css'

/**
 * Container — centres content and owns the page gutter.
 * width: 'content' | 'narrow' | 'full'
 */
export function Container({ width = 'content', as: Tag = 'div', className = '', children, ...rest }) {
  const classes = ['ui-container', `ui-container--${width}`, className].filter(Boolean).join(' ')
  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}

/**
 * Stack — vertical rhythm from the spacing scale, so screens never invent
 * one-off margins.
 * gap:   '3xs' … '4xl'
 * align: 'stretch' (default) | 'start' | 'center' | 'end'
 *
 * Defaults to 'stretch' to match how a flex column behaves natively —
 * children fill the width. Anything narrower ('start') shrinks its children
 * to their content, which silently breaks nested grids and form fields.
 */
export function Stack({ gap = 'md', align = 'stretch', as: Tag = 'div', className = '', children, ...rest }) {
  const classes = ['ui-stack', `ui-stack--gap-${gap}`, `ui-stack--align-${align}`, className]
    .filter(Boolean)
    .join(' ')
  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}

/** Row — horizontal grouping with the same spacing scale, wraps by default. */
export function Row({ gap = 'sm', align = 'center', as: Tag = 'div', className = '', children, ...rest }) {
  const classes = ['ui-row', `ui-row--gap-${gap}`, `ui-row--align-${align}`, className]
    .filter(Boolean)
    .join(' ')
  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}

/** Section — a page band with generous vertical breathing room. */
export function Section({ as: Tag = 'section', className = '', children, ...rest }) {
  return (
    <Tag className={['ui-section', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </Tag>
  )
}
