import { useEffect, useRef } from 'react';
import { cn } from '@/utils/cn';

interface LogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'PASS' | 'WARN' | 'FAIL' | 'RUN';
  message: string;
}

interface LogConsoleProps {
  logs: LogEntry[];
}

export function LogConsole({ logs }: LogConsoleProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  function getLevelColor(level: string) {
    switch (level) {
      case 'INFO': return 'text-[#94a3b8]';
      case 'PASS': return 'text-[#22c55e]';
      case 'WARN': return 'text-[#f59e0b]';
      case 'FAIL': return 'text-[#ef4444]';
      case 'RUN': return 'text-[#6366f1]';
      default: return 'text-[#94a3b8]';
    }
  }

  return (
    <div className="flex flex-col h-full rounded-xl border border-[#252637] bg-[#0d0e14]">
      <div className="flex items-center px-4 py-2 border-b border-[#252637]">
        <h4 className="text-[10px] font-bold uppercase tracking-widest text-[#6b7280]">
          Live Execution Logs
        </h4>
      </div>
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 font-mono text-[11px] leading-relaxed scrollbar-thin"
      >
        {logs.map((log) => (
          <div key={log.id} className="flex gap-4 hover:bg-[#1a1b28] px-1 py-0.5 rounded transition-colors">
            <span className="text-[#6b7280] w-14 flex-shrink-0">{log.timestamp}</span>
            <span className={cn('w-10 font-bold flex-shrink-0', getLevelColor(log.level))}>
              {log.level}
            </span>
            <span className="text-[#f1f5f9] break-all">{log.message}</span>
          </div>
        ))}
        {logs.length === 0 && (
          <div className="text-[#4b5563] text-center pt-8">No logs available</div>
        )}
      </div>
    </div>
  );
}
