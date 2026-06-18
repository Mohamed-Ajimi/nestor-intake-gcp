import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
 ({ className, type, ...props }, ref) => {
 return (
 <input
 type={type}
        className={cn(
          "flex h-10 w-full border border-ink bg-paper2 px-3 py-2 text-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-ink/40 focus-visible:outline-none focus-visible:border-2 focus-visible:px-[calc(0.75rem-1px)] focus-visible:py-[calc(0.5rem-1px)] disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
 ref={ref}
 {...props}
 />
 );
 },
);
Input.displayName = "Input";

export { Input };
