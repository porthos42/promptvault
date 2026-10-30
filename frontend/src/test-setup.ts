import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// vitest globals are off, so RTL's automatic cleanup does not register itself.
afterEach(() => cleanup())

// jsdom has no layout; give the virtualizer a viewport so rows render.
class RO {
  cb: ResizeObserverCallback
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb
  }
  observe(el: Element) {
    this.cb([{ target: el, contentRect: { width: 400, height: 800 } } as ResizeObserverEntry], this as never)
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = RO as never
for (const prop of ['offsetHeight', 'clientHeight'] as const)
  Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, value: 800 })
for (const prop of ['offsetWidth', 'clientWidth'] as const)
  Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, value: 400 })
Element.prototype.getBoundingClientRect = () =>
  ({ width: 400, height: 800, top: 0, left: 0, right: 400, bottom: 800, x: 0, y: 0, toJSON() {} }) as DOMRect
