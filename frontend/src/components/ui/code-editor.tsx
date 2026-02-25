import { useRef, useEffect } from "react"
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from "@codemirror/view"
import { EditorState } from "@codemirror/state"
import { defaultKeymap, indentWithTab } from "@codemirror/commands"
import { json } from "@codemirror/lang-json"
import { javascript } from "@codemirror/lang-javascript"
import {
  syntaxHighlighting,
  defaultHighlightStyle,
  bracketMatching,
  foldGutter,
  indentOnInput,
  HighlightStyle,
} from "@codemirror/language"
import { tags } from "@lezer/highlight"
import { useTheme } from "@/components/theme-provider"

import type { TemplateType } from "@/client"

/** Returns the appropriate CodeMirror language extension for the given template type. */
function getLanguageExtension(templateType: TemplateType) {
  switch (templateType) {
    case "arm":
      return json()
    case "bicep":
      return javascript()
  }
}

/** Dark theme highlight style matching the app's dark mode palette. */
const darkHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#c586c0" },
  { tag: tags.string, color: "#ce9178" },
  { tag: tags.number, color: "#b5cea8" },
  { tag: tags.bool, color: "#569cd6" },
  { tag: tags.null, color: "#569cd6" },
  { tag: tags.propertyName, color: "#9cdcfe" },
  { tag: tags.comment, color: "#6a9955", fontStyle: "italic" },
  { tag: tags.bracket, color: "#d4d4d4" },
  { tag: tags.punctuation, color: "#d4d4d4" },
  { tag: tags.operator, color: "#d4d4d4" },
  { tag: tags.variableName, color: "#4fc1ff" },
  { tag: tags.typeName, color: "#4ec9b0" },
  { tag: tags.function(tags.variableName), color: "#dcdcaa" },
])

/** Light theme highlight style. */
const lightHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#af00db" },
  { tag: tags.string, color: "#a31515" },
  { tag: tags.number, color: "#098658" },
  { tag: tags.bool, color: "#0000ff" },
  { tag: tags.null, color: "#0000ff" },
  { tag: tags.propertyName, color: "#0451a5" },
  { tag: tags.comment, color: "#008000", fontStyle: "italic" },
  { tag: tags.bracket, color: "#333333" },
  { tag: tags.punctuation, color: "#333333" },
  { tag: tags.operator, color: "#333333" },
  { tag: tags.variableName, color: "#001080" },
  { tag: tags.typeName, color: "#267f99" },
  { tag: tags.function(tags.variableName), color: "#795e26" },
])

/** Dark editor base theme. */
const darkEditorTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#1e1e1e",
      color: "#d4d4d4",
    },
    ".cm-gutters": {
      backgroundColor: "#1e1e1e",
      color: "#858585",
      borderRight: "1px solid #333",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "#2a2d2e",
    },
    ".cm-activeLine": {
      backgroundColor: "#2a2d2e40",
    },
    ".cm-cursor": {
      borderLeftColor: "#d4d4d4",
    },
    "&.cm-focused .cm-selectionBackground, ::selection": {
      backgroundColor: "#264f78",
    },
    ".cm-foldGutter .cm-gutterElement": {
      color: "#858585",
    },
  },
  { dark: true }
)

/** Light editor base theme. */
const lightEditorTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#ffffff",
      color: "#333333",
    },
    ".cm-gutters": {
      backgroundColor: "#f5f5f5",
      color: "#999999",
      borderRight: "1px solid #e0e0e0",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "#e8e8e8",
    },
    ".cm-activeLine": {
      backgroundColor: "#f0f0f040",
    },
    ".cm-cursor": {
      borderLeftColor: "#333333",
    },
    "&.cm-focused .cm-selectionBackground, ::selection": {
      backgroundColor: "#add6ff",
    },
    ".cm-foldGutter .cm-gutterElement": {
      color: "#999999",
    },
  },
  { dark: false }
)

interface CodeEditorProps {
  /** Current code content. */
  value: string
  /** Called with new content on every change (edit mode only). */
  onChange?: (value: string) => void
  /** Template language type for syntax highlighting. */
  templateType: TemplateType
  /** When true the editor is read-only (view mode). */
  readOnly?: boolean
  /** Minimum height in CSS units. Defaults to "400px". */
  minHeight?: string
  /** Maximum height in CSS units. Defaults to "500px". */
  maxHeight?: string
}

/**
 * Syntax-highlighted code editor backed by CodeMirror 6.
 *
 * Supports JSON (ARM) and JavaScript-like (Bicep)
 * highlighting with dark/light theme awareness.
 */
export function CodeEditor({
  value,
  onChange,
  templateType,
  readOnly = false,
  minHeight = "400px",
  maxHeight = "500px",
}: CodeEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const { resolvedTheme } = useTheme()

  const isDark = resolvedTheme === "dark"

  // Create / recreate the editor when key props change
  useEffect(() => {
    if (!containerRef.current) return

    const extensions = [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      bracketMatching(),
      foldGutter(),
      indentOnInput(),
      keymap.of([...defaultKeymap, indentWithTab]),
      getLanguageExtension(templateType),
      isDark ? darkEditorTheme : lightEditorTheme,
      isDark
        ? syntaxHighlighting(darkHighlight)
        : syntaxHighlighting(lightHighlight),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      EditorView.lineWrapping,
      EditorView.editable.of(!readOnly),
      EditorState.readOnly.of(readOnly),
    ]

    if (!readOnly && onChange) {
      extensions.push(
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChange(update.state.doc.toString())
          }
        })
      )
    }

    const state = EditorState.create({
      doc: value,
      extensions,
    })

    const view = new EditorView({
      state,
      parent: containerRef.current,
    })

    viewRef.current = view

    return () => {
      view.destroy()
      viewRef.current = null
    }
    // Intentionally re-create editor when these change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateType, readOnly, isDark])

  // Sync external value changes without recreating the editor
  useEffect(() => {
    const view = viewRef.current
    if (!view) return

    const currentDoc = view.state.doc.toString()
    if (currentDoc !== value) {
      view.dispatch({
        changes: { from: 0, to: currentDoc.length, insert: value },
      })
    }
  }, [value])

  return (
    <div
      ref={containerRef}
      className="overflow-auto rounded-md border border-input text-sm"
      style={{ minHeight, maxHeight }}
    />
  )
}
