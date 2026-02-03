/**
 * Custom hook for MSAL authentication
 */
import { useMsal, useAccount, useIsAuthenticated } from "@azure/msal-react"
import { InteractionStatus } from "@azure/msal-browser"
import { useCallback, useMemo, useState, useEffect } from "react"
import { loginRequest, graphRequest } from "@/lib/msalConfig"

export interface MsalUser {
  user_id: string
  name: string
  email: string
  tenant_id: string
  photoUrl?: string
}

export function useMsalAuth() {
  const { instance, accounts, inProgress } = useMsal()
  const account = useAccount(accounts[0] || null)
  const isAuthenticated = useIsAuthenticated()
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)

  const isLoading = inProgress !== InteractionStatus.None

  // Fetch profile photo from Microsoft Graph
  useEffect(() => {
    const fetchPhoto = async () => {
      if (!account || !isAuthenticated) {
        setPhotoUrl(null)
        return
      }

      try {
        const response = await instance.acquireTokenSilent({
          ...graphRequest,
          account,
        })

        const photoResponse = await fetch(
          "https://graph.microsoft.com/v1.0/me/photo/$value",
          {
            headers: {
              Authorization: `Bearer ${response.accessToken}`,
            },
          }
        )

        if (photoResponse.ok) {
          const blob = await photoResponse.blob()
          const url = URL.createObjectURL(blob)
          setPhotoUrl(url)
        }
      } catch (error) {
        // Photo not available or error fetching - silently ignore
        console.debug("Could not fetch profile photo:", error)
      }
    }

    fetchPhoto()

    // Cleanup blob URL on unmount
    return () => {
      if (photoUrl) {
        URL.revokeObjectURL(photoUrl)
      }
    }
  }, [account, isAuthenticated, instance])

  const user: MsalUser | null = useMemo(() => {
    if (!account) return null
    return {
      user_id: account.localAccountId || account.homeAccountId,
      name: account.name || "",
      email: account.username || "",
      tenant_id: account.tenantId || "",
      photoUrl: photoUrl || undefined,
    }
  }, [account, photoUrl])

  const login = useCallback(async () => {
    try {
      // Use redirect for better UX (popup can be blocked)
      await instance.loginRedirect(loginRequest)
    } catch (error) {
      console.error("Login failed:", error)
      throw error
    }
  }, [instance])

  const logout = useCallback(async () => {
    try {
      await instance.logoutRedirect({
        postLogoutRedirectUri: window.location.origin,
      })
    } catch (error) {
      console.error("Logout failed:", error)
      throw error
    }
  }, [instance])

  const getAccessToken = useCallback(async (): Promise<string | null> => {
    if (!account) return null

    try {
      const response = await instance.acquireTokenSilent({
        ...loginRequest,
        account,
      })
      return response.accessToken
    } catch (error) {
      // If silent acquisition fails, try interactive
      console.warn("Silent token acquisition failed, trying interactive:", error)
      try {
        const response = await instance.acquireTokenRedirect(loginRequest)
        return response?.accessToken || null
      } catch (interactiveError) {
        console.error("Interactive token acquisition failed:", interactiveError)
        return null
      }
    }
  }, [instance, account])

  return {
    user,
    isAuthenticated,
    isLoading,
    login,
    logout,
    getAccessToken,
    account,
  }
}

export default useMsalAuth
