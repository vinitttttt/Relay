import { useEffect, useState } from 'react'

const NAVIGATE_EVENT = 'relay:navigate'

export function navigate(path, replace = false) {
  if (replace) window.history.replaceState({}, '', path)
  else window.history.pushState({}, '', path)
  window.dispatchEvent(new Event(NAVIGATE_EVENT))
}

export function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname)
  useEffect(() => {
    const update = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', update)
    window.addEventListener(NAVIGATE_EVENT, update)
    return () => {
      window.removeEventListener('popstate', update)
      window.removeEventListener(NAVIGATE_EVENT, update)
    }
  }, [])
  return pathname
}

export function Link({ to, onClick, children, ...props }) {
  return (
    <a
      href={to}
      onClick={(event) => {
        onClick?.(event)
        if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
        event.preventDefault()
        navigate(to)
      }}
      {...props}
    >
      {children}
    </a>
  )
}
