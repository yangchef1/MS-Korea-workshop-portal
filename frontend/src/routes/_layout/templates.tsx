import { createFileRoute } from "@tanstack/react-router"
import { useState, useEffect, useCallback } from "react"
import { FileCode, Pencil, Trash2, Shield, Eye, X, Save, Plus } from "lucide-react"
import { CodeEditor } from "@/components/ui/code-editor"

import {
  templateApi,
  type InfraTemplate,
  type InfraTemplateDetail,
  type CreateTemplateRequest,
  type TemplateType,
} from "@/client"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

export const Route = createFileRoute("/_layout/templates")({
  component: TemplateManagementPage,
})

/** Maps template_type values to display labels. */
const TEMPLATE_TYPE_LABELS: Record<TemplateType, string> = {
  arm: "ARM Templates",
  bicep: "Bicep",
}

/** Default template content per template type. */
const DEFAULT_TEMPLATE_CONTENT: Record<TemplateType, string> = {
  arm: JSON.stringify(
    {
      $schema:
        "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
      contentVersion: "1.0.0.0",
      resources: [],
    },
    null,
    2
  ),
  bicep: "// Bicep template\n",
}

// ---------------------------------------------------------------------------
// Custom hook: useTemplates
// ---------------------------------------------------------------------------

interface UseTemplatesResult {
  templates: InfraTemplate[]
  isLoading: boolean
  refetch: () => void
}

/**
 * Fetches and manages the infrastructure template list.
 *
 * @returns Template list, loading state, and refetch function.
 */
