import './Field.css'

/** Input — a single-line text control. Use inside <Field>. */
export default function Input({ className = '', ...rest }) {
  return <input className={['ui-input', className].filter(Boolean).join(' ')} {...rest} />
}

/**
 * Select — native <select> with the default chrome replaced. Options are
 * passed as groups: [{ label, options: [string] }].
 */
export function Select({ groups = [], placeholder, className = '', ...rest }) {
  return (
    <select className={['ui-select', className].filter(Boolean).join(' ')} {...rest}>
      {placeholder && <option value="">{placeholder}</option>}
      {groups.map((group) => (
        <optgroup key={group.label} label={group.label}>
          {group.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

/** Checkbox — a soft pill tile with a custom tick. */
export function Checkbox({ label, checked = false, onChange, className = '', ...rest }) {
  return (
    <label
      className={['ui-checkbox', checked ? 'ui-checkbox--checked' : '', className]
        .filter(Boolean)
        .join(' ')}
    >
      <input
        type="checkbox"
        className="ui-checkbox__input"
        checked={checked}
        onChange={onChange}
        {...rest}
      />
      <span className="ui-checkbox__box" aria-hidden="true">
        <svg width="13" height="10" viewBox="0 0 13 10" fill="none">
          <path
            d="M1.5 5.2L4.7 8.4L11.2 1.6"
            stroke="currentColor"
            strokeWidth="2.1"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="ui-checkbox__label">{label}</span>
    </label>
  )
}
