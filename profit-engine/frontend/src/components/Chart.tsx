import { useEffect, useRef } from 'react';

interface Props {
  symbol: string;
  className?: string;
}

export default function Chart({ symbol, className = '' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    let chart: any;
    let series: any;

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

      series = chart.addCandlestickSeries({
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
      });

      chartRef.current = { chart, series };

      const observer = new ResizeObserver(() => {
        if (containerRef.current && chart) {
          chart.applyOptions({
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
          });
        }
      });
      observer.observe(containerRef.current!);
      (containerRef.current as any)._observer = observer;
    });

    return () => {
      if ((containerRef.current as any)?._observer) {
        (containerRef.current as any)._observer.disconnect();
      }
      if (chart) chart.remove();
    };
  }, []);

  return (
    <div className={`relative bg-[#0a0a0a] ${className}`}>
      <div className="absolute top-3 left-3 z-10 font-mono text-sm font-bold text-white bg-black/60 px-2 py-0.5 rounded">
        {symbol}
        <span className="ml-2 text-xs text-gray-500 font-normal">Graphique en temps réel</span>
      </div>
      <div
        className="absolute inset-0 flex items-center justify-center text-gray-600 text-sm"
        style={{ zIndex: 1 }}
      >
        Les données de bougie apparaîtront au prochain cycle d&#39;analyse
      </div>
      <div ref={containerRef} className="w-full h-full" style={{ position: 'relative', zIndex: 2 }} />
    </div>
  );
}
