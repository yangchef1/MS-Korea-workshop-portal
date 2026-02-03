import { createFileRoute } from "@tanstack/react-router"
import { useSuspenseQuery, useQuery } from "@tanstack/react-query"
import { Suspense, useState, useEffect } from "react"
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

      <div className="grid gap-4 md:grid-cols-3">
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
                {new Date(workshop.start_date).toLocaleDateString()} ~ {new Date(workshop.end_date).toLocaleDateString()}
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
                워크샵 기간({new Date(workshop.start_date).toLocaleDateString('ko-KR')} ~ {new Date(workshop.end_date).toLocaleDateString('ko-KR')}) 동안의 비용 현황입니다
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CostAnalysis workshopId={workshop.id} refetch={refetchCost} isRefetching={isRefetchingCost} />
            </CardContent>
          </Card>
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
