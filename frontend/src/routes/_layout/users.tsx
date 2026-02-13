import { createFileRoute } from "@tanstack/react-router"
import { useState, useEffect, useCallback } from "react"
import { UserPlus, Trash2, Shield, User, Mail, MoreVertical } from "lucide-react"

import { authApi, type PortalUser, type UserRole } from "@/client"
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

export const Route = createFileRoute("/_layout/users")({
  component: UserManagementPage,
})

/** Role badge color mapping. */
const ROLE_BADGE_STYLES: Record<UserRole, string> = {
  admin: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
  user: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
}

/** Role display labels. */
const ROLE_LABELS: Record<UserRole, string> = {
  admin: "관리자",
  user: "사용자",
}

/** Pending badge style. */
const PENDING_BADGE_STYLE =
  "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"

/** Invited badge style. */
const INVITED_BADGE_STYLE =
  "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300"

// ---------------------------------------------------------------------------
// Custom hook: useUsers
// ---------------------------------------------------------------------------

interface UseUsersResult {
  users: PortalUser[]
  isLoading: boolean
  refetch: () => void
}

/**
 * Fetches and manages the portal user list.
 *
 * @returns User list, loading state, and refetch function.
 */
function useUsers(): UseUsersResult {
  const [users, setUsers] = useState<PortalUser[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const fetchUsers = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await authApi.listUsers()
      setUsers(data)
    } catch {
      setUsers([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchUsers()
  }, [fetchUsers])

  return { users, isLoading, refetch: fetchUsers }
}

// ---------------------------------------------------------------------------
// Add‑user dialog (modal)
// ---------------------------------------------------------------------------

interface AddUserDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSubmit: (email: string, role: UserRole, name: string, sendInvite: boolean) => void
}

