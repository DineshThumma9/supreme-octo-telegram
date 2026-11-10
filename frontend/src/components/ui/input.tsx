import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      className={cn(
        "h-8 w-full min-w-0 rounded-md border border-transparent bg-raised/60 text-primary text-[11px] px-2.5 py-1 placeholder:text-muted transition-[color,box-shadow,background-color] focus-visible:border-accent/50 focus-visible:ring-3 focus-visible:ring-accent/30 disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
}

export { Input }
