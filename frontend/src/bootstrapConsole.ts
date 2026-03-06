const originalWarn = console.warn.bind(console)

console.warn = (...args: Parameters<typeof console.warn>) => {
  const first = args[0]
  if (typeof first === 'string' && first.includes('THREE.THREE.Clock: This module has been deprecated')) {
    return
  }
  originalWarn(...args)
}
