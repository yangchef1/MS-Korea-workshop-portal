import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useQuery, useSuspenseQuery } from "@tanstack/react-query"
import { Suspense, useState } from "react"
import { Link } from "@tanstack/react-router"
import {
  Plus,
  Calendar,
  Users,
  AlertCircle,
  Info,
  Monitor,
  CheckCircle2,
  Shield,
  User,
  Loader2,
  Clock,
  X,
  ChevronDown,
  ChevronUp,
} from "lucide-react"

import { workshopApi, subscriptionApi, type Workshop } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

/** Poll interval when any workshop is still being provisioned. */
const CREATING_POLL_INTERVAL_MS = 5000

function getWorkshopsQueryOptions() {
  return {
    queryFn: () => workshopApi.list(),
    queryKey: ["workshops"],
    refetchInterval: (query: { state: { data?: Workshop[] } }) => {
      const hasCreating = query.state.data?.some(
        (w) => w.status === "creating"
      )
      return hasCreating ? CREATING_POLL_INTERVAL_MS : false
    },
  }
}

/** Search params schema for the dashboard route. */
interface DashboardSearch {
  createError?: string
  errorDetail?: string
  errorCode?: string
  failedParticipants?: string
}

function parseFailedParticipants(serialized?: string): string[] {
  if (!serialized) {
    return []
  }

  try {
    const parsed = JSON.parse(serialized)
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : []
  } catch {
    return []
  }
}

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  validateSearch: (search: Record<string, unknown>): DashboardSearch => ({
    createError: (search.createError as string) || undefined,
    errorDetail: (search.errorDetail as string) || undefined,
    errorCode: (search.errorCode as string) || undefined,
    failedParticipants: (search.failedParticipants as string) || undefined,
  }),
})

function WorkshopCard({ workshop }: { workshop: Workshop }) {
  const statusColors: Record<string, string> = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    completed: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    creating: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
    scheduled:
      "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
    deleted: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
  }

  const formatDate = (dateStr: string) =>
    new Date(dateStr).toLocaleString("ko-KR", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    })

  const isCreating = workshop.status === "creating"

  const card = (
    <Card
      className={`h-full flex flex-col transition-shadow ${
        isCreating
          ? "opacity-60 cursor-not-allowed"
          : "hover:shadow-md cursor-pointer"
      }`}
    >
      <CardHeader className="flex-none pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-lg truncate">{workshop.name}</CardTitle>
          <span
            className={`px-2 py-1 rounded-full text-xs font-medium whitespace-nowrap shrink-0 ${statusColors[workshop.status] || statusColors.creating}`}
          >
            {workshop.status === "failed" && (
              <AlertCircle className="inline h-3 w-3 mr-1" />
            )}
            {isCreating && (
              <Loader2 className="inline h-3 w-3 mr-1 animate-spin" />
            )}
            {workshop.status === "scheduled" && (
              <Clock className="inline h-3 w-3 mr-1" />
            )}
            {workshop.status === "completed" && (
              <CheckCircle2 className="inline h-3 w-3 mr-1" />
            )}
            {workshop.status}
          </span>
        </div>
        {workshop.description && (
          <CardDescription className="line-clamp-2">
            {workshop.description}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="mt-auto flex-none">
        <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
          {workshop.created_by && (
            <div className="flex items-center gap-1">
              <User className="h-4 w-4 shrink-0" />
              <span className="truncate">{workshop.created_by}</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <Users className="h-4 w-4 shrink-0" />
            {workshop.status === "scheduled"
              ? `${workshop.planned_participant_count ?? 0} 예정`
              : `${workshop.participant_count ?? workshop.participants?.length ?? 0} 참가자`}
          </div>
          <div className="flex items-center gap-1">
            <Calendar className="h-4 w-4 shrink-0" />
            {formatDate(workshop.start_date)} ~ {formatDate(workshop.end_date)}
          </div>
        </div>
      </CardContent>
    </Card>
  )

  if (isCreating) {
    return <div>{card}</div>
  }

  return (
    <Link to="/workshops/$workshopId" params={{ workshopId: workshop.id }}>
      {card}
    </Link>
  )
}

function WorkshopsListContent() {
  const { data: workshops } = useSuspenseQuery(getWorkshopsQueryOptions())

  if (!workshops || workshops.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center text-center py-12">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Calendar className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-semibold">워크샵이 없습니다</h3>
        <p className="text-muted-foreground mb-4">
          새 워크샵을 만들어 시작하세요
        </p>
        <Link to="/workshops/create">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            워크샵 만들기
          </Button>
        </Link>
      </div>
    )
  }

  // Sort: active statuses first (creating, active, scheduled, failed), then completed at the bottom
  const STATUS_ORDER: Record<string, number> = {
    creating: 0,
    active: 1,
    scheduled: 2,
    failed: 3,
    completed: 4,
    deleted: 5,
  }
  const sorted = [...workshops].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99)
  )

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {sorted.map((workshop) => (
        <WorkshopCard key={workshop.id} workshop={workshop} />
      ))}
    </div>
  )
}

