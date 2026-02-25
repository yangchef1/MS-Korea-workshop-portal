import { createFileRoute } from "@tanstack/react-router"
import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, ShieldCheck, ShieldOff, Save, Lock } from "lucide-react"

import { subscriptionAdminApi, type SubscriptionSettingsResponse } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"

export const Route = createFileRoute("/_layout/subscriptions")({
  component: SubscriptionAdminPage,
})

function SubscriptionAdminPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const { data, isLoading, isRefetching } = useQuery({
    queryKey: ["admin-subscriptions"],
    queryFn: () => subscriptionAdminApi.get(),
  })

  const [allowSet, setAllowSet] = useState<Set<string>>(new Set())
  const [denySet, setDenySet] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (data) {
      setAllowSet(new Set(data.allow_list || []))
      setDenySet(new Set(data.deny_list || []))
    }
  }, [data])

  const availableSubs = useMemo(() => data?.subscriptions || [], [data])
  const inUseMap: Record<string, string> = useMemo(() => data?.in_use_map || {}, [data])

  const refreshMutation = useMutation({
    mutationFn: () => subscriptionAdminApi.get(true),
    onSuccess: (result) => {
      queryClient.setQueryData(["admin-subscriptions"], result)
      setAllowSet(new Set(result.allow_list || []))
      setDenySet(new Set(result.deny_list || []))
      showSuccessToast("구독 목록을 새로고침했습니다")
    },
    onError: () => {
      showErrorToast("구독 새로고침에 실패했습니다")
    },
  })

  const saveMutation = useMutation({
    mutationFn: () =>
      subscriptionAdminApi.update(
        Array.from(allowSet.values()),
        Array.from(denySet.values())
      ),
    onSuccess: (result: SubscriptionSettingsResponse) => {
      queryClient.setQueryData(["admin-subscriptions"], result)
      setAllowSet(new Set(result.allow_list || []))
      setDenySet(new Set(result.deny_list || []))
      showSuccessToast("저장되었습니다")
    },
    onError: () => {
      showErrorToast("저장에 실패했습니다")
    },
  })

  const handleToggleAllow = (id: string) => {
    const nextAllow = new Set(allowSet)
    const nextDeny = new Set(denySet)
    if (nextAllow.has(id)) {
      nextAllow.delete(id)
    } else {
      nextAllow.add(id)
      nextDeny.delete(id)
    }
    setAllowSet(nextAllow)
    setDenySet(nextDeny)
  }

  const handleToggleDeny = (id: string) => {
    const nextAllow = new Set(allowSet)
    const nextDeny = new Set(denySet)
    if (nextDeny.has(id)) {
      nextDeny.delete(id)
    } else {
      nextDeny.add(id)
      nextAllow.delete(id)
    }
    setAllowSet(nextAllow)
    setDenySet(nextDeny)
  }

  if (user?.role !== "admin") {
    return (
      <div className="space-y-2">
        <h1 className="text-xl font-semibold">구독 관리</h1>
        <p className="text-muted-foreground">관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

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
            허용/제외 목록을 설정합니다. 허용 목록을 비워두면 (기본값) 모든 구독을 사용하며, 제외 목록은 항상 적용됩니다. 포털 배포 구독은 자동으로 제외됩니다.
          </p>
        </div>
        <div className="flex gap-2">
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
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? (
              <Save className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Save className="h-4 w-4 mr-1" />
            )}
            저장
          </Button>
        </div>
      </div>

      {data?.pruned_ids && data.pruned_ids.length > 0 && (
        <div className="text-sm text-amber-600">
          Azure에서 찾을 수 없는 구독 {data.pruned_ids.length}개를 설정에서 제거했습니다: {data.pruned_ids.join(", ")}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>사용 가능한 구독</CardTitle>
          <CardDescription>
            체크 박스를 사용해 허용 목록(선택적) 또는 제외 목록을 설정하세요. 제외로 지정하면 허용 여부와 관계없이 배정되지 않습니다.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {availableSubs.length === 0 ? (
            <p className="text-sm text-red-600">사용 가능한 구독이 없습니다.</p>
          ) : (
            availableSubs.map((sub) => {
              const inAllow = allowSet.has(sub.subscription_id)
              const inDeny = denySet.has(sub.subscription_id)
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
                  <div className="flex items-center gap-4 text-sm">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={inAllow}
                        onChange={() => handleToggleAllow(sub.subscription_id)}
                      />
                      <span className="inline-flex items-center gap-1">
                        <ShieldCheck className="h-4 w-4" /> 허용 목록
                      </span>
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={inDeny}
                        onChange={() => handleToggleDeny(sub.subscription_id)}
                      />
                      <span className="inline-flex items-center gap-1">
                        <ShieldOff className="h-4 w-4" /> 제외
                      </span>
                    </label>
                  </div>
                </div>
              )
            })
          )}
        </CardContent>
      </Card>
    </div>
  )
}
