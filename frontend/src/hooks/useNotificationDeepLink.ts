import { useEffect } from "react";
import { Platform } from "react-native";
import * as Notifications from "expo-notifications";
import { useRouter } from "expo-router";

/**
 * Ferme la boucle rappel -> action : sans ceci, taper "7 jours dans cette
 * Phase" ne faisait que ramener sur l'app a l'endroit ou elle en etait,
 * jamais sur le scan que la notification demandait. Ne gere que le cas
 * app deja residente (premier plan ou arriere-plan) — un tap a froid,
 * app totalement fermee, retomberait sur la sequence d'ouverture animee
 * de index.tsx, dont les cibles sont mesurees pour /auth et /dashboard
 * uniquement ; y greffer un troisieme atterrissage casserait ce calcul
 * sans qu'aucun rappel de Phase ne se perde vraiment (il reste dans le
 * centre de notifications du systeme).
 */
export function useNotificationDeepLink() {
  const router = useRouter();

  useEffect(() => {
    if (Platform.OS !== "ios" && Platform.OS !== "android") return;

    const sub = Notifications.addNotificationResponseReceivedListener((response) => {
      const kind = response.notification.request.content.data?.kind;
      if (kind === "phase-checkpoint") {
        router.push("/camera-guided");
      }
    });
    return () => sub.remove();
  }, [router]);
}
