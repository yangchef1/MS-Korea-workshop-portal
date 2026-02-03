import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { Cloud, Loader2 } from "lucide-react"
import { useMsal } from "@azure/msal-react"
import { InteractionStatus } from "@azure/msal-browser"
import { loginRequest } from "@/lib/msalConfig"

export const Route = createFileRoute("/login")({
  component: Login,
})

function Login() {
  const { instance, inProgress, accounts } = useMsal()
  const navigate = useNavigate()
  const loginAttempted = useRef(false)

  useEffect(() => {
    // If already authenticated, redirect to home
    if (accounts.length > 0) {
      navigate({ to: "/" })
      return
    }

    // Only attempt login if no interaction is in progress and we haven't tried yet
    if (inProgress === InteractionStatus.None && !loginAttempted.current) {
      loginAttempted.current = true
      instance.loginRedirect(loginRequest).catch((error) => {
        console.error("Login redirect failed:", error)
        loginAttempted.current = false // Allow retry on error
      })
    }
  }, [instance, inProgress, accounts, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      <div className="flex flex-col items-center gap-6 p-8 text-center">
        <div className="flex items-center gap-3">
          <Cloud className="h-12 w-12 text-blue-600 dark:text-blue-400" />
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Azure Workshop Portal
          </h1>
        </div>
        <div className="flex items-center gap-3 text-gray-600 dark:text-gray-300">
          <Loader2 className="h-5 w-5 animate-spin" />
          <p>Microsoft 계정으로 로그인 중...</p>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          자동으로 Microsoft 로그인 페이지로 이동합니다.
        </p>
      </div>
    </div>
  )
}
