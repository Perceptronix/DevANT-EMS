import React from 'react'
import { cn } from '@/lib/utils'

export type StatusColor = 'green' | 'yellow' | 'red' | 'blue' | 'gray'

export interface StatusDotProps extends React.HTMLAttributes<HTMLDivElement> {
  status: StatusColor
  animate?: boolean
}

export function StatusDot({ status, animate = false, className, ...props }: StatusDotProps) {
  const statusClasses = {
    green: 'bg-[#40b883]', // using literal hex values to ensure matte rendering across modes
    yellow: 'bg-[#d8a848]',
    red: 'bg-[#b85038]',
    blue: 'bg-[#4868b8]',
    gray: 'bg-[#666666]',
  }

  return (
    <div
      className={cn(
        'h-2.5 w-2.5 rounded-full flex-shrink-0',
        statusClasses[status],
        animate && 'animate-pulse',
        className
      )}
      {...props}
    />
  )
}
