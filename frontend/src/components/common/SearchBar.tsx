import React from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/utils/cn';

interface SearchBarProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}

export function SearchBar({ value, onChange, placeholder = 'Search...', className }: SearchBarProps) {
  return (
    <div className={cn('relative', className)}>
      <Search
        size={14}
        className="absolute left-3 top-1/2 -translate-y-1/2 text-[#6b7280] pointer-events-none"
      />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full rounded-lg border border-[#252637] bg-[#1a1b28] pl-9 pr-4 py-2.5 text-sm text-[#f1f5f9] placeholder:text-[#4b5563] transition-colors focus:border-[#6366f1] focus:ring-1 focus:ring-[#6366f1] focus:outline-none"
      />
    </div>
  );
}
