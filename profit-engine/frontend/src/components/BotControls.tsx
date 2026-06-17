interface Props {
  running: boolean;
  connected: boolean;
  onToggle: (running: boolean) => void;
}

export default function BotControls({ running, connected, onToggle }: Props) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-1.5">
        <div className={`w-2 h-2 rounded-full ${
          connected ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
        }`} />
        <span className="text-xs text-gray-400">
          {connected ? 'Connecté' : 'Reconnexion...'}
        </span>
      </div>

      <span className="text-xs font-mono bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 px-2 py-0.5 rounded">
        PAPER
      </span>

      <button
        onClick={() => onToggle(!running)}
        className={`px-3 py-1.5 rounded text-xs font-semibold transition-colors ${
          running
            ? 'bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30'
            : 'bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30'
        }`}
      >
        {running ? '⏹ Arrêter' : '▶ Démarrer'}
      </button>
    </div>
  );
}
