import { createFileRoute } from "@tanstack/react-router"
import { useMemo } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Lock } from "lucide-react"

import { subscriptionApi } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/subscriptions")({
  component: SubscriptionPage,
})

function SubscriptionPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data, isLoading, isRefetching } = useQuery({
    queryKey: ["subscriptions"],
    queryFn: () => subscriptionApi.get(),
  })

  const availableSubs = useMemo(() => data?.subscriptions || [], [data])
  const inUseMap: Record<string, string> = useMemo(() => data?.in_use_map || {}, [data])

  const refreshMutation = useMutation({
    mutationFn: () => subscriptionApi.get(true),
    onSuccess: (result) => {
      queryClient.setQueryData(["subscriptions"], result)
      showSuccessToast("구독 목록을 새로고침했습니다")
    },
    onError: () => {
      showErrorToast("구독 새로고침에 실패했습니다")
    },
  })

  if (isLoading) {
    return (
      <div className="text-center py-8 text-muted-foreground">불러오는 중...</div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">구독 관리</h1>
          <p className="text-muted-foreground text-sm">
            Azure 구독 목록과 현재 워크샵에서 사용 중인 구독 현황을 확인합니다. 포털 배포 구독은 자동으로 제외됩니다.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending || isRefetching}
        >
          {refreshMutation.isPending ? (
            <RefreshCw className="h-4 w-4 animate-spin mr-1" />
          ) : (
            <RefreshCw className="h-4 w-4 mr-1" />
          )}
          즉시 새로고침
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>구독 현황</CardTitle>
          <CardDescription>
            사용 가능한 Azure 구독 목록입니다. 워크샵에 할당된 구독은 "사용 중"으로 표시됩니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {availableSubs.length === 0 ? (
            <p className="text-sm text-red-600">사용 가능한 구독이 없습니다.</p>
          ) : (
            availableSubs.map((sub) => {
              const usedByWorkshop = inUseMap[sub.subscription_id]
              return (
                <div
                  key={sub.subscription_id}
                  className="flex items-center justify-between border rounded-lg p-3"
                >
                  <div>
                    <div className="font-medium flex items-center gap-2">
                      {sub.display_name || sub.subscription_id}
                      {usedByWorkshop && (
                        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                          <Lock className="h-3 w-3" />
                          사용 중: {usedByWorkshop}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {sub.subscription_id}
                    </div>
                  </div>
                  {!usedByWorkshop && (
                    <span className="text-xs text-green-600 dark:text-green-400">사용 가능</span>
                  )}
                </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
