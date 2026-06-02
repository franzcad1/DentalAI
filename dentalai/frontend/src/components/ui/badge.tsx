import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-accent/20 text-accent border border-accent/30',
        secondary: 'bg-surface-raised text-slate-300 border border-surface-border',
        completed: 'bg-green-500/15 text-green-400',
        confirmed: 'bg-blue-500/15 text-blue-400',
        pending: 'bg-amber-500/15 text-amber-400',
        cancelled: 'bg-slate-500/15 text-slate-400',
        no_show: 'bg-red-500/15 text-red-400',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
