import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { msalInstance, loginRequest } from "@/lib/msalConfig"
import { InteractionRequiredAuthError, BrowserAuthError } from "@azure/msal-browser"

// API base URL - proxied through Vite in development
const API_BASE_URL = "/api"

// Constants for auth failure tracking (persisted in localStorage)
const AUTH_FAILURE_KEY = "auth_failure_count"
const AUTH_FAILURE_TIME_KEY = "auth_failure_time"
const MAX_AUTH_FAILURES = 3
const AUTH_FAILURE_WINDOW_MS = 10000 // 10 seconds

// Flag to prevent multiple redirect attempts within same page session
let isRedirecting = false

// Token refresh state to prevent concurrent token refresh attempts
let tokenRefreshPromise: Promise<string | null> | null = null

// Track auth failures to prevent infinite redirect loops
const trackAuthFailure = (): boolean => {
  const now = Date.now()
  const lastFailureTime = parseInt(localStorage.getItem(AUTH_FAILURE_TIME_KEY) || "0", 10)
  let failureCount = parseInt(localStorage.getItem(AUTH_FAILURE_KEY) || "0", 10)
  
  // Reset counter if outside the time window
  if (now - lastFailureTime > AUTH_FAILURE_WINDOW_MS) {
    failureCount = 0
  }
  
  failureCount++
  localStorage.setItem(AUTH_FAILURE_KEY, failureCount.toString())
  localStorage.setItem(AUTH_FAILURE_TIME_KEY, now.toString())
  
  // Return true if we should stop retrying
  return failureCount >= MAX_AUTH_FAILURES
}

// Clear auth failure tracking (call on successful auth)
const clearAuthFailureTracking = () => {
  localStorage.removeItem(AUTH_FAILURE_KEY)
  localStorage.removeItem(AUTH_FAILURE_TIME_KEY)
}

// Full logout - clear all MSAL state
const fullLogout = async () => {
  console.warn("Performing full logout and clearing all auth state...")
  
  // Clear all MSAL accounts from cache
  const accounts = msalInstance.getAllAccounts()
  for (const account of accounts) {
    try {
      await msalInstance.logoutRedirect({
        account,
        postLogoutRedirectUri: `${window.location.origin}/login`,
      })
    } catch {
      // If logout redirect fails, manually clear
      msalInstance.setActiveAccount(null)
    }
  }
  
  // Clear any MSAL-related localStorage items
  const keysToRemove = Object.keys(localStorage).filter(
    key => key.includes("msal") || key.includes("login")
  )
  keysToRemove.forEach(key => localStorage.removeItem(key))
}

// Helper function to redirect to login
const redirectToLogin = async (forceFullLogout = false) => {
  if (isRedirecting) return
  isRedirecting = true
  
  const shouldStop = trackAuthFailure()
  
  if (shouldStop || forceFullLogout) {
    console.warn("Too many auth failures or forced logout, clearing all auth state...")
    // Clear all MSAL state and redirect
    clearAuthFailureTracking()
    await fullLogout()
    return
  }
  
  console.warn("Redirecting to login page...")
  
  // Clear active account but keep MSAL cache for potential token refresh
  msalInstance.setActiveAccount(null)
  
  // Redirect to login page
  window.location.href = "/login"
}

// Function to acquire token with deduplication and force refresh on retry
const acquireToken = async (forceRefresh = false): Promise<string | null> => {
  const account = msalInstance.getActiveAccount()
  if (!account) return null

  // If a token refresh is already in progress, wait for it
  if (tokenRefreshPromise && !forceRefresh) {
    return tokenRefreshPromise
  }

  tokenRefreshPromise = (async () => {
    try {
      const response = await msalInstance.acquireTokenSilent({
        ...loginRequest,
        account,
        forceRefresh, // Force refresh if token was rejected by backend
      })
      
      // Token acquired successfully, clear failure tracking
      clearAuthFailureTracking()
      
      return response.idToken
    } catch (error) {
      console.warn("Failed to acquire token silently:", error)
      
      // If interaction is required (token expired, etc.), redirect to login
      if (error instanceof InteractionRequiredAuthError) {
        console.warn("Interaction required, performing full logout...")
        await redirectToLogin(true) // Force full logout
      }
      // iframe-based silent renewal timed out (e.g. third-party cookies blocked)
      if (error instanceof BrowserAuthError) {
        console.warn("Browser auth error (likely iframe timeout), falling back to interactive login...")
        await redirectToLogin(true)
      }
      return null
    } finally {
      // Clear the promise after completion
      tokenRefreshPromise = null
    }
  })()

  return tokenRefreshPromise
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
})

