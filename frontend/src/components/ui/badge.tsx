import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 border border-ink px-3 py-1 font-mono text-xs uppercase tracking-wider transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "bg-ink text-paper",
        secondary: "bg-paper text-ink",
        destructive: "bg-destructive text-destructive-foreground border-destructive",
        outline: "bg-paper text-ink",
        dashed: "bg-paper text-ink border-dashed",
        highlight: "bg-agenic-yellow text-ink",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
 extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
 return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
