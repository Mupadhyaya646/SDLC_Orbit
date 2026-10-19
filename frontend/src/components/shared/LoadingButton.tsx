import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

interface LoadingButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'style'> {
  isLoading?: boolean
  variant?: Variant
  children: ReactNode
  style?: CSSProperties
}

function variantStyle(variant: Variant, enabled: boolean): CSSProperties {
  switch (variant) {
    case 'primary':
      return enabled
        ? { background: 'var(--red)', color: '#fff' }
        : { background: 'var(--surface2)', color: 'var(--muted)' }
    case 'secondary':
      return { border: '1px solid var(--line2)', background: 'var(--surface)', color: 'var(--ink)' }
    case 'danger':
      return { border: '1px solid var(--line2)', background: 'transparent', color: 'var(--red-text)' }
    case 'ghost':
      return { background: 'transparent', border: 0, color: 'var(--ink2)' }
  }
}

export function LoadingButton({ isLoading, variant = 'primary', disabled, children, style, ...rest }: LoadingButtonProps) {
  const isDisabled = !!disabled || !!isLoading
  const combinedStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 10,
    padding: '12px 20px',
    border: 0,
    font: "600 14px 'IBM Plex Sans',sans-serif",
    cursor: isDisabled ? 'not-allowed' : 'pointer',
    ...variantStyle(variant, !isDisabled),
    ...style,
  }

  return (
    <button {...rest} disabled={isDisabled} style={combinedStyle}>
      {isLoading && <span className="btn-spinner" />}
      {children}
    </button>
  )
}
