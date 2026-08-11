import './Card.css'

/**
 * Card — a soft, generously padded panel on cream paper.
 *
 * tone:    'surface' | 'sunken' | 'accent'
 * padding: 'md' | 'lg' | 'xl'
 */
export default function Card({
  tone = 'surface',
  padding = 'lg',
  as: Tag = 'div',
  className = '',
  children,
  ...rest
}) {
  const classes = ['ui-card', `ui-card--${tone}`, `ui-card--pad-${padding}`, className]
    .filter(Boolean)
    .join(' ')

  return (
    <Tag className={classes} {...rest}>
      {children}
    </Tag>
  )
}