// Request interceptor to add Bearer token
apiClient.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    // If already redirecting, reject immediately to prevent request flood
    if (isRedirecting) {
      return Promise.reject(new Error("Authentication required - redirecting to login"))
    }

    const token = await acquireToken()
    
    if (token) {
      // Use idToken for authentication (audience = our client ID)
      // accessToken's audience is Microsoft Graph, not suitable for our backend
      config.headers.Authorization = `Bearer ${token}`
    } else if (msalInstance.getActiveAccount()) {
      // Had account but couldn't get token - authentication issue
      return Promise.reject(new Error("Authentication required"))
    }
    
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor to handle 401 Unauthorized errors
apiClient.interceptors.response.use(
  (response) => {
    // Successful response, clear any auth failure tracking
    clearAuthFailureTracking()
    return response
  },
  async (error: AxiosError) => {
    // Only handle 401 if not already redirecting
    if (error.response?.status === 401 && !isRedirecting) {
      console.warn("Received 401 Unauthorized, attempting token refresh...")
      
      // Try to refresh the token and retry the request once
      const originalRequest = error.config
      if (originalRequest && !originalRequest.headers?.["X-Retry-After-401"]) {
        try {
          const newToken = await acquireToken(true) // Force refresh
          if (newToken && originalRequest) {
            originalRequest.headers = originalRequest.headers || {}
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            originalRequest.headers["X-Retry-After-401"] = "true"
            return apiClient.request(originalRequest)
          }
        } catch {
          // Token refresh failed, redirect to login
        }
      }
      
      // If retry failed or already retried, redirect to login
      await redirectToLogin(true) // Force full logout on 401
    }
    return Promise.reject(error)
  }
)

// Types for API responses
export type UserRole = "admin" | "user"

export interface User {
  user_id: string
  name: string
  email: string
  tenant_id: string
  role: UserRole
}

export interface PortalUser {
  user_id: string
  name: string
  email: string
  role: UserRole
  registered_at: string
}

export interface UpdateRoleRequest {
  email: string
  role: UserRole
}

export interface AddUserRequest {
  email: string
  role?: UserRole
  name?: string
}

export interface Workshop {
  id: string
  name: string
  description?: string
  status: "active" | "completed" | "draft"
  region?: string
  start_date: string
  end_date: string
  participants?: Participant[]
  participant_count?: number
  created_at: string
  updated_at?: string
}

export interface Participant {
  name: string
  email: string
  resource_group: string
  user_principal_name?: string
}

export interface AzureResource {
  id: string
  name: string
  type: string
  location: string
  tags: Record<string, string>
  participant: string
  resource_group: string
}

export interface WorkshopResources {
  workshop_id: string
  total_count: number
  resources: AzureResource[]
}

export interface CostBreakdown {
  resource_group: string
  cost: number
  error?: string
}

export interface WorkshopCost {
  total_cost: number
  currency: string
  period_days: number
  start_date?: string
  end_date?: string
  breakdown?: CostBreakdown[]
}

export interface ArmTemplate {
  name: string
  description: string
  path: string
}

/** Detailed ARM template including raw JSON content. */
export interface ArmTemplateDetail {
  name: string
  description: string
  path: string
  template_content: string
}

/** Request body for updating an ARM template. */
export interface UpdateTemplateRequest {
  description?: string
  template_content?: string
}

export interface ResourceType {
  value: string
  label: string
  category: string
}

export interface CreateWorkshopRequest {
  name: string
  start_date: string
  end_date: string
  base_resources_template: string
  allowed_regions: string  // comma-separated
  allowed_services: string  // comma-separated
  participants_file: File
}

// API Error type
export interface ApiError {
  detail: string
  status?: number
}

// Error handler
export const handleApiError = (error: AxiosError<ApiError>): string => {
  if (error.response?.data?.detail) {
    return error.response.data.detail
  }
  return error.message || "An unexpected error occurred"
}

