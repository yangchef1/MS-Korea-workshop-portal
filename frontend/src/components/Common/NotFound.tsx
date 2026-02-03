import { Link } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"

const NotFound = () => {
  return (
    <div
      className="flex min-h-screen items-center justify-center flex-col p-4"
      data-testid="not-found"
    >
      <div className="flex items-center z-10">
        <div className="flex flex-col ml-4 items-center justify-center p-4">
          <span className="text-6xl md:text-8xl font-bold leading-none mb-4">
            404
          </span>
          <span className="text-2xl font-bold mb-2">페이지를 찾을 수 없습니다</span>
        </div>
      </div>

      <p className="text-lg text-muted-foreground mb-4 text-center z-10">
        요청하신 페이지가 존재하지 않습니다.
      </p>
      <div className="z-10">
        <Link to="/">
          <Button className="mt-4">홈으로 돌아가기</Button>
        </Link>
      </div>
    </div>
  )
}

export default NotFound
