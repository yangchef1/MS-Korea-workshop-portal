/**
 * Authentication hook wrapper for MSAL.
 *
 * Reads the user role from the React Query cache populated by
 * the _layout route guard's `beforeLoad`, avoiding a duplicate
 * `GET /api/auth/me` request.
 */
import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { useMsalAuth, type MsalUser } from "./useMsalAuth"
import { authApi } from "@/client/api"
import { queryKeys } from "@/lib/queryClient"

export type User = MsalUser

export const useAuth = () => {
  const { user, isAuthenticated, isLoading, login, logout, getAccessToken } = useMsalAuth()

  const { data: meData, isLoading: meLoading } = useQuery({
    queryKey: queryKeys.authMe,
    queryFn: () => authApi.me(),
    enabled: isAuthenticated && !!user,
  })

  const enrichedUser: MsalUser | null = useMemo(() => {
    if (!user) return null
    return { ...user, role: meData?.role ?? null }
  }, [user, meData?.role])

  return {
    user: enrichedUser,
    isLoading: isLoading || meLoading,
    error: null,
    isAuthenticated,
    logout,
    login,
    getAccessToken,
  }
}

export const isLoggedIn = (): boolean => {
  // For PKCE auth, check localStorage for MSAL account
  const keys = Object.keys(localStorage)
  return keys.some(key => key.includes("msal") && key.includes("account"))
}

export default useAuth