function WorkshopsList() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>워크샵 목록</CardTitle>
          <CardDescription>
            등록된 워크샵을 확인하고 관리합니다.
          </CardDescription>
        </div>
        <Link to="/workshops/create">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            워크샵 만들기
          </Button>
        </Link>
      </CardHeader>
      <CardContent>
        <Suspense
          fallback={
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((i) => (
                <Card key={i} className="h-full flex flex-col animate-pulse">
                  <CardHeader className="flex-none pb-2">
                    <div className="h-6 bg-muted rounded w-3/4"></div>
                    <div className="h-4 bg-muted rounded w-1/2 mt-2"></div>
                  </CardHeader>
                  <CardContent className="mt-auto flex-none">
                    <div className="h-4 bg-muted rounded w-full"></div>
                  </CardContent>
                </Card>
              ))}
            </div>
          }
        >
          <WorkshopsListContent />
        </Suspense>
      </CardContent>
    </Card>
  )
}

function SubscriptionSummary() {
  const { data, isLoading } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: () => subscriptionApi.get(),
  })

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="pb-2">
              <div className="h-4 bg-muted rounded w-1/2"></div>
            </CardHeader>
            <CardContent>
              <div className="h-8 bg-muted rounded w-1/3"></div>
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (!data) return null

  const totalCount = data.subscriptions.length
  const inUseCount = Object.keys(data.in_use_map ?? {}).length
  const availableCount = totalCount - inUseCount

  const summaryItems = [
    {
      label: "전체 구독",
      value: totalCount,
      icon: Shield,
      color: "text-blue-600 dark:text-blue-400",
      bgColor: "bg-blue-50 dark:bg-blue-950",
    },
    {
      label: "사용 중",
      value: inUseCount,
      icon: Monitor,
      color: "text-orange-600 dark:text-orange-400",
      bgColor: "bg-orange-50 dark:bg-orange-950",
    },
    {
      label: "사용 가능",
      value: availableCount,
      icon: CheckCircle2,
      color: "text-green-600 dark:text-green-400",
      bgColor: "bg-green-50 dark:bg-green-950",
    },
  ]

  return (
    <div className="space-y-3">
      <div className="grid gap-4 md:grid-cols-3">
        {summaryItems.map((item) => (
          <Card key={item.label}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {item.label}
              </CardTitle>
              <div className={`rounded-md p-1.5 ${item.bgColor}`}>
                <item.icon className={`h-4 w-4 ${item.color}`} />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{item.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
        <Info className="h-4 w-4 shrink-0" />
        <span>추가 구독 필요 시, Junghun Lee님께 문의하세요.</span>
      </div>
    </div>
  )
}

function Dashboard() {
  const { user } = useAuth()
  const { createError, errorDetail, failedParticipants } =
    Route.useSearch()
  const navigate = useNavigate()
  const [showError, setShowError] = useState(true)
  const [expanded, setExpanded] = useState(false)

  const failedList = parseFailedParticipants(failedParticipants)

  const handleDismissError = () => {
    setShowError(false)
    navigate({ to: "/", search: {} })
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            안녕하세요, {user?.name || user?.email} 👋
          </h1>
          <p className="text-muted-foreground">
            Azure Workshop Portal에 오신 것을 환영합니다
          </p>
        </div>
      </div>

      <SubscriptionSummary />

      {createError && showError && (
        <div className="flex flex-col gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="flex-1 font-medium">워크샵 생성에 실패했습니다. {createError}</span>
            <button
              onClick={handleDismissError}
              className="shrink-0 rounded-sm p-0.5 hover:bg-red-100 dark:hover:bg-red-900"
              aria-label="닫기"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {errorDetail && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-200"
            >
              {expanded ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
              {expanded ? "상세 접기" : "상세 보기"}
            </button>
          )}
          {expanded && errorDetail && (
            <div className="mt-1 rounded border border-red-200 bg-red-100/50 px-3 py-2 text-xs dark:border-red-800 dark:bg-red-900/50">
              <p className="whitespace-pre-wrap break-all">{errorDetail}</p>
              {failedList.length > 0 && (
                <ul className="mt-2 list-disc pl-4 space-y-0.5">
                  {failedList.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <WorkshopsList />
    </div>
  )
}
