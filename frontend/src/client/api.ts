import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios"
import { msalInstance, loginRequest } from "@/lib/msalConfig"
import { InteractionRequiredAuthError, BrowserAuthError } from "@azure/msal-browser"

// API base URL - proxied through Vite in dev, full URL in production
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api"

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
export type UserStatus = "active" | "pending" | "invited"

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
  status: UserStatus
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

export interface SubscriptionInfo {
  subscription_id: string
  display_name?: string
}

export interface InvalidParticipant {
  alias: string
  subscription_id: string
}

export interface SubscriptionSettingsResponse {
  subscriptions: SubscriptionInfo[]
  in_use_map?: Record<string, string>
  from_cache?: boolean
}

/** Generic message-only response from the API. */
export interface MessageResponse {
  message: string
}

export interface Participant {
  alias?: string
  name?: string
  upn?: string
  resource_group?: string
  user_principal_name?: string
  subscription_id?: string
}

export interface PlannedParticipant {
  alias: string
  email: string
}

export interface Workshop {
  id: string
  name: string
  description?: string
  status: "active" | "cleaning_up" | "completed" | "creating" | "failed" | "deleted" | "scheduled"
  region?: string
  deployment_region?: string
  policy?: {
    allowed_regions: string[]
    denied_services: string[]
    allowed_vm_skus?: string[]
    vm_sku_preset?: string
  }
  allowed_regions?: string[]
  start_date: string
  end_date: string
  participants?: Participant[]
  planned_participants?: PlannedParticipant[]
  participant_count?: number
  planned_participant_count?: number
  created_at: string
  created_by?: string
  updated_at?: string
  survey_url?: string
  available_subscriptions?: SubscriptionInfo[]
  invalid_participants?: InvalidParticipant[]
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
  is_snapshot?: boolean
}

export interface CostBreakdown {
  subscription_id: string
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
  is_snapshot?: boolean
}

/** Infrastructure template type. */
export type TemplateType = "arm" | "bicep"

export interface InfraTemplate {
  name: string
  description: string
  path: string
  template_type: TemplateType
}

/** Detailed infrastructure template including raw content. */
export interface InfraTemplateDetail {
  name: string
  description: string
  path: string
  template_type: TemplateType
  template_content: string
}

/** Request body for updating a template. */
export interface UpdateTemplateRequest {
  description?: string
  template_type?: TemplateType
  template_content?: string
}

/** Request body for creating a new template. */
export interface CreateTemplateRequest {
  name: string
  description?: string
  template_type?: TemplateType
  template_content: string
}

export interface ResourceType {
  value: string
  label: string
  category: string
}

/** VM SKU 정보. */
export interface VmSku {
  name: string
  family: string
  vcpus: number
  memory_gb: number
}

/** VM SKU 프리셋: key → { label, description, skus }. */
export type VmSkuPresets = Record<string, {
  label: string
  description: string
  skus: string[]
}>

/** Deletion failure resource type. */
export type DeletionFailureResourceType = "resource_group" | "user"

/** A single deletion failure record. */
export interface DeletionFailure {
  id: string
  workshop_id: string
  workshop_name: string
  resource_type: DeletionFailureResourceType
  resource_name: string
  subscription_id?: string
  error_message: string
  failed_at: string
  status: "pending" | "resolved"
  retry_count: number
}

/** Response for listing deletion failures. */
export interface DeletionFailureListResponse {
  items: DeletionFailure[]
  total_count: number
}

export interface CreateWorkshopRequest {
  name: string
  start_date: string
  end_date: string
  base_resources_template: string
  allowed_regions: string  // comma-separated
  denied_services: string  // comma-separated
  allowed_vm_skus?: string  // comma-separated
  vm_sku_preset?: string
  deployment_region?: string
  participants_file: File
  /** One-time ARM/Bicep template file upload (.json / .bicep). */
  template_file?: File
  /** ARM parameters file (.parameters.json). */
  parameters_file?: File
  survey_url?: string
  description?: string
}

// API Error type — matches backend AppError.to_dict() format
export interface ApiError {
  error?: string
  message?: string
  detail?: string
  details?: Record<string, unknown>
}

