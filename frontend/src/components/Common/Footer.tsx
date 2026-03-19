export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="shrink-0 py-4 px-6">
      <div className="flex items-center justify-center">
        <p className="text-muted-foreground text-sm text-center">
          &copy; {currentYear} Microsoft Korea. All rights reserved.
        </p>
      </div>
    </footer>
  )
}
