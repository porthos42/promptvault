import { basicSetup, EditorView } from 'codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { useEffect, useRef } from 'react'

type Props = { value: string; onChange: (v: string) => void; label: string }

/** Thin CodeMirror 6 wrapper: uncontrolled after mount, reports edits via onChange. */
export default function CodeEditor({ value, onChange, label }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const cb = useRef(onChange)
  useEffect(() => {
    cb.current = onChange
  })

  useEffect(() => {
    const view = new EditorView({
      doc: value,
      parent: host.current!,
      extensions: [
        basicSetup,
        markdown(),
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({ 'aria-label': label }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) cb.current(u.state.doc.toString())
        }),
      ],
    })
    return () => view.destroy()
    // value is only the initial document
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return <div ref={host} className="cm-host" />
}