/** Extract a human-readable message from an Axios error response. */
export const handleApiError = (error: AxiosError<ApiError>): ApiError => {
  const data = error.response?.data
  return {
    error: data?.error,
    message: data?.message || data?.detail || error.message || "An unexpected error occurred",
    details: data?.details,
  }
}

/** Error code to user-friendly Korean message mapping. */
const ERROR_CODE_MESSAGES: Record<string, string> = {
  INSUFFICIENT_SUBSCRIPTIONS: "사용 가능한 구독이 부족합니다.",
  INVALID_INPUT: "입력값이 올바르지 않습니다.",
  CSV_PARSING_ERROR: "참가자 CSV 파일 형식이 올바르지 않습니다.",
  UNSUPPORTED_FILE_TYPE: "지원하지 않는 파일 형식입니다.",
  INVALID_FORMAT: "입력 형식이 올바르지 않습니다.",
  PARTICIPANT_SETUP_FAILED: "일부 참가자 설정에 실패했습니다.",
  USER_CREATION_ERROR: "사용자 계정 생성에 실패했습니다.",
  ENTRA_ID_AUTHORIZATION_ERROR: "사용자 생성 권한이 없습니다.",
  POLICY_ASSIGNMENT_ERROR: "정책 할당에 실패했습니다.",
  AZURE_AUTH_ERROR: "Azure 인증에 실패했습니다.",
  SERVICE_UNAVAILABLE: "현재 서비스를 사용할 수 없습니다.",
  STORAGE_SERVICE_ERROR: "데이터 저장에 실패했습니다.",
  INTERNAL_ERROR: "예기치 않은 오류가 발생했습니다.",
}

/** Build a user-friendly Korean title from an error code. */
export const getErrorTitle = (code?: string): string => {
  if (code && ERROR_CODE_MESSAGES[code]) return ERROR_CODE_MESSAGES[code]
  return "워크샵 생성 중 오류가 발생했습니다."
}

/** Per-workshop cost info returned by the batch costs endpoint. */
export interface WorkshopCostSummary {
  estimated_cost: number
  currency: string
}