function useTemplates(): UseTemplatesResult {
  const [templates, setTemplates] = useState<InfraTemplate[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const fetchTemplates = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await templateApi.list()
      setTemplates(data)
    } catch {
      setTemplates([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTemplates()
  }, [fetchTemplates])

  return { templates, isLoading, refetch: fetchTemplates }
}

// ---------------------------------------------------------------------------
// Template detail/edit panel
// ---------------------------------------------------------------------------

interface TemplateDetailPanelProps {
  templateName: string
  onClose: () => void
  onSaved: () => void
}

/** Panel for viewing and editing a template's detail (description + content). */
function TemplateDetailPanel({
  templateName,
  onClose,
  onSaved,
}: TemplateDetailPanelProps) {
  const [detail, setDetail] = useState<InfraTemplateDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [description, setDescription] = useState("")
  const [templateType, setTemplateType] = useState<TemplateType>("arm")
  const [content, setContent] = useState("")
  const [jsonError, setJsonError] = useState<string | null>(null)
  const { showSuccessToast, showErrorToast } = useCustomToast()

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)

    templateApi
      .get(templateName)
      .then((data) => {
        if (cancelled) return
        setDetail(data)
        setDescription(data.description)
        setTemplateType(data.template_type ?? "arm")
        // Pretty-print the JSON content for editing (ARM only)
        if ((data.template_type ?? "arm") === "arm") {
          try {
            const parsed = JSON.parse(data.template_content)
            setContent(JSON.stringify(parsed, null, 2))
          } catch {
            setContent(data.template_content)
          }
        } else {
          setContent(data.template_content)
        }
      })
      .catch(() => {
        if (!cancelled) {
          showErrorToast("템플릿 상세 정보를 불러오지 못했습니다.")
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [templateName])

  const handleSave = async () => {
    // Validate JSON only for ARM templates
    if (templateType === "arm") {
      try {
        JSON.parse(content)
        setJsonError(null)
      } catch {
        setJsonError("유효하지 않은 JSON 형식입니다.")
        return
      }
    } else {
      setJsonError(null)
    }

    setIsSaving(true)
    try {
      await templateApi.update(templateName, {
        description,
        template_type: templateType,
        template_content: content,
      })
      showSuccessToast(`'${templateName}' 템플릿이 수정되었습니다.`)
      setIsEditing(false)
      onSaved()
    } catch {
      showErrorToast("템플릿 수정에 실패했습니다.")
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8">
          <div className="flex items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-primary border-t-transparent" />
            <span className="ml-3 text-muted-foreground">불러오는 중…</span>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!detail) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-center text-muted-foreground">
            템플릿 정보를 불러올 수 없습니다.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div>
          <CardTitle className="text-lg flex items-center gap-2">
            <FileCode className="h-5 w-5" />
            {detail.name}
          </CardTitle>
          <CardDescription>
            {detail.path} · {TEMPLATE_TYPE_LABELS[detail.template_type ?? "arm"]}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          {!isEditing ? (
            <Button variant="outline" size="sm" onClick={() => setIsEditing(true)}>
              <Pencil className="h-3.5 w-3.5 mr-1" />
              수정
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleSave}
              disabled={isSaving}
            >
              <Save className="h-3.5 w-3.5 mr-1" />
              {isSaving ? "저장 중…" : "저장"}
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="tpl-description">설명</Label>
          {isEditing ? (
            <Input
              id="tpl-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="템플릿 설명"
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              {detail.description || "(설명 없음)"}
            </p>
          )}
        </div>

        {isEditing && (
          <div className="space-y-2">
            <Label htmlFor="tpl-type">템플릿 유형</Label>
            <select
              id="tpl-type"
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={templateType}
              onChange={(e) => setTemplateType(e.target.value as TemplateType)}
            >
              <option value="arm">ARM Templates</option>
              <option value="bicep">Bicep</option>
            </select>
          </div>
        )}

        <div className="space-y-2">
          <Label>템플릿</Label>
          <CodeEditor
            value={content}
            onChange={(val) => {
              setContent(val)
              setJsonError(null)
            }}
            templateType={templateType}
            readOnly={!isEditing}
          />
          {jsonError && (
            <p className="text-sm text-destructive">{jsonError}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Create template panel
// ---------------------------------------------------------------------------

interface CreateTemplatePanelProps {
  onClose: () => void
  onCreated: () => void
}

/** Panel for creating a new infrastructure template. */
function CreateTemplatePanel({ onClose, onCreated }: CreateTemplatePanelProps) {
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [templateType, setTemplateType] = useState<TemplateType>("arm")
  const [content, setContent] = useState(DEFAULT_TEMPLATE_CONTENT["arm"])
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const handleTypeChange = (newType: TemplateType) => {
    setTemplateType(newType)
    setContent(DEFAULT_TEMPLATE_CONTENT[newType])
    setJsonError(null)
  }

  const handleCreate = async () => {
    if (!name.trim()) {
      showErrorToast("템플릿 이름을 입력해주세요.")
      return
    }

    // Validate JSON only for ARM templates
    if (templateType === "arm") {
      try {
        JSON.parse(content)
        setJsonError(null)
      } catch {
        setJsonError("유효하지 않은 JSON 형식입니다.")
        return
      }
    } else {
      setJsonError(null)
    }

    setIsSaving(true)
    try {
      const request: CreateTemplateRequest = {
        name: name.trim(),
        description,
        template_type: templateType,
        template_content: content,
      }
      await templateApi.create(request)
      showSuccessToast(`'${name.trim()}' 템플릿이 생성되었습니다.`)
      onCreated()
    } catch {
      showErrorToast("템플릿 생성에 실패했습니다.")
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div>
          <CardTitle className="text-lg flex items-center gap-2">
            <Plus className="h-5 w-5" />
            새 템플릿 만들기
          </CardTitle>
          <CardDescription>
            워크샵에서 사용할 새 인프라 템플릿을 등록합니다.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleCreate} disabled={isSaving}>
            <Save className="h-3.5 w-3.5 mr-1" />
            {isSaving ? "생성 중…" : "생성"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="new-tpl-name">템플릿 이름</Label>
          <Input
            id="new-tpl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: vm-linux-basic"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="new-tpl-description">설명</Label>
          <Input
            id="new-tpl-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="템플릿 설명"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="new-tpl-type">템플릿 유형</Label>
          <select
            id="new-tpl-type"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={templateType}
            onChange={(e) => handleTypeChange(e.target.value as TemplateType)}
          >
            <option value="arm">ARM Templates</option>
            <option value="bicep">Bicep</option>

          </select>
        </div>

        <div className="space-y-2">
          <Label>템플릿</Label>
          <CodeEditor
            value={content}
            onChange={(val) => {
              setContent(val)
              setJsonError(null)
            }}
            templateType={templateType}
          />
          {jsonError && (
            <p className="text-sm text-destructive">{jsonError}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Template list row
// ---------------------------------------------------------------------------

interface TemplateRowProps {
  template: InfraTemplate
  isSelected: boolean
  onView: (name: string) => void
  onDelete: (name: string) => void
}

/** Single row in the template table. */
function TemplateRow({ template, isSelected, onView, onDelete }: TemplateRowProps) {
  return (
    <tr
      className={`border-b last:border-b-0 hover:bg-muted/50 transition-colors ${
        isSelected ? "bg-muted/50" : ""
      }`}
    >
      <td className="px-4 py-3 text-sm font-medium">{template.name}</td>
      <td className="px-4 py-3 text-sm">
        <span className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold">
          {TEMPLATE_TYPE_LABELS[template.template_type ?? "arm"]}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">
        {template.description || "-"}
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">{template.path}</td>
      <td className="px-4 py-3 text-sm">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onView(template.name)}
          >
            <Eye className="h-3.5 w-3.5 mr-1" />
            상세
          </Button>

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="ghost" size="sm" title="템플릿 삭제">
                <Trash2 className="h-3.5 w-3.5 text-destructive" />
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>템플릿 삭제</AlertDialogTitle>
                <AlertDialogDescription>
                  <strong>{template.name}</strong> 템플릿을 정말 삭제하시겠습니까?
                  이 작업은 되돌릴 수 없습니다.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>취소</AlertDialogCancel>
                <AlertDialogAction
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  onClick={() => onDelete(template.name)}
                >
                  삭제
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

/** Admin-only ARM template management page. */
function TemplateManagementPage() {
  const { user, isLoading: authLoading } = useAuth()
  const { templates, isLoading, refetch } = useTemplates()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  const isAdmin = user?.role === "admin"

  if (authLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mb-4" />
        <p className="text-muted-foreground">권한을 확인하는 중입니다…</p>
      </div>
    )
  }

  if (!isAdmin) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <Shield className="h-12 w-12 text-muted-foreground mb-4" />
        <h2 className="text-xl font-semibold mb-2">접근 권한이 없습니다</h2>
        <p className="text-muted-foreground">
          이 페이지는 관리자만 접근할 수 있습니다.
        </p>
      </div>
    )
  }

  const handleDelete = async (name: string) => {
    try {
      await templateApi.delete(name)
      showSuccessToast(`'${name}' 템플릿이 삭제되었습니다.`)
      if (selectedTemplate === name) {
        setSelectedTemplate(null)
      }
      refetch()
    } catch {
      showErrorToast("템플릿 삭제에 실패했습니다.")
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">템플릿 관리</h1>
        <p className="text-muted-foreground">
          워크샵에서 사용하는 인프라 템플릿을 관리합니다.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>템플릿 목록</CardTitle>
            <CardDescription>
              총 {templates.length}개의 템플릿이 등록되어 있습니다.
            </CardDescription>
          </div>
          <Button
            onClick={() => {
              setIsCreating(true)
              setSelectedTemplate(null)
            }}
          >
            <Plus className="h-4 w-4 mr-2" />
            템플릿 만들기
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 bg-muted rounded animate-pulse" />
              ))}
            </div>
          ) : templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center text-center py-12">
              <div className="rounded-full bg-muted p-4 mb-4">
                <FileCode className="h-8 w-8 text-muted-foreground" />
              </div>
              <h3 className="text-lg font-semibold">등록된 템플릿이 없습니다</h3>
              <p className="text-muted-foreground mb-4">
                새 템플릿을 만들어 시작하세요
              </p>
              <Button
                onClick={() => {
                  setIsCreating(true)
                  setSelectedTemplate(null)
                }}
              >
                <Plus className="h-4 w-4 mr-2" />
                템플릿 만들기
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b text-left text-sm font-medium text-muted-foreground">
                    <th className="px-4 py-3">이름</th>
                    <th className="px-4 py-3">유형</th>
                    <th className="px-4 py-3">설명</th>
                    <th className="px-4 py-3">경로</th>
                    <th className="px-4 py-3">액션</th>
                  </tr>
                </thead>
                <tbody>
                  {templates.map((tpl) => (
                    <TemplateRow
                      key={tpl.name}
                      template={tpl}
                      isSelected={selectedTemplate === tpl.name}
                      onView={(name) => {
                        setSelectedTemplate(name)
                        setIsCreating(false)
                      }}
                      onDelete={handleDelete}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {isCreating && (
        <CreateTemplatePanel
          onClose={() => setIsCreating(false)}
          onCreated={() => {
            setIsCreating(false)
            refetch()
          }}
        />
      )}

      {selectedTemplate && (
        <TemplateDetailPanel
          key={selectedTemplate}
          templateName={selectedTemplate}
          onClose={() => setSelectedTemplate(null)}
          onSaved={refetch}
        />
      )}
    </div>
  )
}
