import * as React from "react"
import { cn } from "@/lib/utils"

function Label({ className, children, ...props }: React.ComponentProps<"label"> & { children?: React.ReactNode }) {
  return (
    <label
      data-slot="label"
      className={cn("text-[10px] font-medium text-muted uppercase tracking-wider mb-1.5 block", className)}
      {...props}
    >
      {children}
    </label>
  )
}

export { Label }
