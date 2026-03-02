import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useSuspenseQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Suspense, useMemo, useState } from "react"
import { Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Calendar,
  Users,
  MapPin,
  Trash2,
  Copy,
  Mail,
  Download,
  Server,
  RefreshCw,
  DollarSign,
  AlertCircle,
  ClipboardList,
  ExternalLink,
  Check,
  Link as LinkIcon,
  AlertTriangle,
  RotateCw,
  UserX,
  FolderX,
  ChevronDown,
} from "lucide-react"

import { workshopApi, type Participant, type AzureResource, type CostBreakdown, type DeletionFailure, type SubscriptionInfo } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
import useCustomToast from "@/hooks/useCustomToast"
import useAuth from "@/hooks/useAuth"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"

function getWorkshopQueryOptions(workshopId: string) {
  return {
    queryFn: () => workshopApi.get(workshopId),
    queryKey: ["workshop", workshopId],
  }
}

export const Route = createFileRoute("/_layout/workshops/$workshopId")({
  component: WorkshopDetail,
})

function ParticipantRow({
  participant,
  workshopId,
  availableSubscriptions,
  invalidAliases,
}: {
  participant: Participant
  workshopId: string
  availableSubscriptions?: SubscriptionInfo[]
  invalidAliases: Set<string>
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const alias = participant.alias || participant.name
  const isInvalid = alias ? invalidAliases.has(alias) : false
  const [selectedSub, setSelectedSub] = useState(
    participant.subscription_id || availableSubscriptions?.[0]?.subscription_id || ""
  )

  const reassignMutation = useMutation({
    mutationFn: (subscriptionId: string) =>
      workshopApi.reassignParticipantSubscription(workshopId, alias || "", subscriptionId),
    onSuccess: () => {
      showSuccessToast("구독이 재배정되었습니다")
      queryClient.invalidateQueries({ queryKey: ["workshop", workshopId] })
    },
    onError: () => {
      showErrorToast("재배정에 실패했습니다")
    },
  })

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    showSuccessToast("클립보드에 복사되었습니다")
  }

  return (
    <div className="flex flex-col gap-3 p-4 border rounded-lg">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <div className="font-medium">{alias}</div>
          <div className="text-sm text-muted-foreground flex items-center gap-1">
            <Mail className="h-3 w-3" />
            {participant.user_principal_name || participant.upn || participant.alias}
          </div>
          {participant.resource_group && (
            <div className="text-sm text-muted-foreground">
              리소스 그룹: {participant.resource_group}
            </div>
          )}
          {participant.subscription_id && (
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <span className="font-medium">구독</span>
              <span className={isInvalid ? "text-red-600" : ""}>
                {participant.subscription_id}
              </span>
              {isInvalid && (
                <span className="inline-flex items-center gap-1 text-red-600 text-xs">
                  <AlertTriangle className="h-3 w-3" />
                  유효하지 않은 구독
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          {participant.user_principal_name && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => copyToClipboard(participant.user_principal_name!)}
            >
              <Copy className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {isInvalid && user?.role === "admin" && availableSubscriptions?.length ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">가용 구독 중 선택</span>
          <select
            className="border rounded px-2 py-1 text-sm"
            value={selectedSub}
            onChange={(e) => setSelectedSub(e.target.value)}
          >
            {availableSubscriptions.map((sub) => (
              <option key={sub.subscription_id} value={sub.subscription_id}>
                {sub.display_name || sub.subscription_id}
              </option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => reassignMutation.mutate(selectedSub)}
            disabled={reassignMutation.isPending || !selectedSub}
          >
            {reassignMutation.isPending ? (
              <RefreshCw className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <RotateCw className="h-4 w-4 mr-1" />
            )}
            재배정
          </Button>
        </div>
      ) : null}
    </div>
  )
}

function ResourceRow({ resource }: { resource: AzureResource }) {
  // 리소스 타입에서 아이콘/색상 결정
  const getResourceTypeDisplay = (type: string) => {
    const typeParts = type.split('/')
    return typeParts[typeParts.length - 1]
  }

  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-md bg-primary/10">
          <Server className="h-4 w-4 text-primary" />
        </div>
        <div className="flex flex-col gap-1">
          <div className="font-medium">{resource.name}</div>
          <div className="text-sm text-muted-foreground">
            {getResourceTypeDisplay(resource.type)} · {resource.location}
          </div>
        </div>
      </div>
    </div>
  )
}

function ResourcesList({ workshopId, refetch, isRefetching }: { workshopId: string; refetch: () => void; isRefetching: boolean }) {
  const { data, isLoading } = useQuery({
    queryKey: ['workshop-resources', workshopId],
    queryFn: () => workshopApi.getResources(workshopId),
  })

  const COLLAPSE_THRESHOLD = 5

  // Group resources by participant
  const groupedResources = useMemo(() => {
    if (!data?.resources) return {}
    return data.resources.reduce<Record<string, AzureResource[]>>(
      (groups, resource) => {
        const key = resource.participant || "unknown"
        if (!groups[key]) groups[key] = []
        groups[key].push(resource)
        return groups
      },
      {},
    )
  }, [data?.resources])

  const participantCount = Object.keys(groupedResources).length
  const defaultOpen = participantCount <= COLLAPSE_THRESHOLD

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <RefreshCw className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
        <p className="text-muted-foreground mt-2">리소스 조회 중...</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          총 {data?.total_count || 0}개의 리소스 · {participantCount}명의 참가자
        </p>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${isRefetching ? 'animate-spin' : ''}`} />
          새로고침
        </Button>
      </div>
      {data?.resources && data.resources.length > 0 ? (
        <div className="space-y-3">
          {Object.entries(groupedResources).map(([participant, resources]) => {
            const resourceGroup = resources[0]?.resource_group || ""
            return (
              <div key={participant} className="rounded-lg border overflow-hidden">
                <Collapsible defaultOpen={defaultOpen}>
                  <CollapsibleTrigger className="flex items-center justify-between w-full p-3 bg-muted/30 hover:bg-muted/50 transition-colors group">
                    <div className="flex items-center gap-2">
                      <ChevronDown className="h-4 w-4 text-muted-foreground transition-transform group-data-[state=closed]:-rotate-90" />
                      <Users className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{participant}</span>
                      <span className="text-xs text-muted-foreground">
                        {resourceGroup}
                      </span>
                    </div>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                      {resources.length}개
                    </span>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="border-t bg-background">
                    <div className="space-y-2 p-3">
                      {resources.map((resource) => (
                        <ResourceRow key={resource.id} resource={resource} />
                      ))}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-muted-foreground text-center py-8">
          생성된 리소스가 없습니다
        </p>
      )}
    </div>
  )
}

function CostBreakdownRow({ item, alias }: { item: CostBreakdown; alias?: string }) {
  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-md bg-primary/10">
          <DollarSign className="h-4 w-4 text-primary" />
        </div>
        <div className="flex flex-col gap-1">
          {alias && (
            <div className="font-medium text-sm">
              {alias}
            </div>
          )}
          <div className="font-medium text-xs text-muted-foreground truncate max-w-[300px]">
            {item.subscription_id}
          </div>
          {item.error && (
            <div className="text-xs text-yellow-600 flex items-center gap-1">
              <AlertCircle className="h-3 w-3" />
              비용 조회 오류
            </div>
          )}
        </div>
      </div>
      <div className="text-right">
        <span className="text-lg font-semibold">
          ${item.cost.toFixed(2)}
        </span>
      </div>
    </div>
  )
}

function CostAnalysis({ workshopId, participants, refetch, isRefetching }: { workshopId: string; participants?: Participant[]; refetch: () => void; isRefetching: boolean }) {
  const subscriptionToAlias = useMemo(() => {
    const map = new Map<string, string>()
    participants?.forEach((p) => {
      if (p.subscription_id && p.alias) {
        map.set(p.subscription_id, p.alias)
      }
    })
    return map
  }, [participants])
  const { data, isLoading } = useQuery({
    queryKey: ['workshop-cost', workshopId],
    queryFn: () => workshopApi.getCost(workshopId),
  })

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <RefreshCw className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
        <p className="text-muted-foreground mt-2">비용 데이터 조회 중...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 비용 요약 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <DollarSign className="h-5 w-5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">총 비용</span>
          <span className="text-2xl font-bold">
            {data?.currency === 'USD' ? '$' : data?.currency}
            {data?.total_cost?.toFixed(2) || '0.00'}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isRefetching}
        >
          <RefreshCw className={`h-4 w-4 mr-1 ${isRefetching ? 'animate-spin' : ''}`} />
          새로고침
        </Button>
      </div>

      {/* 참가자별 비용 상세 */}
      <div className="space-y-3">
        <p className="text-sm font-medium">참가자별 비용 상세</p>
        {data?.breakdown && data.breakdown.length > 0 ? (
          <div className="space-y-2">
            {data.breakdown.map((item) => (
              <CostBreakdownRow key={item.subscription_id} item={item} alias={subscriptionToAlias.get(item.subscription_id)} />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-center py-8">
            비용 데이터가 없습니다
          </p>
        )}
      </div>
    </div>
  )
}

function SurveyTab({ workshopId, surveyUrl }: { workshopId: string; surveyUrl?: string }) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()
  const [urlInput, setUrlInput] = useState(surveyUrl || "")
  const [isSaved, setIsSaved] = useState(!!surveyUrl)

  const updateUrlMutation = useMutation({
    mutationFn: (url: string) => workshopApi.updateSurveyUrl(workshopId, url),
    onSuccess: () => {
      showSuccessToast("만족도 조사 URL이 저장되었습니다")
      setIsSaved(true)
      queryClient.invalidateQueries({ queryKey: ["workshop", workshopId] })
    },
    onError: () => {
      showErrorToast("URL 저장에 실패했습니다")
    },
  })

  const handleSaveUrl = () => {
    if (!urlInput.trim()) {
      showErrorToast("URL을 입력해 주세요")
      return
    }
    updateUrlMutation.mutate(urlInput.trim())
  }

  const copyToClipboard = () => {
    navigator.clipboard.writeText(urlInput)
    showSuccessToast("클립보드에 복사되었습니다")
  }

  return (
    <div className="space-y-4">
      {/* URL 관리 */}
      <Card>
        <CardHeader>
          <CardTitle>만족도 조사 URL</CardTitle>
          <CardDescription>
            M365 Forms에서 생성한 만족도 조사 링크를 등록하세요
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              type="url"
              placeholder="https://forms.office.com/..."
              value={urlInput}
              onChange={(e) => {
                setUrlInput(e.target.value)
                setIsSaved(false)
              }}
              className="flex-1"
            />
            <Button
              onClick={handleSaveUrl}
              disabled={updateUrlMutation.isPending || (!urlInput.trim())}
            >
              {updateUrlMutation.isPending ? (
                <RefreshCw className="h-4 w-4 animate-spin mr-2" />
              ) : isSaved ? (
                <Check className="h-4 w-4 mr-2" />
              ) : (
                <LinkIcon className="h-4 w-4 mr-2" />
              )}
              {isSaved ? "저장됨" : "저장"}
            </Button>
          </div>
          {isSaved && urlInput && (
            <div className="flex items-center gap-2 text-sm">
              <a
                href={urlInput}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline flex items-center gap-1 truncate"
              >
                <ExternalLink className="h-3 w-3 flex-shrink-0" />
                {urlInput}
              </a>
              <Button variant="ghost" size="sm" onClick={copyToClipboard}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 설문 링크는 직접 공유 안내 (개인 이메일 미저장으로 이메일 전송 불가) */}
      <Card>
        <CardHeader>
          <CardTitle>설문 링크 공유</CardTitle>
          <CardDescription>
            참가자에게 만족도 조사 링크를 직접 공유해 주세요
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isSaved && urlInput ? (
            <div className="flex items-center gap-4">
              <Button variant="outline" onClick={copyToClipboard}>
                <Copy className="h-4 w-4 mr-2" />
                링크 복사
              </Button>
              <p className="text-sm text-muted-foreground">
                복사한 링크를 Teams, 채팅 등으로 참가자에게 공유하세요
              </p>
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">
              먼저 만족도 조사 URL을 등록해 주세요.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Forms 결과 조회 */}
      {isSaved && urlInput && (
        <Card>
          <CardHeader>
            <CardTitle>결과 조회</CardTitle>
            <CardDescription>
              M365 Forms 결과 페이지에서 응답을 확인할 수 있습니다
            </CardDescription>
          </CardHeader>
          <CardContent>
            <a
              href={urlInput}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button variant="outline">
                <ExternalLink className="h-4 w-4 mr-2" />
                Forms 결과 보기
              </Button>
            </a>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function DeletionFailureRow({
  failure,
  workshopId,
}: {
  failure: DeletionFailure
  workshopId: string
}) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const retryMutation = useMutation({
    mutationFn: () => workshopApi.retryDeletion(workshopId, failure.id),
    onSuccess: (data) => {
      showSuccessToast(data.detail || "삭제에 성공했습니다")
      queryClient.invalidateQueries({
        queryKey: ["deletion-failures", workshopId],
      })
      queryClient.invalidateQueries({ queryKey: ["workshop", workshopId] })
    },
    onError: () => {
      showErrorToast("재시도에 실패했습니다")
      queryClient.invalidateQueries({
        queryKey: ["deletion-failures", workshopId],
      })
    },
  })

  const isResourceGroup = failure.resource_type === "resource_group"
  const TypeIcon = isResourceGroup ? FolderX : UserX

  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-md bg-red-100 dark:bg-red-900/30">
          <TypeIcon className="h-4 w-4 text-red-600 dark:text-red-400" />
        </div>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="font-medium">{failure.resource_name}</span>
            <span className="px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground">
              {isResourceGroup ? "리소스 그룹" : "사용자"}
            </span>
          </div>
          <div className="text-sm text-red-600 dark:text-red-400 flex items-center gap-1">
            <AlertCircle className="h-3 w-3 flex-shrink-0" />
            <span className="line-clamp-1">{failure.error_message}</span>
          </div>
          <div className="text-xs text-muted-foreground flex items-center gap-3">
            <span>
              {new Date(failure.failed_at).toLocaleString("ko-KR", {
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
            {failure.retry_count > 0 && (
              <span>재시도 {failure.retry_count}회</span>
            )}
            {failure.subscription_id && (
              <span className="truncate max-w-[200px]">
                구독: {failure.subscription_id}
              </span>
            )}
          </div>
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => retryMutation.mutate()}
        disabled={retryMutation.isPending}
        className="shrink-0"
      >
        {retryMutation.isPending ? (
          <RefreshCw className="h-4 w-4 animate-spin mr-1" />
        ) : (
          <RotateCw className="h-4 w-4 mr-1" />
        )}
        수동 삭제
      </Button>
    </div>
  )
}

function DeletionFailuresTab({ workshopId }: { workshopId: string }) {
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ["deletion-failures", workshopId],
    queryFn: () => workshopApi.getDeletionFailures(workshopId),
  })

  const retryAllMutation = useMutation({
    mutationFn: () => workshopApi.retryAllDeletions(workshopId),
    onSuccess: (data) => {
      showSuccessToast(data.detail || "전체 재시도 완료")
      queryClient.invalidateQueries({
        queryKey: ["deletion-failures", workshopId],
      })
      queryClient.invalidateQueries({ queryKey: ["workshop", workshopId] })
    },
    onError: () => {
      showErrorToast("전체 재시도에 실패했습니다")
    },
  })

  if (isLoading) {
    return (
      <div className="text-center py-8">
        <RefreshCw className="h-6 w-6 animate-spin mx-auto text-muted-foreground" />
        <p className="text-muted-foreground mt-2">삭제 실패 항목 조회 중...</p>
      </div>
    )
  }

  const items = data?.items || []

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-red-500" />
              삭제 실패 항목
            </CardTitle>
            <CardDescription>
              자동 삭제에 실패한 리소스 및 계정 목록입니다. 수동으로 삭제를
              재시도할 수 있습니다.
            </CardDescription>
          </div>
          {items.length > 0 && (
            <Button
              onClick={() => retryAllMutation.mutate()}
              disabled={retryAllMutation.isPending}
              size="sm"
            >
              {retryAllMutation.isPending ? (
                <RefreshCw className="h-4 w-4 animate-spin mr-1" />
              ) : (
                <RotateCw className="h-4 w-4 mr-1" />
              )}
              전체 재시도
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {items.length > 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              총 {data?.total_count || 0}개의 실패 항목
            </p>
            {items.map((failure) => (
              <DeletionFailureRow
                key={failure.id}
                failure={failure}
                workshopId={workshopId}
              />
            ))}
          </div>
        ) : (
          <p className="text-muted-foreground text-center py-8">
            삭제 실패 항목이 없습니다
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function WorkshopDetailContent({ workshopId }: { workshopId: string }) {
  const { data: workshop } = useSuspenseQuery(getWorkshopQueryOptions(workshopId))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const invalidAliases = new Set(
    workshop.invalid_participants?.map((p) => p.alias) || []
  )

  const deleteMutation = useMutation({
    mutationFn: () => workshopApi.delete(workshopId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workshops"] })
      showSuccessToast("워크샵이 삭제되었습니다")
      navigate({ to: "/" })
    },
    onError: () => {
      showErrorToast("워크샵 삭제에 실패했습니다")
    },
  })
  
  // Resources and Cost queries for refresh functionality
  const { refetch: refetchResources, isRefetching: isRefetchingResources } = useQuery({
    queryKey: ['workshop-resources', workshopId],
    queryFn: () => workshopApi.getResources(workshopId),
  })
  
  const { refetch: refetchCost, isRefetching: isRefetchingCost } = useQuery({
    queryKey: ['workshop-cost', workshopId],
    queryFn: () => workshopApi.getCost(workshopId),
  })

  const statusColors: Record<string, string> = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    completed: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    draft: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
    deleted: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight">
                {workshop.name}
              </h1>
              <span
                className={`px-2 py-1 rounded-full text-xs font-medium ${statusColors[workshop.status]}`}
              >
                {workshop.status}
              </span>
            </div>
            <p className="text-muted-foreground">{workshop.description}</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => workshopApi.downloadPasswords(workshop.id)}
          >
            <Download className="h-4 w-4 mr-2" />
            계정 정보 다운로드
          </Button>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="destructive" size="sm" disabled={deleteMutation.isPending}>
                <Trash2 className="h-4 w-4 mr-2" />
                {deleteMutation.isPending ? "삭제 중..." : "삭제"}
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>워크샵을 삭제하시겠습니까?</AlertDialogTitle>
                <AlertDialogDescription>
                  워크샵 "{workshop.name}"을(를) 삭제하면 관련된 리소스 그룹과 참가자 계정이 모두 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>취소</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => deleteMutation.mutate()}
                  className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                >
                  삭제
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card className="flex items-center">
          <CardContent className="py-4 w-full">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <MapPin className="h-4 w-4" />
                <span className="text-sm">리전</span>
              </div>
              <p className="text-xl font-semibold">
                {workshop.policy?.allowed_regions?.join(", ") || "-"}
              </p>
            </div>
          </CardContent>
        </Card>
        <Card className="flex items-center">
          <CardContent className="py-4 w-full">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Users className="h-4 w-4" />
                <span className="text-sm">참가자</span>
              </div>
              <p className="text-xl font-semibold">{workshop.participants?.length || 0}명</p>
            </div>
          </CardContent>
        </Card>
        <Card className="flex items-center">
          <CardContent className="py-4 w-full">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Calendar className="h-4 w-4" />
                <span className="text-sm">기간</span>
              </div>
              <div className="text-lg font-semibold leading-relaxed">
                <p>{new Date(workshop.start_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>
                <p>{new Date(workshop.end_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="flex items-center">
          <CardContent className="py-4 w-full">
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 text-muted-foreground">
                <ClipboardList className="h-4 w-4" />
                <span className="text-sm">만족도 조사</span>
              </div>
              <p className="text-xl font-semibold">
                {workshop.survey_url ? "등록됨" : "미등록"}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="participants">
        <TabsList>
          <TabsTrigger value="participants">참가자</TabsTrigger>
          <TabsTrigger value="resources">리소스</TabsTrigger>
          <TabsTrigger value="costs">비용</TabsTrigger>
          <TabsTrigger value="survey">설문</TabsTrigger>
          {workshop.status === "failed" && (
            <TabsTrigger value="deletion-failures" className="text-red-600 dark:text-red-400">
              <AlertTriangle className="h-4 w-4 mr-1" />
              삭제 실패 항목
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="participants" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>참가자 목록</CardTitle>
              <CardDescription>
                워크샵에 등록된 참가자 목록입니다
              </CardDescription>
              {invalidAliases.size > 0 && (
                <div className="flex items-center gap-2 text-sm text-amber-600 mt-1">
                  <AlertTriangle className="h-4 w-4" />
                  유효하지 않은 구독이 배정된 참가자 {invalidAliases.size}명. 관리자만 재배정할 수 있습니다.
                </div>
              )}
            </CardHeader>
            <CardContent>
              {workshop.participants && workshop.participants.length > 0 ? (
                <div className="space-y-3">
                  {workshop.participants.map((participant, index) => (
                    <ParticipantRow
                      key={participant.alias || index}
                      participant={participant}
                      workshopId={workshop.id}
                      availableSubscriptions={workshop.available_subscriptions}
                      invalidAliases={invalidAliases}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-center py-8">
                  등록된 참가자가 없습니다
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="resources" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Azure 리소스</CardTitle>
              <CardDescription>
                생성된 Azure 리소스 정보입니다
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResourcesList workshopId={workshop.id} refetch={refetchResources} isRefetching={isRefetchingResources} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="costs" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>비용 분석</CardTitle>
              <CardDescription>
                워크샵 기간({new Date(workshop.start_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ~ {new Date(workshop.end_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })})의 비용 현황입니다
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CostAnalysis workshopId={workshop.id} participants={workshop.participants} refetch={refetchCost} isRefetching={isRefetchingCost} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="survey" className="mt-4">
          <SurveyTab workshopId={workshop.id} surveyUrl={workshop.survey_url} />
        </TabsContent>

        {workshop.status === "failed" && (
          <TabsContent value="deletion-failures" className="mt-4">
            <DeletionFailuresTab workshopId={workshop.id} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}

function WorkshopDetail() {
  const { workshopId } = Route.useParams()

  return (
    <Suspense
      fallback={
        <div className="flex flex-col gap-6">
          <div className="animate-pulse">
            <div className="h-8 bg-muted rounded w-1/3 mb-2"></div>
            <div className="h-4 bg-muted rounded w-1/2"></div>
          </div>
        </div>
      }
    >
      <WorkshopDetailContent workshopId={workshopId} />
    </Suspense>
  )
}
