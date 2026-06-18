import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
 "inline-flex items-center justify-center gap-2 whitespace-nowrap font-mono text-xs uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
 {
 variants: {
 variant: {
 default: "bg-ink text-paper border border-ink hover:bg-ink/90",
 destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
 outline: "border border-ink bg-paper text-ink hover:border-2",
 secondary: "border border-ink bg-paper text-ink hover:border-2",
 ghost: "text-ink hover:underline",
 link: "text-ink underline underline-offset-4",
 },
 size: {
 default: "h-10 px-6 py-3",
 sm: "h-8 px-3 text-[11px]",
 lg: "h-11 px-8",
 icon: "h-9 w-9",
 },
 },
 defaultVariants: {
 variant: "default",
 size: "default",
 },
 },
);

export interface ButtonProps
 extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
 asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
 ({ className, variant, size, asChild = false, ...props }, ref) => {
 const Comp = asChild ? Slot : "button";
 return (
 <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
 );
 },
);
Button.displayName = "Button";

export { Button, buttonVariants };