// Workshop API
export const workshopApi = {
  list: async (): Promise<Workshop[]> => {
    const response = await apiClient.get<Workshop[]>("/workshops")
    return response.data
  },

  get: async (id: string): Promise<Workshop> => {
    const response = await apiClient.get<Workshop>(`/workshops/${id}`)
    return response.data
  },

  create: async (data: CreateWorkshopRequest): Promise<Workshop> => {
    const formData = new FormData()
    formData.append("name", data.name)
    formData.append("start_date", data.start_date)
    formData.append("end_date", data.end_date)
    formData.append("base_resources_template", data.base_resources_template)
    formData.append("allowed_regions", data.allowed_regions)
    formData.append("allowed_services", data.allowed_services)
    formData.append("participants_file", data.participants_file)

    const response = await apiClient.post<Workshop>("/workshops", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    })
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/workshops/${id}`)
  },

  downloadPasswords: async (id: string): Promise<void> => {
    const response = await apiClient.get(`/workshops/${id}/passwords`, {
      responseType: 'blob'
    })
    const blob = new Blob([response.data], { type: 'text/csv' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `workshop-${id}-passwords.csv`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  },

  getResources: async (id: string): Promise<WorkshopResources> => {
    const response = await apiClient.get<WorkshopResources>(`/workshops/${id}/resources`)
    return response.data
  },

  getCost: async (id: string): Promise<WorkshopCost> => {
    const response = await apiClient.get<WorkshopCost>(`/workshops/${id}/cost`)
    return response.data
  },

  getTemplates: async (): Promise<ArmTemplate[]> => {
    const response = await apiClient.get<ArmTemplate[]>("/templates")
    return response.data
  },

  getResourceTypes: async (): Promise<ResourceType[]> => {
    const response = await apiClient.get<ResourceType[]>("/workshops/resource-types")
    return response.data
  },
}

// Auth API - Note: Most auth is now handled by MSAL on frontend
// These endpoints are kept for backward compatibility or server-side user info
export const authApi = {
  me: async (): Promise<User> => {
    const response = await apiClient.get<User>("/auth/me")
    return response.data
  },

  /** 포털 사용자 목록 조회 (Admin 전용). */
  listUsers: async (): Promise<PortalUser[]> => {
    const response = await apiClient.get<PortalUser[]>("/auth/users")
    return response.data
  },

  /** 사용자 역할 변경 (Admin 전용). */
  updateUserRole: async (
    email: string,
    role: UserRole
  ): Promise<PortalUser> => {
    const response = await apiClient.patch<PortalUser>(
      "/auth/users/role",
      { email, role }
    )
    return response.data
  },

  /** 포털 사용자 추가 (Admin 전용). */
  addUser: async (
    email: string,
    role: UserRole = "user",
    name: string = ""
  ): Promise<PortalUser> => {
    const response = await apiClient.post<PortalUser>("/auth/users", {
      email,
      role,
      name,
    })
    return response.data
  },

  /** 포털 사용자 제거 (Admin 전용). */
  removeUser: async (email: string): Promise<void> => {
    await apiClient.delete("/auth/users", { params: { email } })
  },
}

// Template API (Admin only)
export const templateApi = {
  /** ARM 템플릿 목록을 조회한다. */
  list: async (): Promise<ArmTemplate[]> => {
    const response = await apiClient.get<ArmTemplate[]>("/templates")
    return response.data
  },

  /** ARM 템플릿 상세 정보를 조회한다. */
  get: async (name: string): Promise<ArmTemplateDetail> => {
    const response = await apiClient.get<ArmTemplateDetail>(
      `/templates/${encodeURIComponent(name)}`
    )
    return response.data
  },

  /** ARM 템플릿을 수정한다. */
  update: async (
    name: string,
    data: UpdateTemplateRequest
  ): Promise<ArmTemplate> => {
    const response = await apiClient.patch<ArmTemplate>(
      `/templates/${encodeURIComponent(name)}`,
      data
    )
    return response.data
  },

  /** ARM 템플릿을 삭제한다. */
  delete: async (name: string): Promise<void> => {
    await apiClient.delete(`/templates/${encodeURIComponent(name)}`)
  },
}
