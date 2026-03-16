import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState, useEffect, useRef, useMemo } from "react"
import { ArrowLeft, ChevronDown, Upload, Plus, Trash2, X } from "lucide-react"
import { Link } from "@tanstack/react-router"

import { workshopApi, handleApiError, getErrorTitle, type CreateWorkshopRequest, type ApiError } from "@/client"
import useAuth from "@/hooks/useAuth"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/workshops/create")({
  component: CreateWorkshop,
})

interface ParticipantInput {
  email: string
}

// Default denied resource types for new workshops (empty = allow everything)
const defaultDeniedResourceTypes: string[] = []

function CreateWorkshop() {
  const navigate = useNavigate()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { isAuthenticated } = useAuth()

  const [formData, setFormData] = useState({
    name: "",
    start_date: "",
    end_date: "",
    infra_template: "",
    survey_url: "",
    description: "",
  })

  const [selectedRegions, setSelectedRegions] = useState<string[]>(["koreacentral"])
  const [deploymentRegion, setDeploymentRegion] = useState<string>("koreacentral")
  const [selectedServices, setSelectedServices] = useState<string[]>([])
  const [selectedPreset, setSelectedPreset] = useState<string>("")
  const [selectedVmSkus, setSelectedVmSkus] = useState<string[]>([])
  const [participants, setParticipants] = useState<ParticipantInput[]>([
    { email: "" },
  ])

  // Template mode derived from dropdown: "none" | "preset" | "upload"
  const [templateMode, setTemplateMode] = useState<"none" | "preset" | "upload">("none")
  const [templateFile, setTemplateFile] = useState<File | null>(null)
  const [parametersFile, setParametersFile] = useState<File | null>(null)

  // Korea regions + Early access regions where new features are deployed first
  const regions: { value: string; label: string }[] = [
    { value: "koreacentral", label: "Korea Central (Seoul)" },
    { value: "koreasouth", label: "Korea South (Busan)" },
    { value: "eastus", label: "East US" },
    { value: "eastus2", label: "East US 2" },
    { value: "westus2", label: "West US 2" },
    { value: "westcentralus", label: "West Central US (EUAP)" },
  ]
  const selectedRegionLabels = regions
    .filter((region) => selectedRegions.includes(region.value))
    .map((region) => region.label)
  const selectedRegionSummary =
    selectedRegionLabels.length === 0
      ? "허용 리전 선택"
      : selectedRegionLabels.length <= 2
        ? selectedRegionLabels.join(", ")
        : `${selectedRegionLabels.slice(0, 2).join(", ")} 외 ${selectedRegionLabels.length - 2}개`

  const { data: templates = [], isLoading: isTemplatesLoading } = useQuery({
    queryKey: ["workshop-templates"],
    queryFn: workshopApi.getTemplates,
    enabled: isAuthenticated,
  })

  const { data: resourceTypes = [] } = useQuery({
    queryKey: ["workshop-resource-types"],
    queryFn: workshopApi.getResourceTypes,
    enabled: isAuthenticated,
  })

  const { data: vmSkuPresets } = useQuery({
    queryKey: ["vm-sku-presets"],
    queryFn: workshopApi.getVmSkuPresets,
    enabled: isAuthenticated,
  })

  const { data: vmSkus = [] } = useQuery({
    queryKey: ["vm-skus-common", regions.map((r) => r.value)],
    queryFn: () => workshopApi.getCommonVmSkus(regions.map((r) => r.value)),
    enabled: isAuthenticated,
  })

  // VM 리소스 차단 시 VM SKU 선택 비활성화
  const isVmBlocked = useMemo(
    () => selectedServices.includes("Microsoft.Compute/virtualMachines"),
    [selectedServices]
  )

  // 허용 리전 변경 시 배포 리전 동기화: 현재 선택이 유효하지 않으면 첫 번째 리전으로 변경
  useEffect(() => {
    if (selectedRegions.length === 0) {
      setDeploymentRegion("")
    } else if (!selectedRegions.includes(deploymentRegion)) {
      setDeploymentRegion(selectedRegions[0])
    }
  }, [selectedRegions, deploymentRegion])

  // VM 리소스 차단 시 SKU 선택 초기화
  useEffect(() => {
    if (isVmBlocked) {
      setSelectedPreset("")
      setSelectedVmSkus([])
    }
  }, [isVmBlocked])

  useEffect(() => {
    if (isVmBlocked) {
      return
    }

    const availableSkuNames = new Set(vmSkus.map((sku) => sku.name))
    setSelectedVmSkus((previousSkus) =>
      previousSkus.filter((sku) => availableSkuNames.has(sku))
    )
  }, [isVmBlocked, vmSkus])

  // API 데이터 도착 시 default 선택을 실제 리소스 타입에 맞춰 동기화
  const hasInitializedDefaults = useRef(false)
  useEffect(() => {
    if (resourceTypes.length > 0 && !hasInitializedDefaults.current) {
      const availableValues = new Set(resourceTypes.map((rt) => rt.value))
      const matched = defaultDeniedResourceTypes.filter((v) =>
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

  const queryClient = useQueryClient()

  const createMutation = useMutation({
    mutationFn: (data: CreateWorkshopRequest) => workshopApi.create(data),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["workshops"] })
      if (response?.status === "scheduled") {
        showSuccessToast("워크샵이 예약되었습니다. 시작 시각 1시간 전에 자동으로 프로비저닝됩니다.")
      } else {
        showSuccessToast("워크샵이 성공적으로 생성되었습니다")
      }
      navigate({ to: "/" })
    },
    onError: (error) => {
      const apiError = handleApiError(error as import("axios").AxiosError<ApiError>)
      const title = getErrorTitle(apiError.error)
      const failedParticipants = Array.isArray(apiError.details?.failed_participants)
        ? JSON.stringify(apiError.details.failed_participants)
        : undefined

      navigate({
        to: "/",
        search: {
          createError: title,
          errorDetail: apiError.message,
          errorCode: apiError.error,
          failedParticipants,
        },
      })
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

    if (selectedRegions.length === 0) {
      showErrorToast("최소 한 개의 리전을 선택해주세요")
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
      base_resources_template: templateMode === "preset"
        ? (formData.infra_template || "none")
        : "none",
      allowed_regions: selectedRegions.join(","),
      denied_services: selectedServices.join(","),
      allowed_vm_skus: selectedVmSkus.length > 0 ? selectedVmSkus.join(",") : undefined,
      vm_sku_preset: selectedPreset || undefined,
      deployment_region: deploymentRegion || undefined,
      participants_file: csvFile,
      template_file: templateMode === "upload" && templateFile ? templateFile : undefined,
      parameters_file: templateMode !== "none" && parametersFile ? parametersFile : undefined,
      survey_url: formData.survey_url || undefined,
      description: formData.description || undefined,
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
            </div>

            <div className="space-y-2">
              <Label htmlFor="description">워크샵 설명 (선택)</Label>
              <textarea
                id="description"
                value={formData.description}
                onChange={(e) =>
                  setFormData({ ...formData, description: e.target.value })
                }
                placeholder="예: Azure 기초 워크샵으로 VM, Storage, Network 등을 다룹니다."
                rows={2}
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
              />
            </div>

            <div className="space-y-2">
              <Label>허용 Azure 리전 *</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-between font-normal"
                  >
                    <span className="truncate text-left">{selectedRegionSummary}</span>
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-[320px]" align="start">
                  <DropdownMenuLabel>허용 Azure 리전</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {regions.map((region) => (
                    <DropdownMenuCheckboxItem
                      key={region.value}
                      checked={selectedRegions.includes(region.value)}
                      onSelect={(event) => event.preventDefault()}
                      onCheckedChange={(checked) => {
                        setSelectedRegions((prev) =>
                          checked === true
                            ? prev.includes(region.value)
                              ? prev
                              : [...prev, region.value]
                            : prev.filter((r) => r !== region.value)
                        )
                      }}
                    >
                      {region.label}
                    </DropdownMenuCheckboxItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
              <div className="flex flex-wrap gap-2">
                {selectedRegionLabels.map((label) => (
                  <span
                    key={label}
                    className="inline-flex items-center rounded-md bg-primary/10 px-2 py-1 text-xs text-primary"
                  >
                    {label}
                  </span>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                참가자가 리소스를 생성할 수 있는 리전을 선택하세요. 최소 1개 필수.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="deployment_region">배포 리전 *</Label>
              <select
                id="deployment_region"
                value={deploymentRegion}
                onChange={(e) => setDeploymentRegion(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {selectedRegions.length === 0 ? (
                  <option value="">허용 리전을 먼저 선택하세요</option>
                ) : (
                  selectedRegions.map((value) => {
                    const label = regions.find((r) => r.value === value)?.label || value
                    return (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    )
                  })
                )}
              </select>
              <p className="text-xs text-muted-foreground">
                리소스 그룹 및 사전 인프라 템플릿이 배포될 리전입니다.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="denied_services">차단 Azure 리소스 타입</Label>
              <select
                id="denied_services"
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
                <option value="">차단할 리소스 타입 선택</option>
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
                워크샵에서 차단할 Azure 리소스를 선택하세요. 선택하지 않으면 모든 리소스가 허용됩니다.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="vm_sku_preset">VM 크기 제한</Label>
              {isVmBlocked ? (
                <p className="text-sm text-muted-foreground italic">
                  VM이 차단되어 있어 VM 크기 제한을 설정할 수 없습니다.
                </p>
              ) : (
                <>
                  <select
                    id="vm_sku_preset"
                    value={selectedPreset}
                    onChange={(e) => {
                      const preset = e.target.value
                      setSelectedPreset(preset)
                      if (preset && vmSkuPresets?.[preset]) {
                        const availableSkuNames = new Set(
                          vmSkus.map((sku) => sku.name)
                        )
                        setSelectedVmSkus(
                          vmSkuPresets[preset].skus.filter((sku) =>
                            availableSkuNames.has(sku)
                          )
                        )
                      } else {
                        setSelectedVmSkus([])
                      }
                    }}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
                  >
                    <option value="">제한 없음 (모든 VM 크기 허용)</option>
                    {vmSkuPresets && Object.entries(vmSkuPresets).map(([key, preset]) => (
                      <option key={key} value={key}>
                        {preset.label} — {preset.description}
                      </option>
                    ))}
                  </select>

                  {selectedVmSkus.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {selectedVmSkus.map((sku) => (
                        <span
                          key={sku}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-sm"
                        >
                          {sku}
                          <button
                            type="button"
                            onClick={() =>
                              setSelectedVmSkus(
                                selectedVmSkus.filter((s) => s !== sku)
                              )
                            }
                            className="hover:bg-primary/20 rounded-full p-0.5"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="flex gap-2 mt-2">
                    <select
                      value=""
                      onChange={(e) => {
                        const value = e.target.value
                        if (value && !selectedVmSkus.includes(value)) {
                          setSelectedVmSkus([...selectedVmSkus, value])
                          if (selectedPreset) setSelectedPreset("")
                        }
                      }}
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-muted-foreground"
                    >
                      <option value="">커스텀 SKU 추가...</option>
                      {vmSkus
                        .filter((sku) => !selectedVmSkus.includes(sku.name))
                        .map((sku) => (
                          <option key={sku.name} value={sku.name}>
                            {sku.name} ({sku.vcpus}vCPU, {sku.memory_gb}GB)
                          </option>
                        ))}
                    </select>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    선택한 모든 리전에 공통으로 배포 가능한 VM SKU만 표시됩니다.
                    프리셋을 선택하거나 직접 허용할 SKU를 추가하세요. 미선택 시 모든 VM 크기가 허용됩니다.
                  </p>
                </>
              )}
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

            <div className="space-y-2">
              <Label htmlFor="infra_template">인프라 템플릿</Label>
              {templateMode === "upload" ? (
                /* File upload mode: show file chip + cancel button */
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => document.getElementById("template-file-upload")?.click()}
                  >
                    <Upload className="h-4 w-4 mr-1" />
                    {templateFile ? "파일 변경" : "템플릿 파일 선택"}
                  </Button>
                  {templateFile && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-sm">
                      {templateFile.name}
                      <button
                        type="button"
                        onClick={() => setTemplateFile(null)}
                        className="hover:bg-primary/20 rounded-full p-0.5"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setTemplateMode("none")
                      setTemplateFile(null)
                      setParametersFile(null)
                    }}
                    className="text-muted-foreground"
                  >
                    취소
                  </Button>
                  <input
                    id="template-file-upload"
                    type="file"
                    accept=".json,.bicep"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) setTemplateFile(file)
                      e.target.value = ""
                    }}
                    className="hidden"
                  />
                </div>
              ) : (
                /* Normal mode: dropdown + upload button side by side */
                <div className="flex gap-2">
                  <select
                    id="infra_template"
                    value={formData.infra_template}
                    onChange={(e) => {
                      const value = e.target.value
                      if (value === "") {
                        setTemplateMode("none")
                        setFormData({ ...formData, infra_template: "" })
                        setParametersFile(null)
                      } else {
                        setTemplateMode("preset")
                        setFormData({ ...formData, infra_template: value })
                      }
                    }}
                    disabled={isTemplatesLoading}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value="">
                      {isTemplatesLoading ? "불러오는 중..." : "선택 안 함"}
                    </option>
                    {templates.map((template) => (
                      <option key={template.path} value={template.path}>
                        {template.name} [{(template.template_type ?? "arm").toUpperCase()}]
                      </option>
                    ))}
                  </select>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    onClick={() => {
                      setTemplateMode("upload")
                      setFormData({ ...formData, infra_template: "" })
                    }}
                  >
                    <Upload className="h-4 w-4 mr-1" />
                    파일 업로드
                  </Button>
                </div>
              )}

              {templateMode !== "none" && (
                <div className="flex items-center gap-2 mt-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => document.getElementById("parameters-file-upload")?.click()}
                  >
                    <Upload className="h-4 w-4 mr-1" />
                    {parametersFile ? "파라미터 파일 변경" : "파라미터 파일 (.parameters.json)"}
                  </Button>
                  {parametersFile && (
                    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-primary/10 text-primary text-sm">
                      {parametersFile.name}
                      <button
                        type="button"
                        onClick={() => setParametersFile(null)}
                        className="hover:bg-primary/20 rounded-full p-0.5"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  <input
                    id="parameters-file-upload"
                    type="file"
                    accept=".json"
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) setParametersFile(file)
                      e.target.value = ""
                    }}
                    className="hidden"
                  />
                </div>
              )}

              <p className="text-xs text-muted-foreground">
                {templateMode === "upload"
                  ? "ARM(.json) 또는 Bicep(.bicep) 파일을 업로드하세요. 이 워크샵에만 일회성으로 사용됩니다."
                  : templateMode === "preset"
                    ? "선택한 템플릿이 각 참가자 리소스 그룹에 배포됩니다."
                    : "사전 등록 템플릿을 선택하거나, 파일을 직접 업로드할 수 있습니다."}
              </p>
            </div>

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
                M365 Forms 만족도 조사 링크를 입력하세요. 나중에 추가할 수도 있습니다.{" "}
                <a
                  href="https://forms.office.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-500 hover:text-sky-600 hover:underline"
                >
                  아직 폼이 없으신가요? 새 폼 만들기
                </a>
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
