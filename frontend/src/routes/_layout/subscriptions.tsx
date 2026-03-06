import { createFileRoute } from "@tanstack/react-router"
import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Lock, Unlock, TriangleAlert } from "lucide-react"

import { subscriptionApi } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"
import { useAuth } from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/subscriptions")({
  component: SubscriptionPage,
})

// ------------------------------------------------------------------
// ForceReleaseDialog — 2단계 확인 다이얼로그 (Admin 전용)
// ------------------------------------------------------------------

interface ForceReleaseDialogProps {
  workshopId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  isPending: boolean
}

function ForceReleaseDialog({
  workshopId,
  open,
  onOpenChange,
  onConfirm,
  isPending,
}: ForceReleaseDialogProps) {
  const [step, setStep] = useState<1 | 2>(1)

  function handleOpenChange(next: boolean) {
    if (!next) setStep(1)
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        {step === 1 ? (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <TriangleAlert className="h-5 w-5 text-destructive" />
                구독 강제 해제
              </DialogTitle>
              <DialogDescription className="space-y-2 pt-1">
                <span className="block">
                  워크샵 <strong className="text-foreground">{workshopId}</strong>에
                  할당된 구독을 강제로 해제합니다.
                </span>
                <span className="block text-amber-600 dark:text-amber-400 font-medium">
                  워크샵 생성 실패 후 alloc이 잔존하는 복구 상황에만 사용하세요.
                  정상 운영 중인 워크샵에 사용하면 구독 충돌이 발생할 수 있습니다.
                </span>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => handleOpenChange(false)}>
                취소
              </Button>
              <Button variant="destructive" onClick={() => setStep(2)}>
                계속
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <TriangleAlert className="h-5 w-5 text-destructive" />
                정말 강제 해제하시겠습니까?
              </DialogTitle>
              <DialogDescription className="space-y-2 pt-1">
                <span className="block font-medium text-foreground">
                  이 작업은 되돌릴 수 없습니다.
                </span>
                <span className="block">
                  워크샵 <strong className="text-foreground">{workshopId}</strong>의
                  모든 구독 할당이 즉시 해제됩니다. 해당 워크샵이 아직 실제로 운영 중이라면
                  참가자들이 구독에 접근하지 못하게 될 수 있습니다.
                </span>
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className="gap-2">
              <Button variant="outline" onClick={() => setStep(1)}>
                이전으로
              </Button>
              <Button
                variant="destructive"
                onClick={onConfirm}
                disabled={isPending}
              >
                {isPending ? "해제 중..." : "강제 해제"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

// ------------------------------------------------------------------
// SubscriptionPage
// ------------------------------------------------------------------

function SubscriptionPage() {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const [dialogWorkshopId, setDialogWorkshopId] = useState<string | null>(null)

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

  const forceReleaseMutation = useMutation({
    mutationFn: (workshopId: string) => subscriptionApi.forceRelease(workshopId),
    onSuccess: (result, workshopId) => {
      showSuccessToast(result.message ?? `워크샵 ${workshopId} 구독이 해제되었습니다`)
      setDialogWorkshopId(null)
      queryClient.invalidateQueries({ queryKey: ["subscriptions"] })
    },
    onError: () => {
      showErrorToast("구독 강제 해제에 실패했습니다")
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
                  {usedByWorkshop && isAdmin ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => setDialogWorkshopId(usedByWorkshop)}
                    >
                      <Unlock className="h-3.5 w-3.5 mr-1" />
                      강제 해제
                    </Button>
                  ) : !usedByWorkshop ? (
                    <span className="text-xs text-green-600 dark:text-green-400">사용 가능</span>
                  ) : null}
                </div>
              )
            })
          )}
        </CardContent>
      </Card>

      {dialogWorkshopId && (
        <ForceReleaseDialog
          workshopId={dialogWorkshopId}
          open={!!dialogWorkshopId}
          onOpenChange={(open) => { if (!open) setDialogWorkshopId(null) }}
          onConfirm={() => forceReleaseMutation.mutate(dialogWorkshopId)}
          isPending={forceReleaseMutation.isPending}
        />
      )}
    </div>
  )
}
