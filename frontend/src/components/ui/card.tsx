import * as React from "react"
import { cn } from "@/lib/utils"

export function Card({
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { children?: React.ReactNode }) {
  return (
    <div
      data-slot="card"
      className={cn("rounded-lg border border-hairline bg-card text-primary", className)}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ className, children, ...props }: React.ComponentProps<"div"> & { children?: React.ReactNode }) {
  return (
    <div data-slot="card-header" className={cn("grid flex-1 gap-1.5 px-5 py-4", className)} {...props}>
      {children}
    </div>
  )
}

export function CardTitle({
  className,
  children,
  ...props
}: React.ComponentProps<"h2"> & { children?: React.ReactNode }) {
  return (
    <h2
      data-slot="card-title"
      className={cn("text-sm font-medium text-primary", className)}
      {...props}
    >
      {children}
    </h2>
  )
}

export function CardContent({ className, children, ...props }: React.ComponentProps<"div"> & { children?: React.ReactNode }) {
  return (
    <div data-slot="card-content" className={cn("px-5 py-3", className)} {...props}>
      {children}
    </div>
  )
}

export function CardFooter({ className, children, ...props }: React.ComponentProps<"div"> & { children?: React.ReactNode }) {
  return (
    <div data-slot="card-footer" className={cn("flex items-center px-5 py-3 border-t border-hairline", className)} {...props}>
      {children}
    </div>
  )
}
