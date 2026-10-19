import { useTheme } from '../../state/ThemeContext'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  return (
    <button className="ctl btn" aria-label="Toggle theme" onClick={toggle}>
      <span
        style={{
          width: 14,
          height: 14,
          borderRadius: '50%',
          border: '1.5px solid var(--ink)',
          background: 'linear-gradient(90deg,var(--ink) 50%,transparent 50%)',
        }}
      />
      <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
    </button>
  )
}
