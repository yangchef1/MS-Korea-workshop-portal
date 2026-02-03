/**
 * MSAL Provider component for Azure AD Authentication
 */
import { MsalProvider as MsalReactProvider } from "@azure/msal-react"
import { ReactNode, useEffect, useState } from "react"
import { msalInstance } from "@/lib/msalConfig"
import { EventType, EventMessage, AuthenticationResult } from "@azure/msal-browser"

interface Props {
  children: ReactNode
}

export function MsalProvider({ children }: Props) {
  const [isInitialized, setIsInitialized] = useState(false)

  useEffect(() => {
    const initializeMsal = async () => {
      try {
        // Initialize MSAL
        await msalInstance.initialize()

        // Handle redirect promise (for redirect flow)
        const response = await msalInstance.handleRedirectPromise()
        if (response) {
          // Set active account after redirect
          msalInstance.setActiveAccount(response.account)
        }

        // Set active account if not already set
        const accounts = msalInstance.getAllAccounts()
        if (!msalInstance.getActiveAccount() && accounts.length > 0) {
          msalInstance.setActiveAccount(accounts[0])
        }

        // Listen for login events
        msalInstance.addEventCallback((event: EventMessage) => {
          if (event.eventType === EventType.LOGIN_SUCCESS && event.payload) {
            const payload = event.payload as AuthenticationResult
            msalInstance.setActiveAccount(payload.account)
          }
        })

        setIsInitialized(true)
      } catch (error) {
        console.error("MSAL initialization failed:", error)
        setIsInitialized(true) // Still render to show error state
      }
    }

    initializeMsal()
  }, [])

  if (!isInitialized) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-pulse text-gray-500">Loading...</div>
      </div>
    )
  }

  return (
    <MsalReactProvider instance={msalInstance}>
      {children}
    </MsalReactProvider>
  )
}

export default MsalProvider
