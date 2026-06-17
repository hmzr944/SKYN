import { useEffect, useRef } from 'react';

interface Props {
  symbol: string;
  className?: string;
}

export default function Chart({ symbol, className = '' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let chart: any;

    import('lightweight-charts').then(({ createChart, ColorType, CrosshairMode }) => {
      chart = createChart(containerRef.current!, {
        layout: {
          background: { type: ColorType.Solid, color: '#0a0a0a' },
          textColor: '#9ca3af',
        },
        grid: {
          vertLines: { color: '#1a1a1a' },
          horzLines: { color: '#1a1a1a' },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: { borderColor: '#262626' },
        timeScale: { borderColor: '#262626', timeVisible: true },
        width: containerRef.current!.clientWidth,
        height: containerRef.current!.clientHeight,
      });

      chart.addCandlestickSeries({
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      });

      const obs = new ResizeObserver(() => {
        if (containerRef.current && chart) {
          chart.applyOptions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
          });
        }
      });
      obs.observe(containerRef.current!);
      (containerRef.current as any)._obs = obs;
    });

    return () => {
      if ((containerRef.current as any)?._obs) {
        (containerRef.current as any)._obs.disconnect();
      }
      if (chart) chart.remove();
    };
  }, []);

  return (
    <div className={`relative bg-[#0a0a0a] ${className}`}>
      <div className="absolute top-3 left-3 z-10 font-mono text-sm font-bold text-white bg-black/60 px-2 py-0.5 rounded">
        {symbol}
        <span className="ml-2 text-xs text-gray-500 font-normal">Live</span>
      </div>
      <div ref={containerRef} className="w-full h-full" />
    </div>
  );
}