// Workshop API
export const workshopApi = {
  list: async (): Promise<Workshop[]> => {
    const response = await apiClient.get<Workshop[]>("/workshops")
    return response.data
  },

  /** Batch-fetch estimated costs for all workshops (lazy-load). */
  costs: async (): Promise<Record<string, WorkshopCostSummary>> => {
    const response = await apiClient.get<Record<string, WorkshopCostSummary>>("/workshops/costs")
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
    formData.append("denied_services", data.denied_services)
    formData.append("participants_file", data.participants_file)
    if (data.survey_url) {
      formData.append("survey_url", data.survey_url)
    }
    if (data.description) {
      formData.append("description", data.description)
    }
    if (data.allowed_vm_skus) {
      formData.append("allowed_vm_skus", data.allowed_vm_skus)
    }
    if (data.vm_sku_preset) {
      formData.append("vm_sku_preset", data.vm_sku_preset)
    }
    if (data.deployment_region) {
      formData.append("deployment_region", data.deployment_region)
    }
    if (data.template_file) {
      formData.append("template_file", data.template_file)
    }
    if (data.parameters_file) {
      formData.append("parameters_file", data.parameters_file)
    }

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

  getTemplates: async (): Promise<InfraTemplate[]> => {
    const response = await apiClient.get<InfraTemplate[]>("/templates")
    return response.data
  },

  getResourceTypes: async (): Promise<ResourceType[]> => {
    const response = await apiClient.get<ResourceType[]>("/workshops/resource-types")
    return response.data
  },

  /**
   * 지정된 모든 리전에서 공통으로 지원되는 VM SKU 교집합을 조회한다.
   *
   * 서버에서 교집합을 계산하여 24시간 캐시로 반환한다.
   *
   * @param regions - 교집합 대상 리전 목록.
   * @returns 모든 리전에서 지원되는 VM SKU 목록.
   */
  getCommonVmSkus: async (regions: string[]): Promise<VmSku[]> => {
    const response = await apiClient.get<VmSku[]>("/workshops/vm-skus/common", {
      params: { regions: regions.join(",") },
    })
    return response.data
  },

  /** VM SKU 프리셋 목록을 조회한다. */
  getVmSkuPresets: async (): Promise<VmSkuPresets> => {
    const response = await apiClient.get<VmSkuPresets>("/workshops/vm-sku-presets")
    return response.data
  },

  /** 워크샵의 만족도 조사 URL을 등록 또는 수정한다. */
  updateSurveyUrl: async (id: string, surveyUrl: string): Promise<void> => {
    await apiClient.patch(`/workshops/${id}/survey-url`, {
      survey_url: surveyUrl,
    })
  },

  /** 워크샵의 종료 시간을 연장한다. */
  extendEndDate: async (id: string, newEndDate: string): Promise<void> => {
    await apiClient.patch(`/workshops/${id}/end-date`, {
      new_end_date: newEndDate,
    })
  },

  // sendSurvey removed: personal emails are no longer stored (compliance).
  // Survey links should be shared via Teams, chat, etc.

  /** 워크샵의 삭제 실패 항목 목록을 조회한다. */
  getDeletionFailures: async (
    id: string
  ): Promise<DeletionFailureListResponse> => {
    const response = await apiClient.get<DeletionFailureListResponse>(
      `/workshops/${id}/deletion-failures`
    )
    return response.data
  },

  /** 삭제 실패 항목을 수동으로 재시도한다. */
  retryDeletion: async (
    workshopId: string,
    failureId: string
  ): Promise<{ message: string; detail?: string }> => {
    const response = await apiClient.post(
      `/workshops/${workshopId}/deletion-failures/${failureId}/retry`
    )
    return response.data
  },

  /** 워크샵의 모든 삭제 실패 항목을 일괄 재시도한다. */
  retryAllDeletions: async (
    workshopId: string
  ): Promise<{ message: string; detail?: string }> => {
    const response = await apiClient.post(
      `/workshops/${workshopId}/deletion-failures/retry-all`
    )
    return response.data
  },

  /** 참가자 구독을 수동 재배정한다. */
  reassignParticipantSubscription: async (
    workshopId: string,
    alias: string,
    subscriptionId: string
  ): Promise<void> => {
    await apiClient.patch(
      `/workshops/${workshopId}/participants/${alias}/subscription`,
      { subscription_id: subscriptionId }
    )
  },
}

export const subscriptionApi = {
  get: async (refresh = false): Promise<SubscriptionSettingsResponse> => {
    const response = await apiClient.get<SubscriptionSettingsResponse>(
      "/subscriptions",
      { params: { refresh } }
    )
    return response.data
  },

  /** 워크샵에 묶인 모든 구독을 강제 해제한다 (Admin 전용). */
  forceRelease: async (workshopId: string): Promise<MessageResponse> => {
    const response = await apiClient.post<MessageResponse>(
      `/subscriptions/force-release/${workshopId}`
    )
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

  /** 초대 이메일 발송 (Admin 전용). 사용자가 이미 등록되어 있어야 한다. */
  inviteUser: async (email: string): Promise<void> => {
    await apiClient.post("/auth/users/invite", { email })
  },
}

// Template API (Admin only)
export const templateApi = {
  /** 인프라 템플릿 목록을 조회한다. */
  list: async (): Promise<InfraTemplate[]> => {
    const response = await apiClient.get<InfraTemplate[]>("/templates")
    return response.data
  },

  /** 새 인프라 템플릿을 생성한다. */
  create: async (data: CreateTemplateRequest): Promise<InfraTemplate> => {
    const response = await apiClient.post<InfraTemplate>("/templates", data)
    return response.data
  },

  /** 인프라 템플릿 상세 정보를 조회한다. */
  get: async (name: string): Promise<InfraTemplateDetail> => {
    const response = await apiClient.get<InfraTemplateDetail>(
      `/templates/${encodeURIComponent(name)}`
    )
    return response.data
  },

  /** 인프라 템플릿을 수정한다. */
  update: async (
    name: string,
    data: UpdateTemplateRequest
  ): Promise<InfraTemplate> => {
    const response = await apiClient.patch<InfraTemplate>(
      `/templates/${encodeURIComponent(name)}`,
      data
    )
    return response.data
  },

  /** 인프라 템플릿을 삭제한다. */
  delete: async (name: string): Promise<void> => {
    await apiClient.delete(`/templates/${encodeURIComponent(name)}`)
  },
}
