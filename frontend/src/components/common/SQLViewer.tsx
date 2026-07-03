import { cn } from '@/utils/cn';

interface SQLViewerProps {
  title?: string;
  code: string;
  errorLine?: number;
}

export function SQLViewer({ title = "TRANSFORMATION SQL", code, errorLine }: SQLViewerProps) {
  const lines = code.split('\n');

  return (
    <div className="flex flex-col h-full rounded-xl border border-[#252637] bg-[#0d0e14] overflow-hidden">
      {title && (
        <div className="flex items-center px-4 py-3 border-b border-[#252637] bg-[#1a1b28]/50">
          <h4 className="text-[10px] font-bold uppercase tracking-widest text-[#6b7280]">
            {title}
          </h4>
        </div>
      )}
      <div className="flex-1 overflow-auto p-4 font-mono text-[11px] leading-relaxed scrollbar-thin">
        {lines.map((line, i) => {
          const lineNum = i + 1;
          const isError = errorLine === lineNum;
          return (
            <div
              key={i}
              className={cn(
                "flex gap-4 px-2 py-0.5 whitespace-pre transition-colors",
                isError ? "bg-[#ef4444]/10" : "hover:bg-[#1a1b28]"
              )}
            >
              <span className={cn(
                "w-4 text-right inline-block select-none flex-shrink-0",
                isError ? "text-[#ef4444] font-bold" : "text-[#4b5563]"
              )}>
                {lineNum}
              </span>
              <span className={cn(
                "flex-1",
                isError ? "text-[#ef4444]" : "text-[#94a3b8]"
              )}>
                {line}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
