import { createFileRoute } from "@tanstack/react-router"
import { useSuspenseQuery } from "@tanstack/react-query"
import { Suspense } from "react"
import { Link } from "@tanstack/react-router"
import { Plus, Calendar, Users, MapPin } from "lucide-react"

import { workshopApi, type Workshop } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

function getWorkshopsQueryOptions() {
  return {
    queryFn: () => workshopApi.list(),
    queryKey: ["workshops"],
  }
}

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
})

function WorkshopCard({ workshop }: { workshop: Workshop }) {
  const statusColors = {
    active: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
    completed: "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300",
    draft: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
  }

  return (
    <Link to="/workshops/$workshopId" params={{ workshopId: workshop.id }}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">{workshop.name}</CardTitle>
            <span
              className={`px-2 py-1 rounded-full text-xs font-medium ${statusColors[workshop.status]}`}
            >
              {workshop.status}
            </span>
          </div>
          <CardDescription>{workshop.description}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
            <div className="flex items-center gap-1">
              <MapPin className="h-4 w-4" />
              {workshop.region}
            </div>
            <div className="flex items-center gap-1">
              <Users className="h-4 w-4" />
              {workshop.participant_count ?? workshop.participants?.length ?? 0} 참가자
            </div>
            <div className="flex items-center gap-1">
              <Calendar className="h-4 w-4" />
              {new Date(workshop.start_date).toLocaleDateString()}
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function WorkshopsListContent() {
  const { data: workshops } = useSuspenseQuery(getWorkshopsQueryOptions())

  if (!workshops || workshops.length === 0) {
    return (
      <Card className="p-12">
        <div className="flex flex-col items-center justify-center text-center">
          <div className="rounded-full bg-muted p-4 mb-4">
            <Calendar className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="text-lg font-semibold">워크샵이 없습니다</h3>
          <p className="text-muted-foreground mb-4">
            새 워크샵을 만들어 시작하세요
          </p>
          <Link to="/workshops/create">
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              워크샵 만들기
            </Button>
          </Link>
        </div>
      </Card>
    )
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {workshops.map((workshop) => (
        <WorkshopCard key={workshop.id} workshop={workshop} />
      ))}
    </div>
  )
}

function WorkshopsList() {
  return (
    <Suspense
      fallback={
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-6 bg-muted rounded w-3/4"></div>
                <div className="h-4 bg-muted rounded w-1/2 mt-2"></div>
              </CardHeader>
              <CardContent>
                <div className="h-4 bg-muted rounded w-full"></div>
              </CardContent>
            </Card>
          ))}
        </div>
      }
    >
      <WorkshopsListContent />
    </Suspense>
  )
}

function Dashboard() {
  const { user } = useAuth()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            안녕하세요, {user?.name || user?.email} 👋
          </h1>
          <p className="text-muted-foreground">
            Azure Workshop Portal에 오신 것을 환영합니다
          </p>
        </div>
        <Link to="/workshops/create">
          <Button>
            <Plus className="h-4 w-4 mr-2" />
            새 워크샵
          </Button>
        </Link>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">워크샵 목록</h2>
        <WorkshopsList />
      </div>
    </div>
  )
}
