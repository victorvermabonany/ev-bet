import { useId } from 'react'
import './Field.css'

/**
 * Field — the shared shell for a labelled form control: label, optional
 * hint, and an error message wired up for screen readers.
 *
 * Pass a render function so the control receives the generated ids:
 *
 *   <Field label="Name" error={errors.name}>
 *     {(props) => <Input {...props} value={…} onChange={…} />}
 *   </Field>
 *
 * Controls are required by default — pass required={false} to mark one
 * optional, so a forgotten prop can't quietly mislabel a required field.
 */
export default function Field({
  label,
  hint,
  error,
  required = true,
  children,
  className = '',
}) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  const control =
    typeof children === 'function'
      ? children({
          id,
          'aria-describedby': describedBy,
          'aria-invalid': error ? true : undefined,
        })
      : children

  return (
    <div
      className={['ui-field', error ? 'ui-field--invalid' : '', className]
        .filter(Boolean)
        .join(' ')}
    >
      <label className="ui-field__label" htmlFor={id}>
        {label}
        {!required && <span className="ui-field__optional"> — optional</span>}
      </label>

      {hint && (
        <p className="ui-field__hint" id={hintId}>
          {hint}
        </p>
      )}

      {control}

      {error && (
        <p className="ui-field__error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Fieldset — the same shell for a group of controls (checkboxes), where a
 * <legend> is correct and a <label> is not.
 */
export function Fieldset({ legend, hint, error, children, className = '' }) {
  const id = useId()
  const errorId = error ? `${id}-error` : undefined

  return (
    <fieldset
      className={['ui-field', 'ui-fieldset', error ? 'ui-field--invalid' : '', className]
        .filter(Boolean)
        .join(' ')}
      aria-describedby={errorId}
    >
      <legend className="ui-field__label">{legend}</legend>
      {hint && <p className="ui-field__hint">{hint}</p>}
      {children}
      {error && (
        <p className="ui-field__error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </fieldset>
  )
}
