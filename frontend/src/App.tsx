import { lazy, Suspense } from 'react'
import { createBrowserRouter, createMemoryRouter, RouterProvider, type RouteObject } from 'react-router'
import Shell from './Shell'
import Library from './pages/Library'
import Trash from './pages/Trash'

const Editor = lazy(() => import('./pages/Editor'))

const editor = (
  <Suspense fallback={<p className="empty">Loading editor...</p>}>
    <Editor />
  </Suspense>
)

export const routes: RouteObject[] = [
  {
    element: <Shell />,
    children: [
      { path: '/', element: <Library /> },
      { path: '/p/:id', element: <Library /> },
      { path: '/p/:id/edit', element: editor },
      { path: '/new', element: editor },
      { path: '/trash', element: <Trash /> },
      { path: '*', element: <p className="empty">Not found.</p> },
    ],
  },
]

export function makeMemoryRouter(initial: string) {
  return createMemoryRouter(routes, { initialEntries: [initial] })
}

const router = createBrowserRouter(routes)

export default function App() {
  return <RouterProvider router={router} />
}