/** Modal dialog for adding a new portal user. */
function AddUserDialog({ open, onOpenChange, onSubmit }: AddUserDialogProps) {
  const [email, setEmail] = useState("")
  const [name, setName] = useState("")
  const [role, setRole] = useState<UserRole>("user")
  const [sendInvite, setSendInvite] = useState(true)

  const resetForm = () => {
    setEmail("")
    setName("")
    setRole("user")
    setSendInvite(true)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(email.trim(), role, name.trim(), sendInvite)
    resetForm()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>새 사용자 추가</DialogTitle>
          <DialogDescription>포털에 새 사용자를 추가합니다.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="add-email">이메일</Label>
              <Input
                id="add-email"
                type="email"
                placeholder="user@example.com"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-name">이름</Label>
              <Input
                id="add-name"
                placeholder="홍길동"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="add-role">역할</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    id="add-role"
                    variant="outline"
                    className="w-full justify-start"
                  >
                    {ROLE_LABELS[role]}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onClick={() => setRole("user")}>
                    <User className="mr-2 h-4 w-4" />
                    사용자
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setRole("admin")}>
                    <Shield className="mr-2 h-4 w-4" />
                    관리자
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="send-invite"
              type="checkbox"
              checked={sendInvite}
              onChange={(e) => setSendInvite(e.target.checked)}
              className="h-4 w-4 rounded border-input accent-primary"
            />
            <Label htmlFor="send-invite" className="text-sm font-normal cursor-pointer">
              초대 메일 발송
            </Label>
          </div>
          <DialogFooter>
            <Button type="submit">사용자 추가</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// User table row
// ---------------------------------------------------------------------------

interface UserRowProps {
  portalUser: PortalUser
  currentEmail: string | undefined
  onRoleChange: (email: string, newRole: UserRole) => void
  onDelete: (email: string) => void
  onResendInvite: (email: string) => void
}

/** Single row in the user table. */
function UserRow({ portalUser, currentEmail, onRoleChange, onDelete, onResendInvite }: UserRowProps) {
  const isSelf = portalUser.email === currentEmail
  const nextRole: UserRole = portalUser.role === "admin" ? "user" : "admin"
  const [showRoleDialog, setShowRoleDialog] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const isInvited = portalUser.status === "invited"
  const isPending = portalUser.status === "pending"

  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/50 transition-colors">
      <td className="px-4 py-3 text-sm">
        <span className="flex items-center gap-2">
          {portalUser.name || "-"}
          {portalUser.status === "pending" && (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${PENDING_BADGE_STYLE}`}
            >
              대기 중
            </span>
          )}
          {portalUser.status === "invited" && (
            <span
              className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${INVITED_BADGE_STYLE}`}
            >
              초대됨
            </span>
          )}
        </span>
      </td>
      <td className="px-4 py-3 text-sm">{portalUser.email}</td>
      <td className="px-4 py-3 text-sm">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${ROLE_BADGE_STYLES[portalUser.role]}`}
        >
          {ROLE_LABELS[portalUser.role]}
        </span>
      </td>
      <td className="px-4 py-3 text-sm text-muted-foreground">
        {new Date(portalUser.registered_at).toLocaleDateString("ko-KR", {
          year: "numeric",
          month: "short",
          day: "numeric",
        })}
      </td>
      <td className="px-4 py-3 text-sm">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              disabled={isSelf}
              title={isSelf ? "자기 자신은 수정할 수 없습니다" : "작업 선택"}
            >
              <MoreVertical className="h-4 w-4" />
              <span className="sr-only">작업 메뉴 열기</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {(isInvited || isPending) && (
              <>
                <DropdownMenuItem onClick={() => onResendInvite(portalUser.email)}>
                  <Mail className="mr-2 h-4 w-4" />
                  {isPending ? "초대 메일 발송" : "초대 메일 재발송"}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuItem onClick={() => setShowRoleDialog(true)}>
              {nextRole === "admin" ? (
                <Shield className="mr-2 h-4 w-4" />
              ) : (
                <User className="mr-2 h-4 w-4" />
              )}
              {ROLE_LABELS[nextRole]}(으)로 변경
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={() => setShowDeleteDialog(true)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              삭제
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <AlertDialog open={showRoleDialog} onOpenChange={setShowRoleDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>권한 변경</AlertDialogTitle>
              <AlertDialogDescription>
                <strong>{portalUser.name || portalUser.email}</strong>의 역할을{" "}
                <strong>{ROLE_LABELS[portalUser.role]}</strong>에서{" "}
                <strong>{ROLE_LABELS[nextRole]}</strong>(으)로 변경하시겠습니까?
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>취소</AlertDialogCancel>
              <AlertDialogAction onClick={() => {
                onRoleChange(portalUser.email, nextRole)
                setShowRoleDialog(false)
              }}>
                변경
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>사용자 삭제</AlertDialogTitle>
              <AlertDialogDescription>
                <strong>{portalUser.name || portalUser.email}</strong> 사용자를
                정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>취소</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={() => {
                  onDelete(portalUser.email)
                  setShowDeleteDialog(false)
                }}
              >
                삭제
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

/** Admin-only user management page. */
function UserManagementPage() {
  const { user, isLoading: authLoading } = useAuth()
  const { users, isLoading, refetch } = useUsers()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [showAddDialog, setShowAddDialog] = useState(false)

  const isAdmin = user?.role === "admin"

  // Guard: show loading while auth/role is being resolved
  if (authLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mb-4" />
        <p className="text-muted-foreground">권한을 확인하는 중입니다…</p>
      </div>
    )
  }

  // Guard: non-admin users see an unauthorized message
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

  const handleAddUser = async (
    email: string,
    role: UserRole,
    name: string,
    sendInvite: boolean,
  ) => {
    try {
      await authApi.addUser(email, role, name)
      if (sendInvite) {
        await authApi.inviteUser(email)
        showSuccessToast(`${email} 사용자가 추가되고 초대 메일이 발송되었습니다.`)
      } else {
        showSuccessToast(`${email} 사용자가 추가되었습니다.`)
      }
      setShowAddDialog(false)
      refetch()
    } catch {
      showErrorToast("사용자 추가에 실패했습니다.")
    }
  }

  const handleResendInvite = async (email: string) => {
    try {
      await authApi.inviteUser(email)
      showSuccessToast(`${email}으로 초대 메일이 재발송되었습니다.`)
    } catch {
      showErrorToast("초대 메일 발송에 실패했습니다.")
    }
  }

  const handleRoleChange = async (email: string, newRole: UserRole) => {
    try {
      await authApi.updateUserRole(email, newRole)
      showSuccessToast(`${email}의 역할이 ${ROLE_LABELS[newRole]}(으)로 변경되었습니다.`)
      refetch()
    } catch {
      showErrorToast("역할 변경에 실패했습니다.")
    }
  }

  const handleDeleteUser = async (email: string) => {
    try {
      await authApi.removeUser(email)
      showSuccessToast(`${email} 사용자가 삭제되었습니다.`)
      refetch()
    } catch {
      showErrorToast("사용자 삭제에 실패했습니다.")
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">유저 관리</h1>
        <p className="text-muted-foreground">
          포털 사용자를 관리합니다.
        </p>
      </div>

      <AddUserDialog
        open={showAddDialog}
        onOpenChange={setShowAddDialog}
        onSubmit={handleAddUser}
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>사용자 목록</CardTitle>
            <CardDescription>
              총 {users.length}명의 사용자가 등록되어 있습니다.
            </CardDescription>
          </div>
          <Button onClick={() => setShowAddDialog(true)}>
            <UserPlus className="h-4 w-4 mr-2" />
            사용자 추가
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 bg-muted rounded animate-pulse" />
              ))}
            </div>
          ) : users.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">
              등록된 사용자가 없습니다.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b text-left text-sm font-medium text-muted-foreground">
                    <th className="px-4 py-3">이름</th>
                    <th className="px-4 py-3">이메일</th>
                    <th className="px-4 py-3">역할</th>
                    <th className="px-4 py-3">등록일</th>
                    <th className="px-4 py-3 w-12"><span className="sr-only">작업</span></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((portalUser) => (
                    <UserRow
                      key={portalUser.email}
                      portalUser={portalUser}
                      currentEmail={user?.email}
                      onRoleChange={handleRoleChange}
                      onDelete={handleDeleteUser}
                      onResendInvite={handleResendInvite}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
