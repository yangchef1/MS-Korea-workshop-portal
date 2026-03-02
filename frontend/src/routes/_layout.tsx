import { createFileRoute, Outlet, redirect } from "@tanstack/react-router"

import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
} from "@/components/ui/sidebar"
import { authApi } from "@/client"
import { queryClient, queryKeys } from "@/lib/queryClient"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    try {
      await queryClient.fetchQuery({
        queryKey: queryKeys.authMe,
        queryFn: () => authApi.me(),
      })
    } catch {
      // Redirect to login if not authenticated
      throw redirect({
        to: "/login",
      })
    }
  },
})

function Layout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="flex flex-col">
        <main className="flex-1 overflow-auto p-6 md:p-8">
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
        <div className="mx-6 md:mx-8 border-t border-border" />
        <Footer />
      </SidebarInset>
    </SidebarProvider>
  )
}

export default Layout
