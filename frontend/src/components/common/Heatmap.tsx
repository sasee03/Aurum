import { cn } from '@/utils/cn';

// Helper to determine color based on density (0-4)
function getHeatmapColor(density: number) {
  switch (density) {
    case 0: return 'bg-[#1a1b28]';
    case 1: return 'bg-[#f59e0b]/20';
    case 2: return 'bg-[#f59e0b]/50';
    case 3: return 'bg-[#f59e0b]/80';
    case 4: return 'bg-[#f59e0b]';
    default: return 'bg-[#1a1b28]';
  }
}

interface HeatmapProps {
  pattern: number[][]; // 2D array representing rows/cols of density blocks
}

export function Heatmap({ pattern }: HeatmapProps) {
  return (
    <div className="flex flex-col w-full">
      <div className="flex flex-col gap-1 w-full">
        {pattern.map((row, rowIndex) => (
          <div key={rowIndex} className="flex gap-1 w-full">
            {row.map((val, colIndex) => (
              <div
                key={colIndex}
                className={cn(
                  'h-4 flex-1 rounded-sm transition-colors duration-300 hover:opacity-80',
                  getHeatmapColor(val)
                )}
                title={`Density score: ${val}`}
              />
            ))}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between mt-3 text-[10px] font-medium text-[#4b5563]">
        <span>Low null density</span>
        <span>High null density</span>
      </div>
    </div>
  );
}
