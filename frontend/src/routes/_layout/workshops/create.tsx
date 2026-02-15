import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useState, useEffect, useRef } from "react"
import { ArrowLeft, Upload, Plus, Trash2, X } from "lucide-react"
import { Link } from "@tanstack/react-router"

import { workshopApi, type CreateWorkshopRequest } from "@/client"
import useAuth from "@/hooks/useAuth"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/workshops/create")({
  component: CreateWorkshop,
})

interface ParticipantInput {
  email: string
}

// Default selected resource types for new workshops
const defaultSelectedResourceTypes = [
  "Microsoft.Compute/virtualMachines",
  "Microsoft.Compute/disks",
  "Microsoft.Network/virtualNetworks",
  "Microsoft.Network/networkSecurityGroups",
  "Microsoft.Network/publicIPAddresses",
  "Microsoft.Network/networkInterfaces",
  "Microsoft.Storage/storageAccounts",
]

function CreateWorkshop() {
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { isAuthenticated } = useAuth()

  const [formData, setFormData] = useState({
    name: "",
    region: "koreacentral",
    start_date: "",
    end_date: "",
    infra_template: "",
    survey_url: "",
  })

  const [selectedServices, setSelectedServices] = useState<string[]>([])

  const [participants, setParticipants] = useState<ParticipantInput[]>([
    { email: "" },
  ])

  // Korea regions + Early access regions where new features are deployed first
  const regions = [
    "koreacentral",    // Korea Central (Seoul)
    "koreasouth",      // Korea South (Busan)
    "eastus",          // East US - Early access region
    "eastus2",         // East US 2 - Early access region
    "westus2",         // West US 2 - Early access region
    "westcentralus",   // West Central US - EUAP canary region
  ]

  const { data: templates = [] } = useQuery({
    queryKey: ["workshop-templates"],
    queryFn: workshopApi.getTemplates,
    enabled: isAuthenticated,
  })

  const { data: resourceTypes = [] } = useQuery({
    queryKey: ["workshop-resource-types"],
    queryFn: workshopApi.getResourceTypes,
    enabled: isAuthenticated,
  })

  // API 데이터 도착 시 default 선택을 실제 리소스 타입에 맞춰 동기화
  const hasInitializedDefaults = useRef(false)
  useEffect(() => {
    if (resourceTypes.length > 0 && !hasInitializedDefaults.current) {
      const availableValues = new Set(resourceTypes.map((rt) => rt.value))
      const matched = defaultSelectedResourceTypes.filter((v) =>
        availableValues.has(v)
      )
      setSelectedServices(matched)
      hasInitializedDefaults.current = true
    }
  }, [resourceTypes])

  // 카테고리별로 그룹화
  const groupedResourceTypes = resourceTypes.reduce((acc, resource) => {
    if (!acc[resource.category]) {
      acc[resource.category] = []
    }
    acc[resource.category].push(resource)
    return acc
  }, {} as Record<string, typeof resourceTypes>)

  const createMutation = useMutation({
    mutationFn: (data: CreateWorkshopRequest) => workshopApi.create(data),
    onSuccess: (workshop) => {
      showSuccessToast("워크샵이 성공적으로 생성되었습니다")
      navigate({ to: "/workshops/$workshopId", params: { workshopId: workshop.id } })
    },
    onError: () => {
      showErrorToast("워크샵 생성에 실패했습니다")
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    const validParticipants = participants.filter(
      (p) => p.email.trim()
    )

    if (validParticipants.length === 0) {
      showErrorToast("최소 한 명의 참가자가 필요합니다")
      return
    }

    // 참가자 이메일을 CSV Blob으로 변환
    const csvContent = "email\n" + validParticipants.map(p => p.email.trim()).join("\n")
    const csvBlob = new Blob([csvContent], { type: "text/csv" })
    const csvFile = new File([csvBlob], "participants.csv", { type: "text/csv" })

    createMutation.mutate({
      name: formData.name,
      start_date: formData.start_date,
      end_date: formData.end_date,
      base_resources_template: formData.infra_template || "none",
      allowed_regions: formData.region,
      allowed_services: selectedServices.join(","),
      participants_file: csvFile,
      survey_url: formData.survey_url || undefined,
    })
  }

  const addParticipant = () => {
    setParticipants([...participants, { email: "" }])
  }

  const removeParticipant = (index: number) => {
    setParticipants(participants.filter((_, i) => i !== index))
  }

  const updateParticipant = (
    index: number,
    value: string
  ) => {
    const updated = [...participants]
    updated[index].email = value
    setParticipants(updated)
  }

  const handleCsvUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      const text = event.target?.result as string
      const lines = text.split("\n").filter((line) => line.trim())

      // Skip header if present (email 컬럼)
      const startIndex = lines[0]?.toLowerCase().includes("email") ? 1 : 0

      const newParticipants: ParticipantInput[] = []
      for (let i = startIndex; i < lines.length; i++) {
        const email = lines[i].split(",")[0]?.trim()
        if (email) {
          newParticipants.push({ email })
        }
      }

      if (newParticipants.length > 0) {
        setParticipants(newParticipants)
        showSuccessToast(`${newParticipants.length}명의 참가자를 불러왔습니다`)
      }
    }
    reader.readAsText(file)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-4">
        <Link to="/">
          <Button variant="ghost" size="icon">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">새 워크샵 만들기</h1>
          <p className="text-muted-foreground">
            Azure 워크샵 환경을 설정합니다
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>기본 정보</CardTitle>
            <CardDescription>워크샵의 기본 정보를 입력하세요</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="name">워크샵 이름 *</Label>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                  placeholder="예: Azure 기초 워크샵"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="region">Azure 리전 *</Label>
                <select
                  id="region"
                  value={formData.region}
                  onChange={(e) =>
                    setFormData({ ...formData, region: e.target.value })
                  }
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  {regions?.map((region) => (
                    <option key={region} value={region}>
                      {region}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="allowed_services">허용 Azure 리소스 타입</Label>
              <select
                id="allowed_services"
                value=""
                onChange={(e) => {
                  const value = e.target.value
                  if (value && !selectedServices.includes(value)) {
                    setSelectedServices([...selectedServices, value])
                  }
                  e.target.value = ""
                }}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
              >
                <option value="">리소스 타입 선택</option>
                {Object.entries(groupedResourceTypes).map(([category, resources]) => (
                  <optgroup key={category} label={category}>
                    {resources
                      .filter((r) => !selectedServices.includes(r.value))
                      .map((resource) => (
                        <option key={resource.value} value={resource.value}>
                          {resource.label}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </select>
              {selectedServices.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {selectedServices.map((service) => {
                    const resourceInfo = resourceTypes.find(
                      (r) => r.value === service
                    )
                    return (
                      <span
                        key={service}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-sm"
                      >
                        {resourceInfo?.label || service}
                        <button
                          type="button"
                          onClick={() =>
                            setSelectedServices(
                              selectedServices.filter((s) => s !== service)
                            )
                          }
                          className="hover:bg-primary/20 rounded-full p-0.5"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    )
                  })}
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                워크샵에서 허용할 Azure 리소스를 선택하세요.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="start_date">시작 일시 *</Label>
                <Input
                  id="start_date"
                  type="datetime-local"
                  value={formData.start_date}
                  onChange={(e) =>
                    setFormData({ ...formData, start_date: e.target.value })
                  }
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="end_date">종료 일시 *</Label>
                <Input
                  id="end_date"
                  type="datetime-local"
                  value={formData.end_date}
                  onChange={(e) =>
                    setFormData({ ...formData, end_date: e.target.value })
                  }
                  required
                />
              </div>
            </div>

            {templates && templates.length > 0 && (
              <div className="space-y-2">
                <Label htmlFor="infra_template">인프라 템플릿</Label>
                <select
                  id="infra_template"
                  value={formData.infra_template}
                  onChange={(e) =>
                    setFormData({ ...formData, infra_template: e.target.value })
                  }
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                >
                  <option value="">선택 안 함</option>
                  {templates.map((template) => (
                    <option key={template.path} value={template.path}>
                      {template.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="survey_url">만족도 조사 URL (선택)</Label>
              <Input
                id="survey_url"
                type="url"
                value={formData.survey_url}
                onChange={(e) =>
                  setFormData({ ...formData, survey_url: e.target.value })
                }
                placeholder="예: https://forms.office.com/..."
              />
              <p className="text-xs text-muted-foreground">
                M365 Forms 만족도 조사 링크를 입력하세요. 나중에 추가할 수도 있습니다.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>참가자</CardTitle>
                <CardDescription>
                  워크샵 참가자 정보를 입력하거나 CSV 파일을 업로드하세요
                </CardDescription>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => document.getElementById("csv-upload")?.click()}
                >
                  <Upload className="h-4 w-4 mr-2" />
                  CSV 업로드
                </Button>
                <input
                  id="csv-upload"
                  type="file"
                  accept=".csv"
                  onChange={handleCsvUpload}
                  className="hidden"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addParticipant}
                >
                  <Plus className="h-4 w-4 mr-2" />
                  참가자 추가
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {participants.map((participant, index) => (
                <div key={index} className="flex gap-3 items-center">
                  <Input
                    type="email"
                    placeholder="이메일 (예: johndoe@company.com)"
                    value={participant.email}
                    onChange={(e) =>
                      updateParticipant(index, e.target.value)
                    }
                    className="flex-1"
                  />
                  {participants.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => removeParticipant(index)}
                    >
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end gap-3">
          <Link to="/">
            <Button type="button" variant="outline">
              취소
            </Button>
          </Link>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "생성 중..." : "워크샵 생성"}
          </Button>
        </div>
      </form>
    </div>
  )
}
