/**
 * Authentication hook wrapper for MSAL
 * Re-exports useMsalAuth for backward compatibility
 */
import { useMsalAuth, type MsalUser } from "./useMsalAuth"

export type User = MsalUser

export const useAuth = () => {
  const { user, isAuthenticated, isLoading, login, logout, getAccessToken } = useMsalAuth()

  return {
    user,
    isLoading,
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
