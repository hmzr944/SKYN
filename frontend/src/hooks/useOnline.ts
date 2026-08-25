import { useEffect, useState } from "react";
import { Platform } from "react-native";

/**
 * Y a-t-il un reseau ?
 *
 * L'analyse part sur un serveur : sans reseau, elle echoue apres que la
 * personne a tourne la tete devant sa camera pendant dix secondes. L'echec est
 * bien traite ensuite, mais il arrive trop tard — autant le dire avant.
 *
 * LIMITE ASSUMEE : seul le web expose un etat de connexion fiable sans
 * dependance supplementaire. Sur mobile, ce crochet rend `true` faute de mieux,
 * et c'est volontaire : afficher « hors ligne » a quelqu'un qui est connecte
 * serait pire que de ne rien afficher. La detection native demanderait
 * `@react-native-community/netinfo`, qui vaudra la peine le jour ou l'app
 * fera plus d'un appel reseau.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof window === "undefined") return;
    const nav = window.navigator as Navigator | undefined;
    if (!nav || typeof nav.onLine !== "boolean") return;

    setOnline(nav.onLine);
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return online;
}
