import React from "react"
import { cn } from "@/lib/utils"

export interface BubbleProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "inbound" | "outbound" | "default" | "primary"
}

export function Bubble({
  variant = "default",
  className,
  children,
  ...props
}: BubbleProps) {
  const variantStyles = {
    inbound: "bg-zinc-900 text-zinc-200 rounded-lg rounded-tl-sm self-start max-w-[80%] border border-zinc-800",
    outbound: "bg-amber-600 text-zinc-950 rounded-lg rounded-tr-sm self-end max-w-[80%]",
    default: "bg-zinc-900 text-zinc-200 rounded-lg self-start max-w-[80%] border border-zinc-800",
    primary: "bg-amber-600 text-zinc-950 rounded-lg self-end max-w-[80%]",
  }

  return (
    <div
      className={cn(
        "px-3 py-2 text-xs inline-block break-words",
        variantStyles[variant],
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function BubbleContent({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("leading-relaxed", className)} {...props}>
      {children}
    </div>
  )
}
