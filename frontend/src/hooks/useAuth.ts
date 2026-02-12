/**
 * Authentication hook wrapper for MSAL.
 * Fetches user role from backend on authentication.
 */
import { useEffect, useMemo, useState } from "react"
import { useMsalAuth, type MsalUser } from "./useMsalAuth"
import { authApi, type UserRole } from "@/client/api"

export type User = MsalUser

export const useAuth = () => {
  const { user, isAuthenticated, isLoading, login, logout, getAccessToken } = useMsalAuth()
  const [role, setRole] = useState<UserRole | null>(null)
  const [roleLoading, setRoleLoading] = useState(false)

  useEffect(() => {
    if (!isAuthenticated || !user) {
      setRole(null)
      return
    }

    let cancelled = false
    setRoleLoading(true)

    authApi
      .me()
      .then((data) => {
        if (!cancelled) {
          setRole(data.role || "user")
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRole(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRoleLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [isAuthenticated, user?.user_id])

  const enrichedUser: MsalUser | null = useMemo(() => {
    if (!user) return null
    return { ...user, role }
  }, [user, role])

  return {
    user: enrichedUser,
    isLoading: isLoading || roleLoading,
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
