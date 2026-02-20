import { PublicClientApplication, type Configuration } from "@azure/msal-browser"

const clientId = import.meta.env.VITE_AZURE_CLIENT_ID
const tenantId = import.meta.env.VITE_AZURE_TENANT_ID
const redirectUri = import.meta.env.VITE_AZURE_REDIRECT_URI || "http://localhost:5173"

if (!clientId) {
  throw new Error("VITE_AZURE_CLIENT_ID is not configured in environment variables")
}

if (!tenantId) {
  throw new Error("VITE_AZURE_TENANT_ID is not configured in environment variables")
}

const msalConfig: Configuration = {
  auth: {
    clientId,
    authority: `https://login.microsoftonline.com/${tenantId}`,
    redirectUri,
    postLogoutRedirectUri: redirectUri,
    navigateToLoginRequestUrl: true,
  },
  cache: {
    cacheLocation: "localStorage",
    storeAuthStateInCookie: true,
  },
}

/**
 * MSAL PublicClientApplication instance
 * Used across the app for authentication operations
 */
export const msalInstance = new PublicClientApplication(msalConfig)

/**
 * Scopes for login request
 * ID token (aud = clientId) is used for backend API authentication
 */
export const loginRequest = {
  scopes: ["openid", "profile", "email"],
}

/**
 * Scopes for Microsoft Graph API (profile photo, etc.)
 */
export const graphRequest = {
  scopes: ["User.Read"],
}
