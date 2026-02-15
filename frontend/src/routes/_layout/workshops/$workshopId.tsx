import { createFileRoute } from "@tanstack/react-router"
import { useSuspenseQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Suspense, useState } from "react"
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
  TrendingUp,
  AlertCircle,
  ClipboardList,
  ExternalLink,
  Send,
  Check,
  Link as LinkIcon,
} from "lucide-react"

import { workshopApi, type Participant, type AzureResource, type CostBreakdown } from "@/client"
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
import useCustomToast from "@/hooks/useCustomToast"

function getWorkshopQueryOptions(workshopId: string) {
  return {
    queryFn: () => workshopApi.get(workshopId),
    queryKey: ["workshop", workshopId],
  }
}

export const Route = createFileRoute("/_layout/workshops/$workshopId")({
  component: WorkshopDetail,
})

function ParticipantRow({ participant }: { participant: Participant }) {
  const { showSuccessToast } = useCustomToast()

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    showSuccessToast("클립보드에 복사되었습니다")
  }

  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex flex-col gap-1">
        <div className="font-medium">{participant.name}</div>
        <div className="text-sm text-muted-foreground flex items-center gap-1">
          <Mail className="h-3 w-3" />
          {participant.email}
        </div>
        {participant.resource_group && (
          <div className="text-sm text-muted-foreground">
            리소스 그룹: {participant.resource_group}
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
          <div className="text-xs text-muted-foreground">
            참가자: {resource.participant} · {resource.resource_group}
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
          총 {data?.total_count || 0}개의 리소스
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
        <div className="space-y-2">
          {data.resources.map((resource) => (
            <ResourceRow key={resource.id} resource={resource} />
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground text-center py-8">
          생성된 리소스가 없습니다
        </p>
      )}
    </div>
  )
}

function CostBreakdownRow({ item }: { item: CostBreakdown }) {
  return (
    <div className="flex items-center justify-between p-4 border rounded-lg">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-md bg-primary/10">
          <DollarSign className="h-4 w-4 text-primary" />
        </div>
        <div className="flex flex-col gap-1">
          <div className="font-medium">{item.resource_group}</div>
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

function CostAnalysis({ workshopId, refetch, isRefetching }: { workshopId: string; refetch: () => void; isRefetching: boolean }) {
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
              <CostBreakdownRow key={item.resource_group} item={item} />
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

  const sendSurveyMutation = useMutation({
    mutationFn: () => workshopApi.sendSurvey(workshopId),
    onSuccess: (data) => {
      showSuccessToast(
        `설문 링크 전송 완료: ${data.sent}명 성공, ${data.failed}명 실패`
      )
    },
    onError: () => {
      showErrorToast("설문 링크 전송에 실패했습니다")
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

      {/* 설문 링크 공유 */}
      <Card>
        <CardHeader>
          <CardTitle>설문 링크 공유</CardTitle>
          <CardDescription>
            참가자에게 만족도 조사 링크를 이메일로 전송합니다
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isSaved && urlInput ? (
            <div className="flex items-center gap-4">
              <Button
                onClick={() => sendSurveyMutation.mutate()}
                disabled={sendSurveyMutation.isPending}
              >
                {sendSurveyMutation.isPending ? (
                  <RefreshCw className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Send className="h-4 w-4 mr-2" />
                )}
                {sendSurveyMutation.isPending
                  ? "전송 중..."
                  : "전체 참가자에게 전송"}
              </Button>
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

function WorkshopDetailContent({ workshopId }: { workshopId: string }) {
  const { data: workshop } = useSuspenseQuery(getWorkshopQueryOptions(workshopId))
  
  // Resources and Cost queries for refresh functionality
  const { refetch: refetchResources, isRefetching: isRefetchingResources } = useQuery({
    queryKey: ['workshop-resources', workshopId],
    queryFn: () => workshopApi.getResources(workshopId),
  })
  
  const { refetch: refetchCost, isRefetching: isRefetchingCost } = useQuery({
    queryKey: ['workshop-cost', workshopId],
    queryFn: () => workshopApi.getCost(workshopId),
  })

  const statusColors = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    completed: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    draft: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
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
          <Button variant="destructive" size="sm">
            <Trash2 className="h-4 w-4 mr-2" />
            삭제
          </Button>
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
              <p className="text-xl font-semibold">
                {new Date(workshop.start_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ~ {new Date(workshop.end_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </p>
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
        </TabsList>

        <TabsContent value="participants" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>참가자 목록</CardTitle>
              <CardDescription>
                워크샵에 등록된 참가자 목록입니다
              </CardDescription>
            </CardHeader>
            <CardContent>
              {workshop.participants && workshop.participants.length > 0 ? (
                <div className="space-y-3">
                  {workshop.participants.map((participant, index) => (
                    <ParticipantRow key={index} participant={participant} />
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
                워크샵 기간({new Date(workshop.start_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })} ~ {new Date(workshop.end_date).toLocaleString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}) 동안의 비용 현황입니다
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CostAnalysis workshopId={workshop.id} refetch={refetchCost} isRefetching={isRefetchingCost} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="survey" className="mt-4">
          <SurveyTab workshopId={workshop.id} surveyUrl={workshop.survey_url} />
        </TabsContent>
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
