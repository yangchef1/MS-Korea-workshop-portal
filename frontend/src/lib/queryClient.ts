import { QueryClient } from "@tanstack/react-query"

/** Shared query keys used across route guards and hooks. */
export const queryKeys = {
  authMe: ["auth", "me"] as const,
} as const

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})
