export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="shrink-0 py-4 px-6">
      <div className="flex items-center justify-center">
        <p className="text-muted-foreground text-sm text-center">
          Microsoft Korea | Azure Workshop Portal - {currentYear}
        </p>
      </div>
    </footer>
  )
}
